# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender Unreal Bridge importer (runs inside Unreal Editor 5.6+ Python).

Reads an export manifest written by the Blender add-on, imports every FBX with
explicitly configured Interchange pipelines, reconciles sockets, verifies
collisions/LODs, tags assets with their Blender source id, and writes a JSON
import receipt beside the manifest.

This file is embedded verbatim into generated ``import_to_unreal.py`` scripts
and shipped as ``blender_bridge.importer`` in the optional Unreal plugin.
It must stay standard-library only and import ``unreal`` lazily so it can be
unit-tested with a fake ``unreal`` module.
"""

import datetime
import hashlib
import json
import os
import traceback

IMPORTER_VERSION = "0.1.0"
MANIFEST_SCHEMA = "blender-unreal-bridge/manifest"
SUPPORTED_MANIFEST_VERSION = 1
RECEIPT_SCHEMA = "blender-unreal-bridge/receipt"
RECEIPT_SCHEMA_VERSION = 1
RECEIPT_FILENAME = "unreal_import_receipt.json"
INDEX_RELPATH = os.path.join("BlenderBridge", "source_index.json")
META_SOURCE_ID = "BlenderBridge.SourceId"
META_PLAN_ID = "BlenderBridge.PlanId"
META_SOURCE_HASH = "BlenderBridge.SourceHash"
SOCKET_LOCATION_TOLERANCE = 0.05  # cm
SOCKET_ROTATION_TOLERANCE = 1e-3  # matrix element difference

_unreal = None


def _ue():
    global _unreal
    if _unreal is None:
        import unreal  # noqa: PLC0415 - only available inside Unreal

        _unreal = unreal
    return _unreal


class BridgeImportError(Exception):
    pass


# ---------------------------------------------------------------- versions


def parse_engine_version(text):
    """'5.8.3-58210709+++UE5+Release-5.8' -> (5, 8)."""
    head = (text or "").split("-")[0]
    parts = head.split(".")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        raise BridgeImportError("Cannot parse Unreal engine version %r." % text)


def _set(obj, name, value):
    try:
        obj.set_editor_property(name, value)
    except Exception as exc:  # unreal raises plain Exception for unknown properties
        raise BridgeImportError("Cannot set %s.%s: %s" % (type(obj).__name__, name, exc))


class Adapter56:
    """Unreal 5.6/5.7 Interchange property spellings."""

    name = "5.6"

    def set_combine_static_meshes(self, mesh_pipeline, combine):
        _set(mesh_pipeline, "combine_static_meshes", bool(combine))

    def set_combine_skeletal_meshes(self, mesh_pipeline, combine):
        _set(mesh_pipeline, "combine_skeletal_meshes", bool(combine))

    def set_snap_to_frames(self, animation_pipeline, snap):
        _set(animation_pipeline, "snap_to_closest_frame_boundary", bool(snap))


class Adapter58(Adapter56):
    """Unreal 5.8+: combine options became enums, frame snapping became an enum."""

    name = "5.8"

    def set_combine_static_meshes(self, mesh_pipeline, combine):
        enum = _ue().InterchangeCombineStaticMeshesBehavior
        _set(mesh_pipeline, "combine_static_meshes_behavior", enum.ALL if combine else enum.DO_NOT_COMBINE)

    def set_combine_skeletal_meshes(self, mesh_pipeline, combine):
        enum = _ue().InterchangeCombineSkeletalMeshesBehavior
        _set(mesh_pipeline, "combine_skeletal_meshes_behavior", enum.BY_SKELETON if combine else enum.DO_NOT_COMBINE)

    def set_snap_to_frames(self, animation_pipeline, snap):
        enum = _ue().InterchangeFrameAlignment
        _set(animation_pipeline, "frame_alignment", enum.SNAP_TO_CLOSEST if snap else enum.NONE)


def select_adapter(version):
    if version < (5, 6):
        raise BridgeImportError("Unreal %d.%d is not supported; the bridge needs Unreal 5.6 or newer." % version)
    if version >= (5, 8):
        return Adapter58()
    return Adapter56()


# ---------------------------------------------------------------- manifest


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("schema") != MANIFEST_SCHEMA:
        raise BridgeImportError("%s is not a Blender Unreal Bridge manifest." % path)
    version = data.get("schema_version")
    if not isinstance(version, int) or version > SUPPORTED_MANIFEST_VERSION:
        raise BridgeImportError(
            "Manifest schema_version %r is not supported by importer %s (supports <= %d)."
            % (version, IMPORTER_VERSION, SUPPORTED_MANIFEST_VERSION))
    return data


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_file(asset, adapter):
    """(relative path, sha256) to import: an engine-specific variant when the manifest has one.

    LOD assets with collision ship a ``.ue56.fbx`` variant because UE 5.6 and 5.8
    expect LOD-group collision in incompatible layouts.
    """
    variant = (asset.get("file_variants") or {}).get(adapter.name)
    if variant:
        return variant["file"], variant.get("file_sha256", "")
    return asset["file"], asset.get("file_sha256", "")


def resolve_file(manifest_dir, relpath):
    parts = relpath.replace("\\", "/").split("/")
    if relpath.startswith(("/", "\\")) or ".." in parts or ":" in relpath:
        raise BridgeImportError("Refusing manifest file path %r outside the manifest folder." % relpath)
    return os.path.normpath(os.path.join(manifest_dir, *parts))


# ---------------------------------------------------------------- pipelines


def _vertex_color_option(options):
    enum = _ue().InterchangeVertexColorImportOption
    return enum.IVCIO_REPLACE if options.get("vertex_colors", "replace") == "replace" else enum.IVCIO_IGNORE


def build_pipeline(asset, options, adapter, skeleton=None):
    """Configure an InterchangeGenericAssetsPipeline explicitly for one asset."""
    ue = _ue()
    kind = asset["kind"]
    pipeline = ue.InterchangeGenericAssetsPipeline()
    common = pipeline.get_editor_property("common_meshes_properties")
    meshes = pipeline.get_editor_property("mesh_pipeline")
    skel = pipeline.get_editor_property("common_skeletal_meshes_and_animations_properties")
    anim = pipeline.get_editor_property("animation_pipeline")
    materials = pipeline.get_editor_property("material_pipeline")

    _set(pipeline, "use_source_name_for_asset", False)
    _set(pipeline, "reimport_strategy", ue.ReimportStrategyFlags.APPLY_NO_PROPERTIES)
    _set(materials, "import_materials", bool(options.get("import_materials", False)))
    _set(materials.get_editor_property("texture_pipeline"), "import_textures",
         bool(options.get("import_textures", False)))

    _set(common, "import_lods", bool(options.get("import_lods", True)))
    _set(common, "import_sockets", bool(options.get("import_sockets", True)))
    _set(common, "bake_meshes", True)
    _set(common, "bake_pivot_meshes", False)
    _set(common, "keep_sections_separate", False)
    _set(common, "recompute_normals", False)
    _set(common, "recompute_tangents", options.get("normals") != "import_normals_and_tangents")
    _set(common, "use_mikk_t_space", True)
    _set(common, "vertex_color_import_option", _vertex_color_option(options))
    # Mesh type is forced below; never touch auto_detect_mesh_type (deprecated and
    # rejected on set in 5.8).

    _set(meshes, "build_nanite", bool(options.get("build_nanite", False)))
    _set(meshes, "generate_lightmap_u_vs", bool(options.get("generate_lightmap_uvs", False)))
    _set(meshes, "collision", True)
    _set(meshes, "import_collision_according_to_mesh_name", True)
    _set(meshes, "one_convex_hull_per_ucx", bool(options.get("one_convex_hull_per_ucx", True)))
    # Fallback hulls only for static meshes without collision helpers, so custom
    # collision is never doubled by an automatic hull.
    auto = bool(options.get("auto_generate_collision")) and not asset.get("collisions")
    fallback = ue.InterchangeMeshCollision.CONVEX18DOP if auto else ue.InterchangeMeshCollision.NONE
    _set(meshes, "fallback_collision_type", fallback)
    _set(meshes, "import_morph_targets", bool(options.get("import_morph_targets", True)))
    _set(meshes, "create_physics_asset", bool(options.get("create_physics_asset", True)))

    if kind == "STATIC_MESH":
        _set(common, "force_all_mesh_as_type", ue.InterchangeForceMeshType.IFMT_STATIC_MESH)
        _set(meshes, "import_static_meshes", True)
        _set(meshes, "import_skeletal_meshes", False)
        adapter.set_combine_static_meshes(meshes, True)
        _set(anim, "import_animations", False)
    elif kind == "SKELETAL_MESH":
        _set(common, "force_all_mesh_as_type", ue.InterchangeForceMeshType.IFMT_SKELETAL_MESH)
        _set(meshes, "import_static_meshes", False)
        _set(meshes, "import_skeletal_meshes", True)
        adapter.set_combine_skeletal_meshes(meshes, True)
        _set(anim, "import_animations", False)
        if skeleton is not None:
            _set(skel, "skeleton", skeleton)
    elif kind == "ANIMATION":
        if skeleton is None:
            raise BridgeImportError("Animation %s needs an existing skeleton." % asset["asset_name"])
        _set(common, "force_all_mesh_as_type", ue.InterchangeForceMeshType.IFMT_SKELETAL_MESH)
        _set(meshes, "import_static_meshes", False)
        _set(meshes, "import_skeletal_meshes", False)
        _set(skel, "skeleton", skeleton)
        _set(skel, "import_only_animations", True)
        _set(anim, "import_animations", True)
        _set(anim, "import_bone_tracks", True)
        _set(anim, "animation_range", ue.InterchangeAnimationRange.TIMELINE)
        fps = (asset.get("animation") or {}).get("fps") or 0
        _set(anim, "custom_bone_animation_sample_rate", int(round(fps)) if fps else 0)
        adapter.set_snap_to_frames(anim, True)
    else:
        raise BridgeImportError("Unknown asset kind %r." % kind)
    return pipeline


# ---------------------------------------------------------------- index


def _project_saved_dir():
    ue = _ue()
    try:
        return ue.Paths.project_saved_dir()
    except Exception:
        return None


class SourceIndex:
    """Blender source id -> Unreal object path, persisted in the project's Saved folder."""

    def __init__(self, path):
        self.path = path
        self.entries = {}
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    self.entries = json.load(handle).get("entries", {})
            except (OSError, ValueError):
                self.entries = {}

    def get(self, source_id):
        return self.entries.get(source_id)

    def set(self, source_id, unreal_path):
        self.entries[source_id] = unreal_path

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"entries": self.entries}, handle, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- unreal helpers


