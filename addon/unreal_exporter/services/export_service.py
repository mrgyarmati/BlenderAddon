"""Export orchestration.

``prepare`` runs discover -> classify -> validate -> plan without touching
scene data (besides assigning missing export ids). ``ExportJob`` then stages,
normalizes and writes one asset per ``step`` inside a :class:`ContextGuard`,
and ``finish`` writes the manifest, import script and logs. Every staging
session is cleaned up -- and every temporary rename reverted -- in ``finally``.
"""

import datetime
import os
import time
import traceback
from dataclasses import asdict, dataclass

import bpy

from .. import constants as C
from ..domain import discovery, naming, planning, validation
from ..domain.models import AssetResult, ExportResult
from . import animation, fbx_export, ids, manifest, scene_snapshot, staging, unreal_script
from .context_guard import ContextGuard
from .logging import ExportLog


@dataclass
class Prepared:
    settings: object
    env: object
    snapshot: object
    discovery: object
    issues: tuple
    plan: object

    @property
    def blocked(self) -> bool:
        return not validation.can_export(self.issues, self.settings)

    @property
    def counts(self) -> dict:
        return validation.summarize(self.issues)


def _assign_ids(snapshot, result):
    objects = bpy.data.objects
    names = set()
    for asset in result.assets:
        names.update(asset.all_object_names)
    ids.ensure_uuids(objects[name] for name in sorted(names) if name in objects)
    for asset in result.assets:
        if asset.collection and asset.collection != C.MASTER_COLLECTION and asset.kind == C.KIND_STATIC_MESH \
                and asset.source_name == asset.collection:
            coll = bpy.data.collections.get(asset.collection)
            if coll is not None:
                ids.ensure_uuid(coll)
        if asset.action and asset.action in bpy.data.actions:
            ids.ensure_uuid(bpy.data.actions[asset.action])


def prepare(context, destination=None, assign_ids=True) -> Prepared:
    """Discover, measure, validate and plan. Only writes missing export ids.

    Runs inside a ContextGuard so Edit Mode changes are flushed to mesh data before
    measuring (the user's mode is restored afterwards).
    """
    with ContextGuard(context):
        return _prepare(context, destination, assign_ids)


def _prepare(context, destination, assign_ids) -> Prepared:
    settings, env = scene_snapshot.build_settings(context, destination)
    if assign_ids:
        ids.repair_all()
        first = scene_snapshot.take_snapshot(context)
        _assign_ids(first, discovery.discover(first, settings))
    snapshot = scene_snapshot.take_snapshot(context)
    found = discovery.discover(snapshot, settings)
    snapshot = scene_snapshot.measure(snapshot, found.assets, context)
    issues = validation.validate(snapshot, found, settings, env)
    plan = planning.build_plan(snapshot, found.assets, settings) if found.assets else None
    return Prepared(settings=settings, env=env, snapshot=snapshot, discovery=found, issues=issues, plan=plan)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _settings_payload(asset, settings) -> dict:
    data = asdict(settings)
    for key in ("export_root", "permitted_roots", "destination", "developer_mode", "debug_paths"):
        data.pop(key, None)
    data["asset_id"] = asset.id
    return data


