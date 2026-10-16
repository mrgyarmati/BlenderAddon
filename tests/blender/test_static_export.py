"""Static mesh export: FBX content, manifest, determinism and scene preservation."""

import json
import math
import os
import unittest

import bpy
from mathutils import Matrix

from tests.blender import fixtures, harness
from tests.blender.fbx_inspect import FbxFile

DATA_ATTRS = ("objects", "meshes", "scenes", "collections", "armatures", "actions", "materials", "shape_keys")


def data_counts():
    return {attr: len(getattr(bpy.data, attr)) for attr in DATA_ATTRS}


def leftover_names():
    names = []
    for attr in DATA_ATTRS:
        for idb in getattr(bpy.data, attr):
            if "__uex" in idb.name or ".uexsrc" in idb.name:
                names.append("%s:%s" % (attr, idb.name))
    return names


class StaticExportBase(unittest.TestCase):
    def setUp(self):
        harness.fresh_file()
        self._tmp = harness.TempDir()
        self.out = self._tmp.__enter__()
        self.settings = harness.export_dir_settings(self.out)
        self.cs = harness.submodule("services.context_guard")
        self.collisions = harness.submodule("services.collisions")
        self.sockets = harness.submodule("services.sockets")
        self.lods = harness.submodule("services.lods")
        self.export_service = harness.submodule("services.export_service")

    def tearDown(self):
        self._tmp.__exit__(None, None, None)

    def assertScenePreserved(self, before, counts):
        after = self.cs.ContextState(bpy.context)
        self.assertEqual(before.diff(after), [])
        self.assertEqual(data_counts(), counts)
        self.assertEqual(leftover_names(), [])

    def manifest(self):
        with open(os.path.join(self.out, "unreal_export_manifest.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def build_crate(self, lods=True, bevel=True):
        ctx = bpy.context
        crate = fixtures.crate("SM_Crate", location=(2.0, 3.0, 0.0), bevel=bevel)
        self.collisions.create_collision(ctx, crate, "CONVEX")
        self.collisions.create_collision(ctx, crate, "BOX")
        socket_world = Matrix.Translation((2.0, 3.0, 0.5)) @ Matrix.Rotation(math.radians(90.0), 4, "Z")
        self.sockets.create_socket(ctx, crate, "Lid", socket_world)
        if lods:
            self.lods.generate(ctx, crate, [0.5, 0.25])
        harness.select_only(crate)
        return crate


class StaticExportTests(StaticExportBase):
    def test_static_asset_with_lods_collisions_and_socket(self):
        self.build_crate()
        before = self.cs.ContextState(bpy.context)
        counts = data_counts()
        result = bpy.ops.uex.export(destination="SCRIPT")
        self.assertEqual(result, {"FINISHED"})
        self.assertScenePreserved(before, counts)

        for name in ("SM_Crate.fbx", "unreal_export_manifest.json", "import_to_unreal.py",
                     "unreal_export_log.txt", "unreal_export_log.jsonl"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, name)), name)
        fbx = FbxFile(os.path.join(self.out, "SM_Crate.fbx"))
        self.assertEqual(fbx.unit_scale, 1.0)
        self.assertEqual(fbx.attributes.get("SM_Crate"), "LodGroup")
        self.assertEqual(fbx.children("SM_Crate"), ["SM_Crate_LOD0", "SM_Crate_LOD1", "SM_Crate_LOD2"])
        # Main file: UE 5.8 layout, hulls named after the LOD group at the root.
        for name in ("UCX_SM_Crate_00", "UBX_SM_Crate_01"):
            self.assertIsNone(fbx.models[name]["parent"])
        self.assertNotIn("UCX_SM_Crate_LOD0_00", fbx.models)
        self.assertEqual(fbx.models["SOCKET_Lid"]["parent"], "SM_Crate_LOD0")
        # Variant: UE 5.6 layout, hulls named after LOD0 and parented to it.
        variant = FbxFile(os.path.join(self.out, "SM_Crate.ue56.fbx"))
        self.assertEqual(variant.children("SM_Crate_LOD0"),
                         ["SOCKET_Lid", "UBX_SM_Crate_LOD0_01", "UCX_SM_Crate_LOD0_00"])
        self.assertNotIn("UCX_SM_Crate_00", variant.models)
        lo, hi = fbx.bounds("SM_Crate_LOD0")
        for axis in range(3):
            self.assertAlmostEqual(lo[axis], -50.0, places=3)
            self.assertAlmostEqual(hi[axis], 50.0, places=3)

        manifest = self.manifest()
        self.assertEqual(manifest["schema_version"], 1)
        asset = manifest["assets"][0]
        self.assertEqual(asset["unreal_path"], "/Game/BlenderExports/SM_Crate")
        self.assertEqual(asset["status"], "written")
        self.assertEqual(len(asset["lods"]), 2)
        self.assertEqual(len(asset["collisions"]), 2)
        self.assertEqual(asset["material_slots"], ["M_Wood"])
        tris = asset["lod_triangles"]
        self.assertEqual(len(tris), 3)
        self.assertGreater(tris[0], tris[1])
        self.assertGreater(tris[1], tris[2])
        socket = asset["sockets"][0]
        self.assertEqual(socket["name"], "Lid")
        for got, want in zip(socket["location_cm"], (0.0, 0.0, 50.0)):
            self.assertAlmostEqual(got, want, places=3)
        self.assertAlmostEqual(socket["rotation"]["yaw"], -90.0, places=3)
        self.assertEqual(len(asset["file_sha256"]), 64)
        self.assertEqual(len(asset["source_hash"]), 64)
        self.assertEqual(asset["file_variants"]["5.6"]["file"], "SM_Crate.ue56.fbx")
        self.assertEqual(len(asset["file_variants"]["5.6"]["file_sha256"]), 64)

    def test_without_lods_helpers_are_children_of_the_mesh(self):
        self.build_crate(lods=False)
        bpy.ops.uex.export(destination="DISK")
        self.assertFalse(os.path.exists(os.path.join(self.out, "import_to_unreal.py")))
        fbx = FbxFile(os.path.join(self.out, "SM_Crate.fbx"))
        self.assertEqual(fbx.roots(), ["SM_Crate"])
        self.assertEqual(fbx.children("SM_Crate"), ["SOCKET_Lid", "UBX_SM_Crate_01", "UCX_SM_Crate_00"])
        self.assertEqual(fbx.models["SM_Crate"]["type"], "Mesh")

    def test_modifiers_exported_but_source_untouched(self):
        crate = self.build_crate(lods=False, bevel=True)
        mesh_name = crate.data.name
        bpy.ops.uex.export(destination="DISK")
        self.assertEqual(len(bpy.data.meshes[mesh_name].vertices), 8)
        self.assertEqual([m.type for m in crate.modifiers], ["BEVEL"])
        fbx = FbxFile(os.path.join(self.out, "SM_Crate.fbx"))
        self.assertGreater(len(fbx.geometry("SM_Crate")["vertices"]), 8)

    def test_multi_material_slots_keep_face_assignment(self):
        """Regression: clearing staged materials reset every face to slot 0."""
        crate = fixtures.crate("SM_TwoMat", location=(0.0, 0.0, 0.0))
        crate.data.materials.append(fixtures.material("M_Metal"))
        for poly in crate.data.polygons:
            poly.material_index = 1 if poly.center.z > 0.1 else 0
        harness.select_only(crate)
        bpy.ops.uex.export(destination="DISK")
        geometry = FbxFile(os.path.join(self.out, "SM_TwoMat.fbx")).geometry("SM_TwoMat")
        self.assertEqual(sorted(set(geometry["materials"])), [0, 1])
        self.assertEqual(self.manifest()["assets"][0]["material_slots"], ["M_Wood", "M_Metal"])

    def test_negative_scale_keeps_outward_winding(self):
        crate = fixtures.crate("SM_Mirror", location=(0.0, 0.0, 0.0))
        crate.scale = (-1.0, 1.0, 1.0)
        harness.select_only(crate)
        bpy.ops.uex.export(destination="DISK")
        fbx = FbxFile(os.path.join(self.out, "SM_Mirror.fbx"))
        self.assertGreater(fbx.signed_volume("SM_Mirror"), 0.0)

    def test_world_origin_keeps_placement(self):
        crate = fixtures.crate("SM_World", location=(2.0, 3.0, 0.0))
        harness.select_only(crate)
        self.settings.origin_mode = "WORLD"
        bpy.ops.uex.export(destination="DISK")
        lo, hi = FbxFile(os.path.join(self.out, "SM_World.fbx")).bounds("SM_World")
        self.assertAlmostEqual(lo[0], 150.0, places=3)
        self.assertAlmostEqual(hi[1], 350.0, places=3)

    def test_centimetre_scene_units(self):
        bpy.context.scene.unit_settings.scale_length = 0.01
        crate = fixtures.crate("SM_Cm", location=(0.0, 0.0, 0.0), size=100.0)
        harness.select_only(crate)
        bpy.ops.uex.export(destination="DISK")
        lo, hi = FbxFile(os.path.join(self.out, "SM_Cm.fbx")).bounds("SM_Cm")
        self.assertAlmostEqual(hi[0] - lo[0], 100.0, places=3)

    def test_collection_asset_combines_members(self):
        props = fixtures.collection("Props")
        fixtures.crate("Wall", location=(0.0, 0.0, 0.0), collection=props)
        fixtures.crate("Roof", location=(0.0, 0.0, 2.0), collection=props)
        wall = bpy.data.objects["Wall"]
        self.collisions.create_collision(bpy.context, wall, "BOX")
        layer = bpy.context.view_layer.layer_collection.children["Props"]
        bpy.context.view_layer.active_layer_collection = layer
        self.settings.scope = "ACTIVE_COLLECTION"
        self.settings.grouping = "PER_COLLECTION"
        before = self.cs.ContextState(bpy.context)
        counts = data_counts()
        bpy.ops.uex.export(destination="DISK")
        self.assertScenePreserved(before, counts)
        fbx = FbxFile(os.path.join(self.out, "SM_Props.fbx"))
        self.assertEqual(fbx.roots(), ["Roof", "Wall"])
        self.assertEqual(fbx.children("Wall"), ["UBX_Wall_00"])