def _object_path(package_path):
    """'/Game/A/SM_X' -> '/Game/A/SM_X.SM_X'."""
    if "." in package_path.rsplit("/", 1)[-1]:
        return package_path
    return "%s.%s" % (package_path, package_path.rsplit("/", 1)[-1])


def _package_path(object_path):
    return object_path.split(".", 1)[0]


def asset_exists(package_path):
    return bool(_ue().EditorAssetLibrary.does_asset_exist(package_path))


def load_asset(package_path):
    if not asset_exists(package_path):
        return None
    return _ue().EditorAssetLibrary.load_asset(_object_path(package_path))


def _metadata(asset_obj, tag):
    try:
        return _ue().EditorAssetLibrary.get_metadata_tag(asset_obj, tag) or ""
    except Exception:
        return ""


def find_existing(asset, index):
    """Locate an earlier import of this Blender source (by id) at another path."""
    planned = asset["unreal_path"]
    previous = index.get(asset["id"])
    if previous and previous.lower() != planned.lower() and asset_exists(previous):
        obj = load_asset(previous)
        if obj is not None and _metadata(obj, META_SOURCE_ID) == asset["id"]:
            return previous
    return None


def _vector(values):
    return _ue().Vector(x=float(values[0]), y=float(values[1]), z=float(values[2]))


