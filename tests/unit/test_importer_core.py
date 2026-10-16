import importlib.util
import json
import os
import shutil
import tempfile
import unittest

from tests.unit import factories  # noqa: F401 (sys.path)
from tests.unit import fake_unreal
from unreal_exporter import constants as C
from unreal_exporter.services import unreal_script

CORE_PATH = unreal_script.CORE_TEMPLATE


def load_core():
    fake_unreal.install()
    spec = importlib.util.spec_from_file_location("bridge_importer_under_test", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._unreal = None
    return module


def write_manifest(folder, assets, options=None, version=C.MANIFEST_SCHEMA_VERSION):
    data = {
        "schema": C.MANIFEST_SCHEMA,
        "schema_version": version,
        "plan_id": "plan123",
        "import_options": options or {"one_convex_hull_per_ucx": True, "reimport_policy": "UPDATE_EXISTING"},
        "assets": assets,
    }
    path = os.path.join(folder, C.MANIFEST_FILENAME)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return path


def static_asset(name="SM_Crate", folder="/Game/Exports", file="SM_Crate.fbx", **kw):
    asset = {
        "id": "uuid-" + name,
        "kind": "STATIC_MESH",
        "asset_name": name,
        "unreal_path": folder + "/" + name,
        "destination_path": folder,
        "file": file,
        "status": "written",
        "lods": [],
        "collisions": [{"object": "UCX_" + name + "_00", "shape": "CONVEX", "index": 0}],
        "sockets": [{"name": "Lid", "location_cm": [0.0, 0.0, 50.0],
                     "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": -90.0}, "scale": [1.0, 1.0, 1.0]}],
    }
    asset.update(kw)
    return asset


