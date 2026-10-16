"""Build the acceptance fixtures in Blender and export them with the add-on.

    blender --background --factory-startup --python-exit-code 1 \
        --python scripts/make_fixture_files.py -- --out build/acceptance [--addon-dir addon]

Writes one export folder per run (static, batch, character, reimport_v1,
reimport_v2) plus ``expectations.json`` that tests/unreal/acceptance.py checks
inside Unreal. Also saves ``fixtures.blend`` for manual inspection.
"""

import argparse
import json
import math
import os
import shutil
import sys

import bmesh
import bpy
from mathutils import Matrix

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from tests.blender import fixtures, harness  # noqa: E402

UNREAL_ROOT = "/Game/Acceptance"


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(REPO_ROOT, "build", "acceptance"))
    parser.add_argument("--addon-dir", default=os.path.join(REPO_ROOT, "addon"))
    return parser.parse_args(argv)


def boxes_mesh(name, boxes, materials=()):
    """Mesh made of axis-aligned boxes given as ((x0, y0, z0), (x1, y1, z1), material_index)."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    _ = uv
    for lo, hi, mat in boxes:
        size = [hi[i] - lo[i] for i in range(3)]
        center = [(hi[i] + lo[i]) * 0.5 for i in range(3)]
        result = bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True,
                                       matrix=Matrix.Translation(center) @ Matrix.Diagonal((*size, 1.0)))
        for vert in result["verts"]:
            for face in vert.link_faces:
                face.material_index = mat
    bm.to_mesh(mesh)
    bm.free()
    for material in materials:
        mesh.materials.append(fixtures.material(material))
    return mesh


def sphere_mesh(name, segments, rings, materials=("M_A", "M_B")):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=0.5, calc_uvs=True)
    for face in bm.faces:
        face.material_index = 1 if face.calc_center_median().z > 0 else 0
    bm.to_mesh(mesh)
    bm.free()
    for material in materials:
        mesh.materials.append(fixtures.material(material))
    return mesh


def obj(name, mesh, collection, location=(0.0, 0.0, 0.0)):
    ob = bpy.data.objects.new(name, mesh)
    collection.objects.link(ob)
    ob.location = location
    return ob


def configure(scene, out_dir, unreal_root, **settings):
    s = scene.uex
    s.export_dir = out_dir
    s.unreal_root = unreal_root
    s.chosen_collections.clear()
    s.actions.clear()
    for key, value in settings.items():
        if key == "chosen":
            for coll in value:
                s.chosen_collections.add().collection = coll
        elif key == "actions":
            for action in value:
                s.actions.add().action = action
        else:
            setattr(s, key, value)


def export(out_dir):
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)
    service = harness.submodule("services.export_service")
    prepared, result = service.export(bpy.context, "SCRIPT")
    if result is None or not result.ok:
        problems = [i.message for i in prepared.issues if i.severity == "ERROR"]
        raise SystemExit("Fixture export into %s failed: %s %s" % (out_dir, problems,
                                                                  result.failures if result else ""))
    with open(os.path.join(out_dir, "unreal_export_manifest.json"), encoding="utf-8") as handle:
        return json.load(handle)


def asset_by_source(manifest, source):
    for asset in manifest["assets"]:
        if asset["source"]["name"] == source:
            return asset
    raise KeyError(source)


def build_static(ctx, root):
    collisions = harness.submodule("services.collisions")
    sockets = harness.submodule("services.sockets")
    lods = harness.submodule("services.lods")
    coll = fixtures.collection("Static")

    # Reference cube: 1 m cube with markers at +X (to x=0.75) and +Y (to y=0.6).
    ref = obj("SM_RefCube", boxes_mesh("ref_me", [
        ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0),
        ((0.5, -0.1, -0.1), (0.75, 0.1, 0.1), 0),
        ((-0.05, 0.5, -0.05), (0.05, 0.6, 0.05), 0)], ["M_Ref"]), coll, location=(5.0, 0.0, 0.0))

    # Door frame: posts and lintel, one UCX hull each; the opening must stay walkable.
    parts = [((-1.0, -0.1, 0.0), (-0.8, 0.1, 2.0)), ((0.8, -0.1, 0.0), (1.0, 0.1, 2.0)),
             ((-1.0, -0.1, 1.8), (1.0, 0.1, 2.0))]
    door = obj("SM_DoorFrame", boxes_mesh("door_me", [(lo, hi, 0) for lo, hi in parts], ["M_Door"]), coll,
               location=(0.0, 5.0, 0.0))
    for index, (lo, hi) in enumerate(parts):
        hull = obj("UCX_SM_DoorFrame_%02d" % index, boxes_mesh("door_ucx_%d" % index, [(lo, hi, 0)]), coll,
                   location=(0.0, 5.0, 0.0))
        hull.display_type = "WIRE"

    # Socket prop: Top (identity) and Side (yaw 90 in Blender).
    prop = obj("SM_SocketProp", boxes_mesh("prop_me", [((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)], ["M_Prop"]),
               coll, location=(-5.0, 0.0, 0.0))
    bpy.context.view_layer.update()
    sockets.create_socket(ctx, prop, "Top", Matrix.Translation((-5.0, 0.0, 0.5)))
    sockets.create_socket(ctx, prop, "Side", Matrix.Translation((-4.5, 0.0, 0.0))
                          @ Matrix.Rotation(math.radians(90.0), 4, "Z"))
    collisions.create_collision(ctx, prop, "BOX")

    # Authored LODs: spheres with two material slots in a fixed order.
    lod0 = obj("SM_AuthoredLOD", sphere_mesh("alod0", 32, 16), coll, location=(0.0, -5.0, 0.0))
    for index, (seg, rings) in enumerate(((16, 8), (8, 4)), start=1):
        lod = obj("SM_AuthoredLOD_LOD%d" % index, sphere_mesh("alod%d" % index, seg, rings), coll,
                  location=(0.0, -5.0, 0.0))
        lods.assign(lod0, lod, index, rename=True)

    # Auto LODs: subdivided cube with generated Decimate LODs.
    auto = obj("SM_AutoLOD", boxes_mesh("auto_me", [((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)], ["M_Auto"]),
               coll, location=(0.0, -10.0, 0.0))
    sub = auto.modifiers.new("Subdivision", "SUBSURF")
    sub.levels = 3
    bpy.context.view_layer.update()
    lods.generate(ctx, auto, [0.5, 0.25])
    auto_vertices = len(auto.data.vertices)

    # LODs + collision + socket together: the dual LOD collision names must yield exactly
    # one hull in both engines, and the socket must exist (5.8 drops sockets on LOD groups,
    # the importer re-adds them from the manifest).
    combo = obj("SM_LodCombo", boxes_mesh("combo_me", [((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)], ["M_Combo"]),
                coll, location=(0.0, -15.0, 0.0))
    combo.modifiers.new("Subdivision", "SUBSURF").levels = 2
    bpy.context.view_layer.update()
    lods.generate(ctx, combo, [0.5])
    collisions.create_collision(ctx, combo, "CONVEX")
    sockets.create_socket(ctx, combo, "Handle", Matrix.Translation((0.3, -15.0, 0.5))
                          @ Matrix.Rotation(math.radians(45.0), 4, "Z"))

    # Unicode and long names.
    obj("Kiste_Größe_Ünïcödé", boxes_mesh("uni_me", [((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)], ["M_Uni"]), coll,
        location=(10.0, 0.0, 0.0))
    obj("Prop_" + "VeryLongDescriptiveName" * 4, boxes_mesh("long_me", [((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)],
                                                            ["M_Long"]), coll, location=(12.0, 0.0, 0.0))

    configure(bpy.context.scene, os.path.join(root, "static"), UNREAL_ROOT + "/Static",
              profile="STATIC_MESH", scope="CHOSEN_COLLECTIONS", grouping="PER_OBJECT", chosen=[coll])
    manifest = export(os.path.join(root, "static"))
    assert len(auto.data.vertices) == auto_vertices, "auto LOD source mesh changed"
    assert [m.type for m in auto.modifiers] == ["SUBSURF"], "auto LOD source modifiers changed"

    def path(source):
        return asset_by_source(manifest, source)["unreal_path"]

    uni = asset_by_source(manifest, "Kiste_Größe_Ünïcödé")
    long_asset = asset_by_source(manifest, "Prop_" + "VeryLongDescriptiveName" * 4)
    return {
        "run": "static",
        "checks": [
            {"type": "static_bounds", "path": path("SM_RefCube"), "min": [-50.0, -60.0, -50.0],
             "max": [75.0, 50.0, 50.0], "materials": ["M_Ref"], "lods": 1},
            {"type": "collision", "path": path("SM_RefCube"), "min_total": 1},
            {"type": "collision", "path": path("SM_DoorFrame"), "convex": 3, "box": 0, "sphere": 0, "capsule": 0,
             "open_point_cm": [0.0, 0.0, 100.0]},
            {"type": "sockets", "path": path("SM_SocketProp"),
             "sockets": asset_by_source(manifest, "SM_SocketProp")["sockets"], "box": 1},
            {"type": "lods", "path": path("SM_AuthoredLOD"), "lods": 3, "materials": ["M_A", "M_B"],
             "decreasing": True},
            {"type": "lods", "path": path("SM_AutoLOD"), "lods": 3, "decreasing": True,
             "ratios": [[0.5, 0.15], [0.25, 0.12]]},
            {"type": "lods", "path": path("SM_LodCombo"), "lods": 2, "decreasing": True},
            {"type": "collision", "path": path("SM_LodCombo"), "convex": 1, "box": 0, "sphere": 0, "capsule": 0},
            {"type": "sockets", "path": path("SM_LodCombo"),
             "sockets": asset_by_source(manifest, "SM_LodCombo")["sockets"]},
            {"type": "exists", "path": uni["unreal_path"], "expect_name": "SM_Kiste_Gro_e_Unicode"},
            {"type": "exists", "path": long_asset["unreal_path"], "max_name_length": 64},
        ],
    }


def build_batch(ctx, root):
    collisions = harness.submodule("services.collisions")
    sockets = harness.submodule("services.sockets")
    batch_a = fixtures.collection("BatchA")
    batch_b = fixtures.collection("BatchB")
    wall = obj("Wall", boxes_mesh("wall_me", [((-1.0, -0.1, 0.0), (1.0, 0.1, 2.0), 0)], ["M_Wall"]), batch_a)
    window = obj("Window", boxes_mesh("win_me", [((-0.3, -0.12, 1.0), (0.3, 0.12, 1.5), 0)], ["M_Glass"]), batch_a)
    door = obj("Door", boxes_mesh("door2_me", [((-0.4, -0.05, 0.0), (0.4, 0.05, 2.0), 0)], ["M_Door"]), batch_b)
    bpy.context.view_layer.update()
    collisions.create_collision(ctx, wall, "BOX")
    sockets.create_socket(ctx, window, "Latch", Matrix.Translation((0.0, 0.0, 1.25)))
    collisions.create_collision(ctx, door, "CONVEX")
    configure(bpy.context.scene, os.path.join(root, "batch"), UNREAL_ROOT + "/Batch",
              profile="STATIC_MESH", scope="CHOSEN_COLLECTIONS", grouping="PER_COLLECTION", chosen=[batch_a, batch_b])
    manifest = export(os.path.join(root, "batch"))
    return {
        "run": "batch",
        "checks": [
            {"type": "collision", "path": asset_by_source(manifest, "BatchA")["unreal_path"], "box": 1, "convex": 0,
             "sphere": 0, "capsule": 0, "socket_names": ["Latch"]},
            {"type": "collision", "path": asset_by_source(manifest, "BatchB")["unreal_path"], "box": 0, "convex": 1,
             "sphere": 0, "capsule": 0, "socket_names": []},
        ],
    }


def build_character(ctx, root):
    arm, meshes, wave = fixtures.rig("Hero", location=(0.0, 20.0, 0.0), shape_key=True)
    data = arm.data
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    head = data.edit_bones.new("head")
    head.head, head.tail = (0.0, 0.0, 1.5), (0.0, 0.0, 1.9)
    head.parent = data.edit_bones["spine"]
    bpy.ops.object.mode_set(mode="OBJECT")
    meshes[0].vertex_groups.new(name="head")

    walk = bpy.data.actions.new("Walk")
    arm.animation_data.action = walk
    root_bone = arm.pose.bones["root"]
    for frame, x in ((1, 0.0), (31, 2.0)):
        root_bone.location = (x, 0.0, 0.0)
        root_bone.keyframe_insert("location", frame=frame)
    idle = bpy.data.actions.new("Idle")
    arm.animation_data.action = idle
    spine = arm.pose.bones["spine"]
    spine.rotation_mode = "XYZ"
    for frame, angle in ((1, 0.0), (31, 10.0), (61, 0.0)):
        spine.rotation_euler = (math.radians(angle), 0.0, 0.0)
        spine.keyframe_insert("rotation_euler", frame=frame)
    arm.animation_data.action = wave
    root_bone.location = (0.0, 0.0, 0.0)
    spine.rotation_euler = (0.0, 0.0, 0.0)
    arm.uex.asset_name_override = "Hero"
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    arm.select_set(True)
    configure(bpy.context.scene, os.path.join(root, "character"), UNREAL_ROOT + "/Character",
              profile="SKELETAL_MESH", scope="SELECTED", skeletal_include_animations=True,
              actions=[walk, idle], root_motion="ROOT_BONE", frame_range_mode="ACTION")
    manifest = export(os.path.join(root, "character"))
    sk = [a for a in manifest["assets"] if a["kind"] == "SKELETAL_MESH"][0]
    walk_asset = asset_by_source(manifest, "Walk")
    idle_asset = asset_by_source(manifest, "Idle")
    return {
        "run": "character",
        "checks": [
            {"type": "skeletal", "path": sk["unreal_path"], "bones": ["root", "spine", "head"],
             "morph_targets": ["Bulge"], "materials": ["M_Skin"]},
            {"type": "animation", "path": walk_asset["unreal_path"], "skeleton": sk["unreal_path"] + "_Skeleton",
             "length": 1.0, "root_motion": True},
            {"type": "animation", "path": idle_asset["unreal_path"], "skeleton": sk["unreal_path"] + "_Skeleton",
             "length": 2.0, "root_motion": True},
        ],
    }


def build_skeletal_lod(ctx, root):
    """Skeletal mesh with an authored LOD1 skinned to the same armature."""
    lods = harness.submodule("services.lods")
    arm, meshes, _action = fixtures.rig("HeroLod", location=(10.0, 20.0, 0.0))
    body = meshes[0]
    body.modifiers.new("Subdivision", "SUBSURF").levels = 2
    body.modifiers.move(len(body.modifiers) - 1, 0)  # subdivide before the armature deform
    lod1 = body.copy()
    lod1.data = body.data.copy()
    lod1.modifiers.remove(lod1.modifiers["Subdivision"])
    bpy.context.scene.collection.objects.link(lod1)
    lods.assign(body, lod1, 1, rename=True)
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    configure(bpy.context.scene, os.path.join(root, "skeletal_lod"), UNREAL_ROOT + "/SkeletalLod",
              profile="SKELETAL_MESH", scope="SELECTED", skeletal_include_animations=False)
    manifest = export(os.path.join(root, "skeletal_lod"))
    sk = manifest["assets"][0]
    return {"run": "skeletal_lod",
            "checks": [{"type": "skeletal_lods", "path": sk["unreal_path"], "lods": 2, "bones": ["root", "spine"]}]}


def build_follow(ctx, root):
    """Reimport policy FOLLOW_RENAME: renaming in Blender renames the Unreal asset."""
    coll = fixtures.collection("Follow")
    cube = obj("SM_Follow", boxes_mesh("follow_me", [((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)], ["M_Follow"]),
               coll)
    configure(bpy.context.scene, os.path.join(root, "follow_v1"), UNREAL_ROOT + "/Follow",
              profile="STATIC_MESH", scope="CHOSEN_COLLECTIONS", grouping="PER_OBJECT", chosen=[coll],
              reimport_policy="FOLLOW_RENAME")
    v1 = export(os.path.join(root, "follow_v1"))
    rename = harness.submodule("services.rename")
    rename.apply(rename.plan([cube], rename.make_transform("SET", new_name="SM_Follow_Renamed")))
    configure(bpy.context.scene, os.path.join(root, "follow_v2"), UNREAL_ROOT + "/Follow",
              profile="STATIC_MESH", scope="CHOSEN_COLLECTIONS", grouping="PER_OBJECT", chosen=[coll],
              reimport_policy="FOLLOW_RENAME")
    v2 = export(os.path.join(root, "follow_v2"))
    bpy.context.scene.uex.reimport_policy = "UPDATE_EXISTING"
    return {"v1_path": v1["assets"][0]["unreal_path"], "v2_path": v2["assets"][0]["unreal_path"]}


def build_reimport(ctx, root):
    sockets = harness.submodule("services.sockets")
    coll = fixtures.collection("Reimport")
    cube = obj("SM_Reimport", boxes_mesh("re_me", [((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0)], ["M_Re"]), coll)
    bpy.context.view_layer.update()
    sockets.create_socket(ctx, cube, "Grip", Matrix.Translation((0.0, 0.0, 0.5)))
    configure(bpy.context.scene, os.path.join(root, "reimport_v1"), UNREAL_ROOT + "/Reimport",
              profile="STATIC_MESH", scope="CHOSEN_COLLECTIONS", grouping="PER_OBJECT", chosen=[coll])
    v1 = export(os.path.join(root, "reimport_v1"))
    bpy.ops.uex.rename_preview  # keep the operator registered for interactive debugging
    rename = harness.submodule("services.rename")
    rename.apply(rename.plan([cube], rename.make_transform("SET", new_name="SM_Reimport_Renamed")))
    configure(bpy.context.scene, os.path.join(root, "reimport_v2"), UNREAL_ROOT + "/Reimport",
              profile="STATIC_MESH", scope="CHOSEN_COLLECTIONS", grouping="PER_OBJECT", chosen=[coll])
    v2 = export(os.path.join(root, "reimport_v2"))
    assert v1["assets"][0]["id"] == v2["assets"][0]["id"], "rename changed the export id"
    return {
        "run": "reimport",
        "v1_path": v1["assets"][0]["unreal_path"],
        "v2_planned_path": v2["assets"][0]["unreal_path"],
    }


def main():
    args = _args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    harness.load_addon(os.path.abspath(args.addon_dir))
    harness.fresh_file()
    ctx = bpy.context
    expectations = {"unreal_root": UNREAL_ROOT, "runs": []}
    expectations["runs"].append(build_static(ctx, out))
    expectations["runs"].append(build_batch(ctx, out))
    expectations["runs"].append(build_character(ctx, out))
    expectations["runs"].append(build_skeletal_lod(ctx, out))
    expectations["reimport"] = build_reimport(ctx, out)
    expectations["follow"] = build_follow(ctx, out)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "fixtures.blend"), check_existing=False)
    with open(os.path.join(out, "expectations.json"), "w", encoding="utf-8") as handle:
        json.dump(expectations, handle, indent=2)
    print("FIXTURES_DONE", out)


main()