def _rotator(rot):
    return _ue().Rotator(roll=float(rot["roll"]), pitch=float(rot["pitch"]), yaw=float(rot["yaw"]))


def _rotation_matrix(roll, pitch, yaw):
    import math

    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    return (
        (cp * cy, cp * sy, sp),
        (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp),
        (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp),
    )


def rotators_equal(a, b, tolerance=SOCKET_ROTATION_TOLERANCE):
    ma = _rotation_matrix(*a)
    mb = _rotation_matrix(*b)
    return all(abs(ma[i][j] - mb[i][j]) <= tolerance for i in range(3) for j in range(3))


def reconcile_sockets(static_mesh, sockets, messages):
    """Make the static mesh sockets match the manifest (add missing, fix drifted)."""
    ue = _ue()
    added, corrected, ok = 0, 0, 0
    for spec in sockets:
        name = spec["name"]
        location = spec["location_cm"]
        rotation = spec["rotation"]
        scale = spec.get("scale", [1.0, 1.0, 1.0])
        socket = static_mesh.find_socket(name)
        if socket is None:
            socket = ue.StaticMeshSocket(static_mesh)
            socket.set_editor_property("socket_name", name)
            socket.set_editor_property("relative_location", _vector(location))
            socket.set_editor_property("relative_rotation", _rotator(rotation))
            socket.set_editor_property("relative_scale", _vector(scale))
            static_mesh.add_socket(socket)
            added += 1
            continue
        loc = socket.get_editor_property("relative_location")
        rot = socket.get_editor_property("relative_rotation")
        loc_ok = all(abs(a - b) <= SOCKET_LOCATION_TOLERANCE for a, b in zip((loc.x, loc.y, loc.z), location))
        rot_ok = rotators_equal((rot.roll, rot.pitch, rot.yaw), (rotation["roll"], rotation["pitch"], rotation["yaw"]))
        if loc_ok and rot_ok:
            ok += 1
            continue
        socket.set_editor_property("relative_location", _vector(location))
        socket.set_editor_property("relative_rotation", _rotator(rotation))
        socket.set_editor_property("relative_scale", _vector(scale))
        corrected += 1
    if added:
        messages.append("added %d socket(s) missing after FBX import" % added)
    if corrected:
        messages.append("corrected %d socket transform(s) to the manifest values" % corrected)
    return {"sockets_ok": ok, "sockets_added": added, "sockets_corrected": corrected}


