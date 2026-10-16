import json
import os
import shutil
import tempfile
import unittest
from dataclasses import replace

from tests.unit import factories as F
from unreal_exporter import constants as C
from unreal_exporter.domain import discovery, planning
from unreal_exporter.domain.models import AssetResult
from unreal_exporter.services import manifest as M


def plan_for(snap, **kw):
    settings = F.settings(**kw)
    result = discovery.discover(snap, settings)
    return planning.build_plan(snap, result.assets, settings)


def scene():
    return F.snapshot(
        F.selected(F.mesh("Crate")), F.mesh("UCX_Crate_00"), F.empty("SOCKET_Crate_Lid"),
        F.selected(F.armature("Hero")), F.skinned("Hero_Body", "Hero"),
        actions=(F.action("Run"),),
    )


class PlanTests(unittest.TestCase):
    def test_plan_is_deterministic(self):
        a = plan_for(scene(), profile=C.PROFILE_COLLECTION_SCENE)
        b = plan_for(scene(), profile=C.PROFILE_COLLECTION_SCENE)
        self.assertEqual(a.plan_id, b.plan_id)
        self.assertEqual(a, b)

    def test_plan_id_ignores_machine_paths(self):
        a = plan_for(scene(), export_root="/a")
        b = plan_for(scene(), export_root="/b")
        self.assertEqual(a.plan_id, b.plan_id)

    def test_plan_id_changes_with_content(self):
        a = plan_for(scene())
        b = plan_for(scene(), unreal_root="/Game/Other")
        c = plan_for(F.snapshot(F.selected(F.mesh("Crate")), F.mesh("UCX_Crate_00")))
        self.assertNotEqual(a.plan_id, b.plan_id)
        self.assertNotEqual(a.plan_id, c.plan_id)

    def test_import_order_puts_skeletal_before_animation(self):
        plan = plan_for(scene(), profile=C.PROFILE_SKELETAL_MESH, skeletal_include_animations=True, actions=("Run",))
        self.assertEqual([a.kind for a in plan.assets], [C.KIND_SKELETAL_MESH, C.KIND_ANIMATION])
        self.assertEqual([f.relpath for f in plan.files], ["SK_Hero.fbx", "A_Run.fbx"])

    def test_fbx_options_per_kind(self):
        settings = F.settings(sample_step=2.0, export_tangents=True)
        static = planning.fbx_export_options(C.KIND_STATIC_MESH, settings)
        anim = planning.fbx_export_options(C.KIND_ANIMATION, settings)
        self.assertEqual(static["object_types"], {"MESH", "EMPTY"})
        self.assertFalse(static["bake_anim"])
        self.assertTrue(static["use_tspace"])
        self.assertEqual(static["apply_scale_options"], "FBX_SCALE_NONE")
        self.assertFalse(static["add_leaf_bones"])
        self.assertEqual(anim["object_types"], {"ARMATURE"})
        self.assertTrue(anim["bake_anim"])
        self.assertFalse(anim["bake_anim_use_all_actions"])
        self.assertFalse(anim["bake_anim_use_nla_strips"])
        self.assertEqual(anim["bake_anim_step"], 2.0)

    def test_cm_per_unit(self):
        self.assertEqual(planning.cm_per_unit(1.0), 100.0)
        self.assertEqual(planning.cm_per_unit(0.01), 1.0)
        self.assertEqual(planning.cm_per_unit(0.0), 100.0)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="uex_manifest_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _manifest(self):
        plan = plan_for(scene(), profile=C.PROFILE_COLLECTION_SCENE)
        results = {a.id: AssetResult(asset_id=a.id, asset_name=a.asset_name, kind=a.kind, unreal_path=a.unreal_path,
                                     relpath=a.file_relpath, status="written", file_sha256="ab" * 32,
                                     source_hash="cd" * 32) for a in plan.assets}
        extras = {plan.assets[0].id: {"material_slots": ["M_Wood"], "triangles": 12}}
        return M.build_manifest(plan, results, extras, created_at="2026-01-01T00:00:00Z"), plan

    def test_round_trip(self):
        manifest, plan = self._manifest()
        path = os.path.join(self.tmp, C.MANIFEST_FILENAME)
        M.write_manifest(path, manifest)
        loaded = M.load_manifest(path)
        self.assertEqual(loaded, json.loads(M.dumps(manifest)))
        self.assertEqual(loaded["plan_id"], plan.plan_id)
        self.assertEqual(loaded["schema_version"], C.MANIFEST_SCHEMA_VERSION)
        kinds = sorted(a["kind"] for a in loaded["assets"])
        self.assertEqual(kinds, [C.KIND_SKELETAL_MESH, C.KIND_STATIC_MESH])
        static = [a for a in loaded["assets"] if a["kind"] == C.KIND_STATIC_MESH][0]
        self.assertEqual(static["destination_path"], "/Game/BlenderExports")
        self.assertEqual(static["collisions"][0]["object"], "UCX_Crate_00")
        self.assertEqual(static["status"], "written")

    def test_serialization_is_stable(self):
        first, _ = self._manifest()
        second, _ = self._manifest()
        self.assertEqual(M.dumps(first), M.dumps(second))

    def test_semantic_view_drops_run_specific_fields(self):
        a, _ = self._manifest()
        b = json.loads(M.dumps(a))
        b["created_at"] = "2030-01-01T00:00:00Z"
        b["assets"][0]["file_sha256"] = "ff" * 32
        self.assertEqual(M.semantic_view(a), M.semantic_view(b))

    def test_rejects_future_and_foreign_documents(self):
        manifest, _ = self._manifest()
        future = dict(manifest, schema_version=C.MANIFEST_SCHEMA_VERSION + 1)
        with self.assertRaises(M.ManifestError):
            M.loads(json.dumps(future))
        with self.assertRaises(M.ManifestError):
            M.loads(json.dumps(dict(manifest, schema="something/else")))
        with self.assertRaises(M.ManifestError):
            M.loads("{not json")
        broken = dict(manifest, schema_version="1")
        with self.assertRaises(M.ManifestError):
            M.loads(json.dumps(broken))

    def test_migration_chain(self):
        manifest, _ = self._manifest()
        old = dict(manifest, schema_version=0)
        old.pop("import_options")
        old["options"] = manifest["import_options"]

        def v0_to_v1(data):
            data["import_options"] = data.pop("options")
            data["schema_version"] = 1
            return data

        M.MIGRATIONS[0] = v0_to_v1
        try:
            migrated = M.loads(json.dumps(old))
        finally:
            del M.MIGRATIONS[0]
        self.assertEqual(migrated["import_options"], manifest["import_options"])
        with self.assertRaises(M.ManifestError):
            M.loads(json.dumps(old))  # no migration registered any more

    def test_validation_rejects_escaping_paths_and_duplicates(self):
        manifest, _ = self._manifest()
        escaped = json.loads(M.dumps(manifest))
        escaped["assets"][0]["file"] = "../evil.fbx"
        with self.assertRaises(M.ManifestError):
            M.validate_manifest(escaped)
        dup = json.loads(M.dumps(manifest))
        dup["assets"][1]["unreal_path"] = dup["assets"][0]["unreal_path"].upper()
        with self.assertRaises(M.ManifestError):
            M.validate_manifest(dup)
        variant = json.loads(M.dumps(manifest))
        variant["assets"][0]["file_variants"] = {"5.6": {"file": "C:/evil.fbx"}}
        with self.assertRaises(M.ManifestError):
            M.validate_manifest(variant)

    def test_atomic_write_leaves_no_temp_files(self):
        manifest, _ = self._manifest()
        path = os.path.join(self.tmp, "sub", C.MANIFEST_FILENAME)
        M.write_manifest(path, manifest)
        self.assertEqual(os.listdir(os.path.dirname(path)), [C.MANIFEST_FILENAME])

    def test_sha256_file(self):
        path = os.path.join(self.tmp, "x.bin")
        with open(path, "wb") as handle:
            handle.write(b"abc")
        self.assertEqual(M.sha256_file(path), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main()