class ExportJob:
    """Stateful export of a prepared plan, one asset per :meth:`step`."""

    def __init__(self, context, prepared: Prepared, fail_after_staging=None):
        self.context = context
        self.prepared = prepared
        self.plan = prepared.plan
        self.settings = prepared.settings
        self.root = self.settings.export_root
        self.index = 0
        self.extras = {}
        self.results = {}
        self.result = ExportResult(plan_id=self.plan.plan_id if self.plan else "", started_at=_now_iso())
        self.log = ExportLog(self.root, debug=self.settings.debug_paths)
        self.guard = None
        self._fail_after_staging = fail_after_staging  # test hook: raise after staging this asset id
        self._started = False

    # -- lifecycle

    @property
    def total(self) -> int:
        return len(self.plan.assets) if self.plan else 0

    @property
    def done(self) -> bool:
        return self.index >= self.total

    def start(self):
        if self.plan is None:
            raise RuntimeError("Nothing to export.")
        os.makedirs(self.root, exist_ok=True)
        self.guard = ContextGuard(self.context)
        self.guard.__enter__()
        self._started = True
        self.log.info("start", "Exporting %d asset(s) with plan %s" % (self.total, self.plan.plan_id[:12]),
                      profile=self.settings.profile, blender=bpy.app.version_string)
        counts = self.prepared.counts
        self.log.info("validation", "%d error(s), %d warning(s)" % (counts[C.SEVERITY_ERROR],
                                                                    counts[C.SEVERITY_WARNING]))
        for issue in self.prepared.issues:
            if issue.severity != C.SEVERITY_INFO:
                self.log.add(issue.severity, "issue", issue.message, code=issue.code)
        self.extras["__scene__"] = {"fps": self.prepared.snapshot.fps}

    def step(self) -> bool:
        """Export the next asset. Returns False when everything is done."""
        if self.done:
            return False
        asset = self.plan.assets[self.index]
        self.index += 1
        self._export_asset(asset)
        return not self.done

    def run_all(self) -> ExportResult:
        self.start()
        try:
            while self.step():
                pass
        except BaseException:
            self.finish(cancelled=True)
            raise
        return self.finish()

    def cancel(self) -> ExportResult:
        return self.finish(cancelled=True)

    # -- per asset

    def _export_asset(self, asset):
        started = time.perf_counter()
        record = AssetResult(asset_id=asset.id, asset_name=asset.asset_name, kind=asset.kind,
                             unreal_path=asset.unreal_path, relpath=asset.file_relpath)
        self.results[asset.id] = record
        self.result.files.append(record)
        session = None
        try:
            path = naming.safe_join(self.root, asset.file_relpath)
            session = staging.StagingSession(self.context.scene)
            if asset.kind == C.KIND_STATIC_MESH:
                staged = staging.stage_static(session, asset, self.settings,
                                              self.prepared.discovery.helpers.owner_of)
            elif asset.kind == C.KIND_SKELETAL_MESH:
                staged = staging.stage_skeletal(session, asset, self.settings)
            else:
                staged = animation.stage_animation(session, asset, self.settings)
            if self._fail_after_staging == asset.id:
                raise RuntimeError("forced failure after staging (test hook)")
            record.source_hash = staged.content_hash(_settings_payload(asset, self.settings))
            self.extras[asset.id] = staged.extras
            fbx_export.write_fbx(session, path, asset.kind, self.settings)
            record.file_sha256 = manifest.sha256_file(path)
            if staged.needs_lod0_variant:
                # UE 5.6 needs LOD collision under the LOD0 node (docs/compatibility.md).
                stem, ext = asset.file_relpath.rsplit(".", 1)
                variant_rel = "%s%s.%s" % (stem, C.UE56_VARIANT_SUFFIX, ext)
                variant_path = naming.safe_join(self.root, variant_rel)
                staged.use_lod0_collision_layout()
                fbx_export.write_fbx(session, variant_path, asset.kind, self.settings)
                staged.extras["file_variants"] = {
                    "5.6": {"file": variant_rel, "file_sha256": manifest.sha256_file(variant_path)},
                }
            record.status = "written"
            self.log.info("written", "%s -> %s" % (asset.asset_name, path), kind=asset.kind,
                          unreal_path=asset.unreal_path)
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            self.result.failures.append("%s: %s" % (asset.asset_name, exc))
            self.log.error("failed", "%s: %s" % (asset.asset_name, exc), trace=traceback.format_exc(limit=6))
        finally:
            if session is not None:
                for problem in session.cleanup():
                    self.result.failures.append("cleanup: %s" % problem)
                    self.log.error("cleanup", problem)
            record.seconds = round(time.perf_counter() - started, 4)

    # -- completion

    def finish(self, cancelled=False) -> ExportResult:
        result = self.result
        result.cancelled = cancelled
        try:
            if self._started and self.plan is not None:
                for asset in self.plan.assets[self.index:]:
                    if asset.id not in self.results:
                        skipped = AssetResult(asset_id=asset.id, asset_name=asset.asset_name, kind=asset.kind,
                                              unreal_path=asset.unreal_path, relpath=asset.file_relpath,
                                              status="skipped")
                        self.results[asset.id] = skipped
                        result.files.append(skipped)
                self._write_outputs()
        finally:
            if self.guard is not None:
                guard, self.guard = self.guard, None
                guard.__exit__(None, None, None)
                for problem in guard.errors:
                    result.failures.append("restore: %s" % problem)
            result.finished_at = _now_iso()
        return result

    def _write_outputs(self):
        result = self.result
        for issue in self.prepared.issues:
            if issue.severity == C.SEVERITY_WARNING:
                result.warnings.append(issue.message)
        data = manifest.build_manifest(
            self.plan, self.results, self.extras, created_at=result.started_at,
            generator={"name": C.ADDON_ID, "version": C.ADDON_VERSION_STRING,
                       "blender_version": bpy.app.version_string},
        )
        result.manifest_path = os.path.join(self.root, C.MANIFEST_FILENAME)
        manifest.write_manifest(result.manifest_path, data)
        if self.settings.destination == C.DEST_SCRIPT:
            result.script_path = os.path.join(self.root, C.IMPORT_SCRIPT_FILENAME)
            unreal_script.write_import_script(result.script_path, self.plan.plan_id)
        written = sum(1 for r in result.files if r.status == "written")
        self.log.info("finish", "%d written, %d failed%s" % (written, len(result.failures),
                                                              ", cancelled" if result.cancelled else ""))
        result.log_path = os.path.join(self.root, C.LOG_TEXT_FILENAME)
        self.log.write(result.log_path, os.path.join(self.root, C.LOG_JSON_FILENAME))


def export(context, destination=None, allow_warnings=True) -> tuple:
    """Prepare and run synchronously. Returns ``(Prepared, ExportResult | None)``."""
    prepared = prepare(context, destination)
    if prepared.plan is None or prepared.blocked:
        return prepared, None
    if not allow_warnings and prepared.counts[C.SEVERITY_WARNING]:
        return prepared, None
    return prepared, ExportJob(context, prepared).run_all()