def collision_counts(static_mesh):
    body = static_mesh.get_editor_property("body_setup")
    if body is None:
        return {"box": 0, "sphere": 0, "capsule": 0, "convex": 0}
    agg = body.get_editor_property("agg_geom")
    return {
        "box": len(agg.get_editor_property("box_elems")),
        "sphere": len(agg.get_editor_property("sphere_elems")),
        "capsule": len(agg.get_editor_property("sphyl_elems")),
        "convex": len(agg.get_editor_property("convex_elems")),
    }


def expected_collision_counts(asset, options):
    counts = {"box": 0, "sphere": 0, "capsule": 0, "convex": 0}
    key = {"BOX": "box", "SPHERE": "sphere", "CAPSULE": "capsule", "CONVEX": "convex"}
    for col in asset.get("collisions", []):
        counts[key[col["shape"]]] += 1
    return counts


def collisions_match(actual, asset, options):
    """True when the imported simple collision matches what the manifest asked for."""
    if not asset.get("collisions"):
        total = sum(actual.values())
        return total >= 1 if options.get("auto_generate_collision") else total == 0
    expected = expected_collision_counts(asset, options)
    for key, want in expected.items():
        if key == "convex" and not options.get("one_convex_hull_per_ucx", True):
            if actual[key] < want:  # Unreal may decompose a UCX into several hulls
                return False
        elif actual[key] != want:
            return False
    return True


def verify_static(static_mesh, asset, options, messages):
    checks = {}
    actual = collision_counts(static_mesh)
    checks["collisions"] = actual
    checks["collisions_ok"] = collisions_match(actual, asset, options)
    if not checks["collisions_ok"]:
        messages.append("collision differs from manifest: expected %s%s, got %s" % (
            expected_collision_counts(asset, options),
            " (or an automatic hull)" if options.get("auto_generate_collision") else "", actual))
    lods = static_mesh.get_num_lods()
    checks["lods"] = lods
    expected_lods = 1 + len(asset.get("lods", []))
    checks["lods_ok"] = lods == expected_lods
    if lods != expected_lods:
        messages.append("LOD count %d differs from manifest (%d)" % (lods, expected_lods))
    slots = [str(m.get_editor_property("material_slot_name")) for m in static_mesh.get_editor_property("static_materials")]
    checks["material_slots"] = slots
    return checks