class ImporterTestBase(unittest.TestCase):
    version = "5.8"

    def setUp(self):
        fake_unreal.reset(self.version)
        self.tmp = tempfile.mkdtemp(prefix="uex_importer_")
        self.saved = os.path.join(self.tmp, "Saved")
        fake_unreal.SAVED_DIR["path"] = self.saved
        self.core = load_core()
        self.export_dir = os.path.join(self.tmp, "export")
        os.makedirs(self.export_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def touch(self, rel, data=b"fbx"):
        path = os.path.join(self.export_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def result(self, receipt, asset_id):
        return [r for r in receipt["results"] if r["asset_id"] == asset_id][0]


class AdapterTests(ImporterTestBase):
    def test_version_parsing_and_selection(self):
        core = self.core
        self.assertEqual(core.parse_engine_version("5.8.3-58210709+++UE5+Release-5.8"), (5, 8))
        self.assertIsInstance(core.select_adapter((5, 6)), core.Adapter56)
        self.assertIsInstance(core.select_adapter((5, 7)), core.Adapter56)
        self.assertIsInstance(core.select_adapter((5, 8)), core.Adapter58)
        self.assertIsInstance(core.select_adapter((6, 0)), core.Adapter58)
        with self.assertRaises(core.BridgeImportError):
            core.select_adapter((5, 5))

    def test_static_pipeline_explicit_options(self):
        pipeline = self.core.build_pipeline(static_asset(), {"build_nanite": False}, self.core.Adapter58())
        mesh = pipeline.get_editor_property("mesh_pipeline")
        common = pipeline.get_editor_property("common_meshes_properties")
        self.assertTrue(mesh.get_editor_property("collision"))
        self.assertTrue(mesh.get_editor_property("import_collision_according_to_mesh_name"))
        self.assertEqual(mesh.get_editor_property("fallback_collision_type"), fake_unreal.InterchangeMeshCollision.NONE)
        self.assertEqual(mesh.get_editor_property("combine_static_meshes_behavior"),
                         fake_unreal.InterchangeCombineStaticMeshesBehavior.ALL)
        self.assertEqual(common.get_editor_property("force_all_mesh_as_type"),
                         fake_unreal.InterchangeForceMeshType.IFMT_STATIC_MESH)
        self.assertTrue(common.get_editor_property("import_sockets"))
        self.assertFalse(common.get_editor_property("recompute_normals"))

    def test_fallback_collision_only_for_meshes_without_helpers(self):
        options = {"auto_generate_collision": True}
        helpers = self.core.build_pipeline(static_asset(), options, self.core.Adapter58())
        plain = self.core.build_pipeline(static_asset(collisions=[]), options, self.core.Adapter58())
        off = self.core.build_pipeline(static_asset(collisions=[]), {}, self.core.Adapter58())
        fallback = lambda p: p.get_editor_property("mesh_pipeline").get_editor_property("fallback_collision_type")
        self.assertEqual(fallback(helpers), fake_unreal.InterchangeMeshCollision.NONE)
        self.assertEqual(fallback(plain), fake_unreal.InterchangeMeshCollision.CONVEX18DOP)
        self.assertEqual(fallback(off), fake_unreal.InterchangeMeshCollision.NONE)

    def test_collision_matching_rules(self):
        match = self.core.collisions_match
        none = {"box": 0, "sphere": 0, "capsule": 0, "convex": 0}
        one = dict(none, convex=1)
        three = dict(none, convex=3)
        self.assertTrue(match(one, static_asset(), {"one_convex_hull_per_ucx": True}))
        self.assertFalse(match(three, static_asset(), {"one_convex_hull_per_ucx": True}))
        self.assertTrue(match(three, static_asset(), {"one_convex_hull_per_ucx": False}))
        self.assertTrue(match(one, static_asset(collisions=[]), {"auto_generate_collision": True}))
        self.assertFalse(match(none, static_asset(collisions=[]), {"auto_generate_collision": True}))
        self.assertTrue(match(none, static_asset(collisions=[]), {}))

    def test_56_adapter_rejected_by_58_engine(self):
        with self.assertRaises(self.core.BridgeImportError):
            self.core.build_pipeline(static_asset(), {}, self.core.Adapter56())

    def test_animation_pipeline_requires_skeleton(self):
        anim = {"kind": "ANIMATION", "asset_name": "A_Run", "animation": {"fps": 30}}
        with self.assertRaises(self.core.BridgeImportError):
            self.core.build_pipeline(anim, {}, self.core.Adapter58())
        skeleton = fake_unreal.Skeleton("/Game/SK_Hero_Skeleton")
        pipeline = self.core.build_pipeline(anim, {}, self.core.Adapter58(), skeleton)
        anim_pipe = pipeline.get_editor_property("animation_pipeline")
        self.assertEqual(anim_pipe.get_editor_property("custom_bone_animation_sample_rate"), 30)
        self.assertEqual(anim_pipe.get_editor_property("frame_alignment"),
                         fake_unreal.InterchangeFrameAlignment.SNAP_TO_CLOSEST)


def lod_asset_with_variant():
    return static_asset(lods=[{"index": 1, "object": "SM_Crate_LOD1", "generated": True}],
                        file_variants={"5.6": {"file": "SM_Crate.ue56.fbx", "file_sha256": ""}})


class VariantSelectionTests(ImporterTestBase):
    def test_58_uses_main_file(self):
        self.assertEqual(self.core.select_file(lod_asset_with_variant(), self.core.Adapter58()),
                         ("SM_Crate.fbx", ""))

    def test_56_uses_variant(self):
        self.assertEqual(self.core.select_file(lod_asset_with_variant(), self.core.Adapter56()),
                         ("SM_Crate.ue56.fbx", ""))

    def test_run_imports_the_variant_on_56(self):
        fake_unreal.reset("5.6")
        self.touch("SM_Crate.ue56.fbx")  # only the variant exists: the main file must not be read
        fake_unreal.SCENARIOS["SM_Crate.ue56.fbx"] = {"collisions": {"convex_elems": 1}, "lods": 2}
        entry = self.result(self.core.run(write_manifest(self.export_dir, [lod_asset_with_variant()])),
                            "uuid-SM_Crate")
        self.assertEqual(entry["status"], "created", entry)
        self.assertTrue(entry["checks"]["lods_ok"])
        self.assertIn("using engine-specific file SM_Crate.ue56.fbx", entry["messages"])
        task = fake_unreal.IMPORT_CALLS[0]
        self.assertTrue(task.get_editor_property("filename").endswith("SM_Crate.ue56.fbx"))


class Adapter56Tests(ImporterTestBase):
    version = "5.6"

    def test_56_spellings(self):
        pipeline = self.core.build_pipeline(static_asset(), {}, self.core.Adapter56())
        self.assertTrue(pipeline.get_editor_property("mesh_pipeline").get_editor_property("combine_static_meshes"))
        with self.assertRaises(self.core.BridgeImportError):
            self.core.build_pipeline(static_asset(), {}, self.core.Adapter58())

    def test_run_selects_56_adapter(self):
        self.touch("SM_Crate.fbx")
        path = write_manifest(self.export_dir, [static_asset()])
        receipt = self.core.run(path)
        self.assertEqual(receipt["adapter"], "5.6")
        self.assertEqual(self.result(receipt, "uuid-SM_Crate")["status"], "created")


class RunTests(ImporterTestBase):
    def test_static_import_reconciles_sockets_and_writes_receipt(self):
        self.touch("SM_Crate.fbx")
        fake_unreal.SCENARIOS["SM_Crate.fbx"] = {"collisions": {"convex_elems": 1}}
        path = write_manifest(self.export_dir, [static_asset()])
        receipt = self.core.run(path)
        entry = self.result(receipt, "uuid-SM_Crate")
        self.assertEqual(entry["status"], "created")
        self.assertEqual(entry["checks"]["sockets_added"], 1)
        self.assertTrue(entry["checks"]["collisions_ok"])
        self.assertTrue(entry["checks"]["lods_ok"])
        self.assertEqual(entry["unreal_path"], "/Game/Exports/SM_Crate")
        with open(os.path.join(self.export_dir, C.RECEIPT_FILENAME), encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["plan_id"], "plan123")
        self.assertEqual(fake_unreal.METADATA[("/game/exports/sm_crate", self.core.META_SOURCE_ID)], "uuid-SM_Crate")
        task = fake_unreal.IMPORT_CALLS[0]
        self.assertTrue(task.get_editor_property("automated"))
        self.assertFalse(task.get_editor_property("async_"))
        self.assertEqual(task.get_editor_property("destination_name"), "SM_Crate")

    def test_reimport_reports_updated_and_keeps_sockets(self):
        self.touch("SM_Crate.fbx")
        fake_unreal.SCENARIOS["SM_Crate.fbx"] = {"collisions": {"convex_elems": 1},
                                                 "sockets": [{"name": "Lid", "loc": (0, 0, 50), "rot": (0, 0, -90)}]}
        path = write_manifest(self.export_dir, [static_asset()])
        self.core.run(path)
        receipt = self.core.run(path)
        entry = self.result(receipt, "uuid-SM_Crate")
        self.assertEqual(entry["status"], "updated")
        self.assertEqual(entry["checks"]["sockets_ok"], 1)

    def test_drifted_socket_is_corrected(self):
        self.touch("SM_Crate.fbx")
        fake_unreal.SCENARIOS["SM_Crate.fbx"] = {"collisions": {"convex_elems": 1},
                                                 "sockets": [{"name": "Lid", "loc": (0, 0, 50), "rot": (-90, 0, -90)}]}
        receipt = self.core.run(write_manifest(self.export_dir, [static_asset()]))
        self.assertEqual(self.result(receipt, "uuid-SM_Crate")["checks"]["sockets_corrected"], 1)

    def test_collision_and_lod_mismatch_are_reported(self):
        self.touch("SM_Crate.fbx")
        fake_unreal.SCENARIOS["SM_Crate.fbx"] = {"collisions": {}, "lods": 1}
        asset = static_asset(lods=[{"index": 1, "object": "SM_Crate_LOD1", "generated": True}])
        entry = self.result(self.core.run(write_manifest(self.export_dir, [asset])), "uuid-SM_Crate")
        self.assertEqual(entry["status"], "created")
        self.assertFalse(entry["checks"]["collisions_ok"])
        self.assertFalse(entry["checks"]["lods_ok"])
        self.assertTrue(any("LOD count" in m for m in entry["messages"]))

    def test_checksum_mismatch_fails_asset(self):
        self.touch("SM_Crate.fbx", b"changed")
        asset = static_asset(file_sha256="00" * 32)
        entry = self.result(self.core.run(write_manifest(self.export_dir, [asset])), "uuid-SM_Crate")
        self.assertEqual(entry["status"], "failed")
        self.assertIn("checksum", entry["messages"][0])

    def test_missing_file_and_traversal(self):
        assets = [static_asset(), static_asset(name="SM_Evil", file="../evil.fbx")]
        receipt = self.core.run(write_manifest(self.export_dir, assets))
        self.assertEqual(self.result(receipt, "uuid-SM_Crate")["status"], "failed")
        self.assertIn("missing", self.result(receipt, "uuid-SM_Crate")["messages"][0])
        self.assertIn("outside", self.result(receipt, "uuid-SM_Evil")["messages"][0])

    def test_unsupported_manifest_version(self):
        receipt = self.core.run(write_manifest(self.export_dir, [static_asset()], version=99))
        self.assertTrue(receipt["errors"])
        self.assertEqual(receipt["results"], [])

    def test_unsupported_engine(self):
        fake_unreal.reset("5.5")
        self.touch("SM_Crate.fbx")
        receipt = self.core.run(write_manifest(self.export_dir, [static_asset()]))
        self.assertIn("not supported", receipt["errors"][0])

    def test_skeletal_then_animation_uses_skeleton(self):
        self.touch("SK_Hero.fbx")
        self.touch("A_Run.fbx")
        fake_unreal.SCENARIOS["A_Run.fbx"] = {"length": 23 / 24}
        sk = {"id": "uuid-hero", "kind": "SKELETAL_MESH", "asset_name": "SK_Hero", "unreal_path": "/Game/C/SK_Hero",
              "destination_path": "/Game/C", "file": "SK_Hero.fbx", "status": "written",
              "skeleton": {"armature": "Hero", "unreal_skeleton_path": "/Game/C/SK_Hero_Skeleton",
                           "skeleton_asset_id": ""}}
        anim = {"id": "uuid-hero+run", "kind": "ANIMATION", "asset_name": "A_Run", "unreal_path": "/Game/C/A_Run",
                "destination_path": "/Game/C", "file": "A_Run.fbx", "status": "written",
                "skeleton": {"armature": "Hero", "unreal_skeleton_path": "/Game/C/SK_Hero_Skeleton",
                             "skeleton_asset_id": "uuid-hero"},
                "animation": {"fps": 24, "root_motion": "ROOT_BONE", "expected_length_seconds": 23 / 24}}
        receipt = self.core.run(write_manifest(self.export_dir, [sk, anim]))
        self.assertEqual(self.result(receipt, "uuid-hero")["status"], "created")
        anim_entry = self.result(receipt, "uuid-hero+run")
        self.assertEqual(anim_entry["status"], "created", anim_entry)
        self.assertTrue(anim_entry["checks"]["enable_root_motion"])
        self.assertTrue(anim_entry["checks"]["length_ok"])

    def test_animation_without_skeleton_fails(self):
        self.touch("A_Run.fbx")
        anim = {"id": "a", "kind": "ANIMATION", "asset_name": "A_Run", "unreal_path": "/Game/C/A_Run",
                "destination_path": "/Game/C", "file": "A_Run.fbx", "status": "written",
                "skeleton": {"unreal_skeleton_path": "/Game/C/Missing_Skeleton"}, "animation": {"fps": 24}}
        entry = self.result(self.core.run(write_manifest(self.export_dir, [anim])), "a")
        self.assertEqual(entry["status"], "failed")
        self.assertIn("Skeleton", entry["messages"][0])

    def _rename_setup(self, policy):
        self.touch("SM_Crate.fbx")
        self.touch("SM_Box.fbx")
        fake_unreal.SCENARIOS["SM_Crate.fbx"] = {"collisions": {"convex_elems": 1}}
        fake_unreal.SCENARIOS["SM_Box.fbx"] = {"collisions": {"convex_elems": 1}}
        options = {"one_convex_hull_per_ucx": True, "reimport_policy": policy}
        self.core.run(write_manifest(self.export_dir, [static_asset()], options))
        renamed = static_asset(name="SM_Box", file="SM_Box.fbx")
        renamed["id"] = "uuid-SM_Crate"  # same Blender source, new name
        return self.core.run(write_manifest(self.export_dir, [renamed], options))

    def test_reimport_after_blender_rename_updates_existing(self):
        receipt = self._rename_setup("UPDATE_EXISTING")
        entry = self.result(receipt, "uuid-SM_Crate")
        self.assertEqual(entry["status"], "updated")
        self.assertEqual(entry["unreal_path"], "/Game/Exports/SM_Crate")
        self.assertNotIn("/game/exports/sm_box", fake_unreal.ASSETS)

    def test_reimport_after_blender_rename_follows_rename(self):
        receipt = self._rename_setup("FOLLOW_RENAME")
        entry = self.result(receipt, "uuid-SM_Crate")
        self.assertEqual(entry["unreal_path"], "/Game/Exports/SM_Box")
        self.assertNotIn("/game/exports/sm_crate", fake_unreal.ASSETS)
        self.assertEqual(entry["status"], "updated")

    def test_failed_import_reports_and_continues(self):
        self.touch("SM_Crate.fbx")
        self.touch("SM_Other.fbx")
        fake_unreal.SCENARIOS["SM_Crate.fbx"] = {"fail": True}
        fake_unreal.SCENARIOS["SM_Other.fbx"] = {"collisions": {"convex_elems": 1}}
        receipt = self.core.run(write_manifest(self.export_dir, [static_asset(),
                                                                 static_asset(name="SM_Other", file="SM_Other.fbx")]))
        self.assertEqual(self.result(receipt, "uuid-SM_Crate")["status"], "failed")
        self.assertEqual(self.result(receipt, "uuid-SM_Other")["status"], "created")


class GeneratedScriptTests(ImporterTestBase):
    def test_generated_script_runs_end_to_end(self):
        self.touch("SM_Crate.fbx")
        fake_unreal.SCENARIOS["SM_Crate.fbx"] = {"collisions": {"convex_elems": 1}}
        write_manifest(self.export_dir, [static_asset()])
        script_path = os.path.join(self.export_dir, C.IMPORT_SCRIPT_FILENAME)
        unreal_script.write_import_script(script_path, "plan123")
        with open(script_path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn(self.tmp, text)  # no absolute paths embedded
        namespace = {"__file__": script_path, "__name__": "__main__"}
        exec(compile(text, script_path, "exec"), namespace)
        receipt = namespace["bridge_receipt"]
        self.assertEqual(self.result(receipt, "uuid-SM_Crate")["status"], "created")

    def test_plugin_copy_is_in_sync(self):
        plugin_copy = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                   "unreal", "BlenderBridge", "Content", "Python", "blender_bridge", "importer.py")
        if not os.path.exists(plugin_copy):
            self.skipTest("Unreal plugin not generated yet")
        with open(plugin_copy, encoding="utf-8") as a, open(CORE_PATH, encoding="utf-8") as b:
            self.assertEqual(a.read(), b.read(), "run scripts/sync_unreal_plugin.py")


if __name__ == "__main__":
    unittest.main()
