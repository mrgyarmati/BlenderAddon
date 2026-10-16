"""Export manifest: build, serialize, load and migrate (pure, no bpy).

The manifest is the contract between the Blender exporter and the Unreal
importer. It is versioned by ``schema_version``; readers migrate older
versions forward and refuse versions newer than they understand.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile

from .. import constants as C
from ..domain.models import AssetResult, ExportAsset, ExportPlan


class ManifestError(ValueError):
    pass


# version -> function(data) returning data at version + 1
MIGRATIONS = {}


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_entry(asset: ExportAsset, plan: ExportPlan, result: AssetResult | None, extra: dict) -> dict:
    folder, _, name = asset.unreal_path.rpartition("/")
    entry = {
        "id": asset.id,
        "kind": asset.kind,
        "asset_name": asset.asset_name,
        "unreal_path": asset.unreal_path,
        "destination_path": folder or "/",
        "file": asset.file_relpath,
        "source": {
            "name": asset.source_name,
            "collection": asset.collection,
            "objects": list(asset.all_object_names),
            "object_ids": list(asset.source_object_ids),
            "sanitized_from": asset.sanitized_from,
        },
        "lods": [
            {"index": lod.index, "object": lod.object_name, "generated": lod.generated}
            for lod in asset.lods
        ],
        "collisions": [
            {"object": c.object_name, "shape": c.shape, "index": c.index} for c in asset.collisions
        ],
        "sockets": [],
        "skeleton": None,
        "animation": None,
        "material_slots": [],
        "morph_targets": [],
        "triangles": 0,
        "status": result.status if result else "planned",
        "file_sha256": result.file_sha256 if result else "",
        "source_hash": result.source_hash if result else "",
        "warnings": list(result.warnings) if result else [],
    }
    if asset.kind in (C.KIND_SKELETAL_MESH, C.KIND_ANIMATION):
        entry["skeleton"] = {
            "armature": asset.armature,
            "unreal_skeleton_path": asset.skeleton_path,
            "skeleton_asset_id": asset.skeleton_asset_id,
        }
    if asset.kind == C.KIND_ANIMATION:
        settings = plan.settings
        entry["animation"] = {
            "action": asset.action,
            "frame_start": asset.frame_start,
            "frame_end": asset.frame_end,
            "sample_step": settings.sample_step,
            "root_motion": settings.root_motion,
            "nla": settings.nla_policy,
        }
    # Facts measured while staging (socket transforms, material slots, ...).
    for key, value in extra.items():
        if key == "animation" and entry["animation"] is not None:
            entry["animation"].update(value)
        else:
            entry[key] = value
    return entry


def build_manifest(plan: ExportPlan, results=None, extras=None, created_at: str = "",
                   generator: dict | None = None) -> dict:
    """Assemble the manifest dict. ``results``/``extras`` are keyed by asset id."""
    results = results or {}
    extras = extras or {}
    settings = plan.settings
    return {
        "schema": C.MANIFEST_SCHEMA,
        "schema_version": C.MANIFEST_SCHEMA_VERSION,
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "created_at": created_at,
        "generator": generator or {
            "name": C.ADDON_ID,
            "version": C.ADDON_VERSION_STRING,
            "blender_version": plan.blender_version,
        },
        "unreal_target": {"min": plan.unreal_target[0], "gate": plan.unreal_target[1]},
        "units": {
            "blender_unit_scale": plan.unit_scale,
            "fbx_units": "centimeter",
            "axis_forward": "-Z",
            "axis_up": "Y",
            "handedness": "Blender (x, y, z) -> Unreal (x, -y, z)",
        },
        "settings": {
            "profile": settings.profile,
            "unreal_root": settings.unreal_root,
            "origin_mode": settings.origin_mode,
            "fps": extras.get("__scene__", {}).get("fps", 0),
        },
        "import_options": dict(plan.import_options),
        "assets": [_asset_entry(a, plan, results.get(a.id), extras.get(a.id, {})) for a in plan.assets],
    }


def dumps(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json_atomic(path: str, text: str) -> None:
    """Write via a temporary file and rename, so readers never see partial JSON."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def write_manifest(path: str, manifest: dict) -> None:
    validate_manifest(manifest)
    write_json_atomic(path, dumps(manifest))


def migrate(data: dict) -> dict:
    """Bring a manifest dict up to the current schema version."""
    if not isinstance(data, dict):
        raise ManifestError("Manifest must be a JSON object.")
    if data.get("schema") != C.MANIFEST_SCHEMA:
        raise ManifestError("Not a %s document (schema=%r)." % (C.MANIFEST_SCHEMA, data.get("schema")))
    version = data.get("schema_version")
    if not isinstance(version, int):
        raise ManifestError("Manifest has no integer schema_version.")
    if version > C.MANIFEST_SCHEMA_VERSION:
        raise ManifestError(
            "Manifest schema_version %d is newer than this add-on supports (%d); update the add-on."
            % (version, C.MANIFEST_SCHEMA_VERSION))
    while version < C.MANIFEST_SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ManifestError("No migration from manifest schema_version %d." % version)
        data = step(dict(data))
        if data.get("schema_version") != version + 1:
            raise ManifestError("Migration from version %d did not produce version %d." % (version, version + 1))
        version += 1
    return data


_REQUIRED_ASSET_KEYS = ("id", "kind", "asset_name", "unreal_path", "destination_path", "file")


def validate_manifest(data: dict) -> None:
    """Structural check of a current-version manifest (raises ManifestError)."""
    for key in ("schema", "schema_version", "plan_id", "assets", "import_options"):
        if key not in data:
            raise ManifestError("Manifest is missing '%s'." % key)
    if not isinstance(data["assets"], list):
        raise ManifestError("Manifest 'assets' must be a list.")
    seen = set()
    for index, asset in enumerate(data["assets"]):
        for key in _REQUIRED_ASSET_KEYS:
            if key not in asset:
                raise ManifestError("Asset #%d is missing '%s'." % (index, key))
        if asset["kind"] not in C.ASSET_KINDS:
            raise ManifestError("Asset #%d has unknown kind %r." % (index, asset["kind"]))
        path = asset["unreal_path"].lower()
        if path in seen:
            raise ManifestError("Duplicate unreal_path %s." % asset["unreal_path"])
        seen.add(path)
        files = [asset["file"]] + [v.get("file", "") for v in (asset.get("file_variants") or {}).values()]
        for rel in files:
            if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/") or ":" in rel:
                raise ManifestError("Asset file path %r must be relative to the manifest." % rel)


def loads(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError("Manifest is not valid JSON: %s" % exc) from exc
    data = migrate(data)
    validate_manifest(data)
    return data


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return loads(handle.read())


def semantic_view(manifest: dict) -> dict:
    """Manifest without run-specific fields, for determinism comparisons."""
    data = json.loads(dumps(manifest))
    data.pop("created_at", None)
    for asset in data.get("assets", []):
        asset.pop("file_sha256", None)
        for variant in (asset.get("file_variants") or {}).values():
            variant.pop("file_sha256", None)
    return data