def apply_root_motion(anim_sequence, asset):
    ue = _ue()
    policy = (asset.get("animation") or {}).get("root_motion", "NONE")
    enable = policy == "ROOT_BONE" or policy == "OBJECT_TO_ROOT"
    anim_sequence.set_editor_property("enable_root_motion", enable)
    if enable:
        anim_sequence.set_editor_property("root_motion_root_lock", ue.RootMotionRootLock.ANIM_FIRST_FRAME)
    return {"enable_root_motion": enable}


def verify_animation(anim_sequence, asset, messages):
    checks = {}
    try:
        length = float(anim_sequence.get_play_length())
    except Exception:
        length = float(anim_sequence.get_editor_property("sequence_length"))
    checks["play_length"] = round(length, 5)
    expected = (asset.get("animation") or {}).get("expected_length_seconds")
    if expected is not None:
        ok = abs(length - expected) <= 0.5 / max(1.0, (asset.get("animation") or {}).get("fps") or 30.0)
        checks["length_ok"] = ok
        if not ok:
            messages.append("animation length %.4fs differs from manifest %.4fs" % (length, expected))
    return checks


def tag_asset(asset_obj, asset, plan_id):
    lib = _ue().EditorAssetLibrary
    lib.set_metadata_tag(asset_obj, META_SOURCE_ID, asset["id"])
    lib.set_metadata_tag(asset_obj, META_PLAN_ID, plan_id)
    lib.set_metadata_tag(asset_obj, META_SOURCE_HASH, asset.get("source_hash", ""))


def _primary_class(kind):
    ue = _ue()
    return {"STATIC_MESH": ue.StaticMesh, "SKELETAL_MESH": ue.SkeletalMesh, "ANIMATION": ue.AnimSequence}[kind]


# ---------------------------------------------------------------- import


