"""Unreal-side acceptance checks. Runs inside Unreal Editor (commandlet or editor).

    UnrealEditor-Cmd <project> -run=pythonscript -Script="acceptance.py <acceptance_dir> <result.json>"

For every export folder produced by scripts/make_fixture_files.py it runs the
generated ``import_to_unreal.py`` exactly as a user would, then checks the
resulting assets against ``expectations.json``. Results go to ``result.json``.
"""

import json
import math
import os
import re
import sys
import traceback

import unreal

LOCATION_TOLERANCE = 0.1  # cm
MATRIX_TOLERANCE = 1e-3


class Results:
    def __init__(self):
        self.checks = []

    def add(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        (unreal.log if ok else unreal.log_error)("[Acceptance] %s %s %s" % ("PASS" if ok else "FAIL", name, detail))

    @property
    def failures(self):
        return [c for c in self.checks if not c["ok"]]


def rotation_matrix(roll, pitch, yaw):
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    return ((cp * cy, cp * sy, sp), (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp),
            (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp))


def close(a, b, tolerance):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def load(path):
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        return None
    return unreal.EditorAssetLibrary.load_asset(path)


def run_import(folder):
    script = os.path.join(folder, "import_to_unreal.py")
    namespace = {"__file__": script, "__name__": "__bridge_acceptance__"}
    with open(script, "r", encoding="utf-8") as handle:
        exec(compile(handle.read(), script, "exec"), namespace)
    return namespace["bridge_receipt"]


_ELEM_BOX = re.compile(r"ElemBox=\(Min=\(X=([-\d.e+]+),Y=([-\d.e+]+),Z=([-\d.e+]+)\),"
                       r"Max=\(X=([-\d.e+]+),Y=([-\d.e+]+),Z=([-\d.e+]+)\)")


def hull_bounds(elem):
    """((min xyz), (max xyz)) of a KConvexElem, read from its text export.

    KConvexElem exposes no geometry properties to Python in 5.6/5.8 (ElemBox and
    VertexData are not reflected, Transform is protected), but export_text() has them.
    """
    match = _ELEM_BOX.search(elem.export_text())
    if not match:
        return None
    values = [float(v) for v in match.groups()]
    return tuple(values[:3]), tuple(values[3:])


def agg_counts(static_mesh):
    agg = static_mesh.get_editor_property("body_setup").get_editor_property("agg_geom")
    return agg, {
        "box": len(agg.get_editor_property("box_elems")),
        "sphere": len(agg.get_editor_property("sphere_elems")),
        "capsule": len(agg.get_editor_property("sphyl_elems")),
        "convex": len(agg.get_editor_property("convex_elems")),
    }


def check_static_bounds(results, check):
    sm = load(check["path"])
    results.add("exists " + check["path"], sm is not None)
    if sm is None:
        return
    box = sm.get_bounding_box()
    lo = (box.min.x, box.min.y, box.min.z)
    hi = (box.max.x, box.max.y, box.max.z)
    results.add("bounds %s" % check["path"], close(lo, check["min"], LOCATION_TOLERANCE)
                and close(hi, check["max"], LOCATION_TOLERANCE), "min=%s max=%s" % (lo, hi))
    slots = [str(m.get_editor_property("material_slot_name")) for m in sm.get_editor_property("static_materials")]
    results.add("materials %s" % check["path"], slots == check["materials"], str(slots))
    results.add("lods %s" % check["path"], sm.get_num_lods() == check["lods"], str(sm.get_num_lods()))


def check_collision(results, check):
    sm = load(check["path"])
    results.add("exists " + check["path"], sm is not None)
    if sm is None:
        return
    agg, counts = agg_counts(sm)
    if "min_total" in check:
        results.add("automatic collision %s" % check["path"], sum(counts.values()) >= check["min_total"],
                    str(counts))
    else:
        expected = {k: check[k] for k in ("box", "sphere", "capsule", "convex")}
        results.add("collision counts %s" % check["path"], counts == expected,
                    "got %s want %s" % (counts, expected))
    point = check.get("open_point_cm")
    if point:
        boxes = [hull_bounds(elem) for elem in agg.get_editor_property("convex_elems")]
        readable = [b for b in boxes if b is not None]
        results.add("hull bounds readable %s" % check["path"], len(readable) == len(boxes) and boxes,
                    "%d of %d" % (len(readable), len(boxes)))
        inside = [b for b in readable if all(b[0][i] - 0.5 <= point[i] <= b[1][i] + 0.5 for i in range(3))]
        results.add("walkable opening %s" % check["path"], readable and not inside,
                    "hulls covering %s: %s" % (point, inside))
    for name in check.get("socket_names", []):
        results.add("socket %s on %s" % (name, check["path"]), sm.find_socket(name) is not None)
    if "socket_names" in check and not check["socket_names"]:
        results.add("no leaked Latch socket on %s" % check["path"], sm.find_socket("Latch") is None)


def check_sockets(results, check):
    sm = load(check["path"])
    results.add("exists " + check["path"], sm is not None)
    if sm is None:
        return
    for spec in check["sockets"]:
        socket = sm.find_socket(spec["name"])
        results.add("socket %s" % spec["name"], socket is not None)
        if socket is None:
            continue
        loc = socket.get_editor_property("relative_location")
        rot = socket.get_editor_property("relative_rotation")
        got_loc = (loc.x, loc.y, loc.z)
        results.add("socket %s location" % spec["name"], close(got_loc, spec["location_cm"], LOCATION_TOLERANCE),
                    "got %s want %s" % (got_loc, spec["location_cm"]))
        want = rotation_matrix(spec["rotation"]["roll"], spec["rotation"]["pitch"], spec["rotation"]["yaw"])
        got = rotation_matrix(rot.roll, rot.pitch, rot.yaw)
        ok = all(abs(want[i][j] - got[i][j]) <= MATRIX_TOLERANCE for i in range(3) for j in range(3))
        results.add("socket %s rotation" % spec["name"], ok, "got (%.2f, %.2f, %.2f) want %s" % (
            rot.roll, rot.pitch, rot.yaw, spec["rotation"]))
    if "box" in check:
        _agg, counts = agg_counts(sm)
        results.add("socket prop box collision", counts["box"] == check["box"], str(counts))


def check_lods(results, check):
    sm = load(check["path"])
    results.add("exists " + check["path"], sm is not None)
    if sm is None:
        return
    lods = sm.get_num_lods()
    results.add("lod count %s" % check["path"], lods == check["lods"], str(lods))
    tris = [sm.get_num_triangles(i) for i in range(lods)]
    if check.get("decreasing"):
        results.add("lod triangles decrease %s" % check["path"], all(a > b for a, b in zip(tris, tris[1:])), str(tris))
    for index, (ratio, tolerance) in enumerate(check.get("ratios", []), start=1):
        if index < len(tris) and tris[0]:
            actual = tris[index] / float(tris[0])
            results.add("lod%d ratio %s" % (index, check["path"]), abs(actual - ratio) <= tolerance,
                        "%.3f vs %.3f" % (actual, ratio))
    if "materials" in check:
        slots = [str(m.get_editor_property("material_slot_name")) for m in sm.get_editor_property("static_materials")]
        results.add("material order %s" % check["path"], slots == check["materials"], str(slots))


def check_exists(results, check):
    path = check["path"]
    results.add("exists " + path, unreal.EditorAssetLibrary.does_asset_exist(path))
    name = path.rsplit("/", 1)[-1]
    if "expect_name" in check:
        results.add("sanitized name " + name, name == check["expect_name"])
    if "max_name_length" in check:
        results.add("name length %d <= %d" % (len(name), check["max_name_length"]),
                    len(name) <= check["max_name_length"])


def check_skeletal(results, check):
    skm = load(check["path"])
    results.add("exists " + check["path"], skm is not None)
    if skm is None:
        return
    skeleton = skm.get_editor_property("skeleton")
    pose = skeleton.get_reference_pose()
    bones = [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(pose)]
    results.add("bone hierarchy", bones == check["bones"], str(bones))
    scales_ok = True
    for bone in bones:
        xform = unreal.AnimPoseExtensions.get_ref_bone_pose(pose, bone, unreal.AnimPoseSpaces.WORLD)
        s = xform.scale3d
        scales_ok = scales_ok and close((s.x, s.y, s.z), (1.0, 1.0, 1.0), 1e-3)
    results.add("bone scale 1 (no 100x armature scale)", scales_ok)
    morphs = [str(n) for n in skm.get_all_morph_target_names()]
    results.add("morph targets", morphs == check["morph_targets"], str(morphs))
    slots = [str(m.get_editor_property("material_slot_name")) for m in skm.get_editor_property("materials")]
    results.add("skeletal material slots", slots == check["materials"], str(slots))


def check_skeletal_lods(results, check):
    skm = load(check["path"])
    results.add("exists " + check["path"], skm is not None)
    if skm is None:
        return
    # 5.8 no longer reflects LODInfo; the editor library works in both engines (and in commandlets).
    library = getattr(unreal, "EditorSkeletalMeshLibrary", None)
    lods = library.get_lod_count(skm) if library else len(skm.get_editor_property("lod_info"))
    results.add("skeletal LOD count %s" % check["path"], lods == check["lods"], str(lods))
    pose = skm.get_editor_property("skeleton").get_reference_pose()
    bones = [str(n) for n in unreal.AnimPoseExtensions.get_bone_names(pose)]
    results.add("skeletal LOD bones %s" % check["path"], bones == check["bones"], str(bones))


def check_animation(results, check):
    anim = load(check["path"])
    results.add("exists " + check["path"], anim is not None)
    if anim is None:
        return
    skeleton = anim.get_skeleton()
    got = skeleton.get_path_name().split(".")[0] if skeleton else None
    results.add("animation skeleton %s" % check["path"], got == check["skeleton"], str(got))
    length = float(anim.get_play_length())
    results.add("animation length %s" % check["path"], abs(length - check["length"]) <= 1.0 / 60.0,
                "%.4f vs %.4f" % (length, check["length"]))
    root_motion = bool(anim.get_editor_property("enable_root_motion"))
    results.add("root motion flag %s" % check["path"], root_motion == check["root_motion"], str(root_motion))


CHECKS = {
    "static_bounds": check_static_bounds,
    "collision": check_collision,
    "sockets": check_sockets,
    "lods": check_lods,
    "exists": check_exists,
    "skeletal": check_skeletal,
    "skeletal_lods": check_skeletal_lods,
    "animation": check_animation,
}


def receipt_ok(results, run, receipt, expected_status=None):
    failed = [r for r in receipt["results"] if r["status"] == "failed"]
    results.add("receipt %s: no failed imports" % run, not failed and not receipt["errors"],
                json.dumps(failed or receipt["errors"])[:400])
    if expected_status:
        statuses = sorted({r["status"] for r in receipt["results"]})
        results.add("receipt %s statuses %s" % (run, expected_status), statuses == [expected_status], str(statuses))
    for entry in receipt["results"]:
        for message in entry.get("messages", []):
            unreal.log_warning("[Acceptance] %s: %s" % (entry["unreal_path"], message))


def reimport_scenario(results, acceptance_dir, spec):
    folder = spec["v1_path"].rsplit("/", 1)[0]
    receipt = run_import(os.path.join(acceptance_dir, "reimport_v1"))
    receipt_ok(results, "reimport_v1 first", receipt, "created")
    before = sorted(unreal.EditorAssetLibrary.list_assets(folder, recursive=True))
    sm = load(spec["v1_path"])
    engine_material = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/BasicShapeMaterial")
    sm.set_material(0, engine_material)
    unreal.EditorAssetLibrary.save_loaded_asset(sm, False)

    receipt = run_import(os.path.join(acceptance_dir, "reimport_v1"))
    receipt_ok(results, "reimport_v1 again", receipt, "updated")
    after = sorted(unreal.EditorAssetLibrary.list_assets(folder, recursive=True))
    results.add("reimport does not duplicate assets", before == after, "%s -> %s" % (before, after))
    sm = load(spec["v1_path"])
    kept = sm.get_material(0)
    results.add("editor-assigned material preserved on reimport",
                kept is not None and kept.get_path_name() == engine_material.get_path_name(),
                kept.get_path_name() if kept else "None")
    results.add("socket survives reimport", sm.find_socket("Grip") is not None)

    receipt = run_import(os.path.join(acceptance_dir, "reimport_v2"))
    receipt_ok(results, "reimport_v2 renamed source", receipt, "updated")
    entry = receipt["results"][0]
    results.add("renamed source updates the original asset", entry["unreal_path"] == spec["v1_path"],
                entry["unreal_path"])
    results.add("no asset created at the renamed path",
                not unreal.EditorAssetLibrary.does_asset_exist(spec["v2_planned_path"]))
    final = sorted(unreal.EditorAssetLibrary.list_assets(folder, recursive=True))
    results.add("asset count unchanged after renamed reimport", final == before, str(final))


def static_meshes_in(folder):
    out = []
    for path in unreal.EditorAssetLibrary.list_assets(folder, recursive=True):
        asset = unreal.EditorAssetLibrary.load_asset(path)
        if isinstance(asset, unreal.StaticMesh):
            out.append(path.split(".")[0])
    return sorted(out)


def follow_rename_scenario(results, acceptance_dir, spec):
    """Reimport policy FOLLOW_RENAME: a Blender rename renames the existing Unreal asset."""
    folder = spec["v1_path"].rsplit("/", 1)[0]
    receipt_ok(results, "follow_v1", run_import(os.path.join(acceptance_dir, "follow_v1")), "created")
    receipt = run_import(os.path.join(acceptance_dir, "follow_v2"))
    receipt_ok(results, "follow_v2 renamed source", receipt, "updated")
    entry = receipt["results"][0]
    results.add("follow rename moves the asset to the new name", entry["unreal_path"] == spec["v2_path"],
                entry["unreal_path"])
    meshes = static_meshes_in(folder)
    results.add("follow rename leaves exactly one static mesh", meshes == [spec["v2_path"]], str(meshes))


def plugin_scenario(results, acceptance_dir):
    """The optional BlenderBridge plugin exposes the same importer as a module."""
    try:
        import blender_bridge  # noqa: PLC0415 - available only when the plugin is installed
    except ImportError:
        results.add("BlenderBridge plugin importable", False, "plugin not installed in the test project")
        return
    receipt = blender_bridge.import_manifest(os.path.join(acceptance_dir, "batch", "unreal_export_manifest.json"))
    receipt_ok(results, "plugin import of batch", receipt, "updated")
    results.add("plugin importer version", receipt["importer_version"] == blender_bridge.IMPORTER_VERSION,
                receipt["importer_version"])


def main(argv):
    acceptance_dir, result_path = argv[0], argv[1]
    results = Results()
    engine = unreal.SystemLibrary.get_engine_version()
    try:
        with open(os.path.join(acceptance_dir, "expectations.json"), encoding="utf-8") as handle:
            expectations = json.load(handle)
        root = expectations["unreal_root"]
        if unreal.EditorAssetLibrary.does_directory_exist(root):
            unreal.EditorAssetLibrary.delete_directory(root)
        index = os.path.join(unreal.Paths.project_saved_dir(), "BlenderBridge", "source_index.json")
        if os.path.exists(index):
            os.remove(index)
        for run in expectations["runs"]:
            receipt = run_import(os.path.join(acceptance_dir, run["run"]))
            receipt_ok(results, run["run"], receipt, "created")
            results.add("receipt %s engine adapter" % run["run"], receipt["adapter"] in ("5.6", "5.8"),
                        receipt["adapter"])
            for check in run["checks"]:
                try:
                    CHECKS[check["type"]](results, check)
                except Exception:
                    results.add("check %s %s raised" % (check["type"], check.get("path")), False,
                                traceback.format_exc())
        reimport_scenario(results, acceptance_dir, expectations["reimport"])
        follow_rename_scenario(results, acceptance_dir, expectations["follow"])
        plugin_scenario(results, acceptance_dir)
    except Exception:
        results.add("acceptance run", False, traceback.format_exc())
    payload = {"engine": engine, "checks": results.checks, "failures": len(results.failures)}
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)
    unreal.log("[Acceptance] DONE %s: %d checks, %d failures" % (engine, len(results.checks), len(results.failures)))


main(sys.argv[1:])