class StaticSafetyTests(StaticExportBase):
    def test_forced_failure_restores_names_and_cleans_up(self):
        crate = self.build_crate()
        before = self.cs.ContextState(bpy.context)
        counts = data_counts()
        prepared = self.export_service.prepare(bpy.context, "DISK")
        asset_id = prepared.plan.assets[0].id
        result = self.export_service.ExportJob(bpy.context, prepared, fail_after_staging=asset_id).run_all()
        self.assertTrue(result.failures)
        self.assertEqual(result.files[0].status, "failed")
        self.assertScenePreserved(before, counts)
        self.assertEqual(crate.name, "SM_Crate")
        self.assertFalse(os.path.exists(os.path.join(self.out, "SM_Crate.fbx")))
        manifest = self.manifest()
        self.assertEqual(manifest["assets"][0]["status"], "failed")

    def test_export_twice_is_deterministic(self):
        self.build_crate()
        bpy.ops.uex.export(destination="DISK")
        first = self.manifest()
        bpy.ops.uex.export(destination="DISK")
        second = self.manifest()
        manifest_module = harness.submodule("services.manifest")
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(manifest_module.semantic_view(first), manifest_module.semantic_view(second))

    def test_edit_mode_and_frame_are_restored(self):
        crate = self.build_crate(lods=False)
        bpy.context.scene.frame_set(7)
        bpy.ops.object.mode_set(mode="EDIT")
        before = self.cs.ContextState(bpy.context)
        bpy.ops.uex.export(destination="DISK")
        self.assertEqual(bpy.context.mode, "EDIT_MESH")
        self.assertEqual(bpy.context.active_object, crate)
        self.assertEqual(before.diff(self.cs.ContextState(bpy.context)), [])
        bpy.ops.object.mode_set(mode="OBJECT")

    def test_blocking_errors_stop_export(self):
        orphan = bpy.data.objects.new("UCX_Ghost_00", fixtures.cube_mesh("ghost"))
        fixtures.link(orphan)
        harness.select_only(orphan)
        with self.assertRaises(RuntimeError):  # operators reporting ERROR raise in Python
            bpy.ops.uex.export(destination="DISK")
        codes = [item.code for item in bpy.context.window_manager.uex.issues]
        self.assertIn("E_COLLISION_OWNER_MISSING", codes)
        self.assertEqual(os.listdir(self.out), [])

    def test_validate_operator_lists_issues(self):
        crate = fixtures.crate("Rock", location=(0.0, 0.0, 0.0))
        crate.data.uv_layers.remove(crate.data.uv_layers[0])
        harness.select_only(crate)
        self.assertEqual(bpy.ops.uex.validate(), {"FINISHED"})
        state = bpy.context.window_manager.uex
        self.assertTrue(state.validated)
        self.assertIn("W_MISSING_UV0", [item.code for item in state.issues])
        self.assertTrue(crate.uex.uuid)


if __name__ == "__main__":
    unittest.main()