def import_asset(asset, manifest, manifest_dir, adapter, index, skeletons):
    ue = _ue()
    options = manifest.get("import_options", {})
    entry = {
        "asset_id": asset["id"],
        "kind": asset["kind"],
        "unreal_path": asset["unreal_path"],
        "status": "failed",
        "objects": [],
        "messages": [],
        "checks": {},
    }
    messages = entry["messages"]
    if asset.get("status") not in (None, "written", "planned"):
        entry["status"] = "skipped"
        messages.append("export status was %r" % asset.get("status"))
        return entry
    relpath, checksum = select_file(asset, adapter)
    if relpath != asset["file"]:
        messages.append("using engine-specific file %s" % relpath)
    fbx = resolve_file(manifest_dir, relpath)
    if not os.path.isfile(fbx):
        raise BridgeImportError("FBX file %s is missing." % relpath)
    if checksum and sha256_file(fbx) != checksum:
        raise BridgeImportError("FBX file %s changed after export (checksum mismatch)." % relpath)

    target_path = asset["unreal_path"]
    previous = find_existing(asset, index)
    policy = options.get("reimport_policy", "UPDATE_EXISTING")
    if previous:
        if policy == "FOLLOW_RENAME" and not asset_exists(target_path):
            if not ue.EditorAssetLibrary.rename_asset(previous, target_path):
                raise BridgeImportError("Could not rename %s to %s." % (previous, target_path))
            messages.append("renamed existing asset %s to follow the Blender rename" % previous)
        else:
            target_path = previous
            messages.append("updated existing asset at %s (source was renamed in Blender)" % previous)
    existed = asset_exists(target_path)
    destination, _, name = target_path.rpartition("/")

    skeleton = None
    if asset["kind"] in ("SKELETAL_MESH", "ANIMATION"):
        skel_info = asset.get("skeleton") or {}
        skel_path = skeletons.get(skel_info.get("skeleton_asset_id") or "") or skel_info.get("unreal_skeleton_path")
        if skel_path:
            skeleton = load_asset(_package_path(skel_path))
        if asset["kind"] == "ANIMATION" and skeleton is None:
            raise BridgeImportError("Skeleton %s does not exist; import the skeletal mesh first." % skel_path)

    task = ue.AssetImportTask()
    task.set_editor_property("filename", fbx)
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("replace_existing_settings", False)
    task.set_editor_property("save", True)
    task.set_editor_property("async_", False)
    stack = ue.InterchangePipelineStackOverride()
    stack.add_pipeline(build_pipeline(asset, options, adapter, skeleton))
    task.set_editor_property("options", stack)
    ue.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    imported = [o for o in (task.get_objects() or []) if o is not None]
    entry["objects"] = sorted(o.get_path_name() for o in imported)
    primary_cls = _primary_class(asset["kind"])
    primary = None
    for obj in imported:
        if isinstance(obj, primary_cls):
            if _package_path(obj.get_path_name()).lower() == target_path.lower():
                primary = obj
                break
            primary = primary or obj
    if primary is None:
        raise BridgeImportError("Unreal did not create a %s for %s." % (primary_cls.__name__, asset["asset_name"]))

    if asset["kind"] == "STATIC_MESH":
        if asset.get("sockets"):
            entry["checks"].update(reconcile_sockets(primary, asset["sockets"], messages))
        entry["checks"].update(verify_static(primary, asset, options, messages))
    elif asset["kind"] == "SKELETAL_MESH":
        skel = primary.get_editor_property("skeleton")
        if skel is not None:
            skeletons[asset["id"]] = _package_path(skel.get_path_name())
            entry["checks"]["skeleton"] = _package_path(skel.get_path_name())
    elif asset["kind"] == "ANIMATION":
        entry["checks"].update(apply_root_motion(primary, asset))
        entry["checks"].update(verify_animation(primary, asset, messages))

    tag_asset(primary, asset, manifest.get("plan_id", ""))
    ue.EditorAssetLibrary.save_loaded_asset(primary, False)
    index.set(asset["id"], _package_path(primary.get_path_name()))
    entry["unreal_path"] = _package_path(primary.get_path_name())
    entry["status"] = "updated" if existed else "created"
    return entry


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(manifest_path, receipt_path=None, only_ids=None):
    """Import every asset of a manifest. Returns the receipt dict."""
    ue = _ue()
    manifest_path = os.path.abspath(manifest_path)
    manifest_dir = os.path.dirname(manifest_path)
    receipt_path = receipt_path or os.path.join(manifest_dir, RECEIPT_FILENAME)
    started = _now()
    engine = ue.SystemLibrary.get_engine_version()
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "importer_version": IMPORTER_VERSION,
        "engine_version": engine,
        "started_at": started,
        "finished_at": "",
        "plan_id": "",
        "adapter": "",
        "results": [],
        "errors": [],
    }
    try:
        manifest = load_manifest(manifest_path)
        receipt["plan_id"] = manifest.get("plan_id", "")
        adapter = select_adapter(parse_engine_version(engine))
        receipt["adapter"] = adapter.name
        saved = _project_saved_dir()
        index = SourceIndex(os.path.join(saved, INDEX_RELPATH) if saved else None)
        skeletons = {}
        for asset in manifest["assets"]:
            if only_ids and asset["id"] not in only_ids:
                continue
            try:
                entry = import_asset(asset, manifest, manifest_dir, adapter, index, skeletons)
            except Exception as exc:  # report per asset and keep going
                entry = {
                    "asset_id": asset.get("id"),
                    "kind": asset.get("kind"),
                    "unreal_path": asset.get("unreal_path"),
                    "status": "failed",
                    "objects": [],
                    "messages": [str(exc)],
                    "checks": {},
                }
                if not isinstance(exc, BridgeImportError):
                    entry["traceback"] = traceback.format_exc()
                ue.log_error("[BlenderBridge] %s: %s" % (asset.get("asset_name"), exc))
            else:
                ue.log("[BlenderBridge] %s %s" % (entry["status"], entry["unreal_path"]))
                for msg in entry["messages"]:
                    ue.log_warning("[BlenderBridge] %s: %s" % (asset.get("asset_name"), msg))
            receipt["results"].append(entry)
        index.save()
    except Exception as exc:
        receipt["errors"].append(str(exc))
        ue.log_error("[BlenderBridge] import aborted: %s" % exc)
    receipt["finished_at"] = _now()
    tmp = receipt_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
    os.replace(tmp, receipt_path)
    failed = [r for r in receipt["results"] if r["status"] == "failed"]
    ue.log("[BlenderBridge] import finished: %d ok, %d failed, receipt %s"
           % (len(receipt["results"]) - len(failed), len(failed), receipt_path))
    return receipt
