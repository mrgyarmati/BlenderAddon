import unittest
from dataclasses import replace

from tests.unit import factories as F
from unreal_exporter import constants as C
from unreal_exporter.domain import discovery, validation
from unreal_exporter.domain.models import BoneRecord, ModifierRecord


def run(snap, **settings_kw):
    settings = F.settings(**settings_kw)
    result = discovery.discover(snap, settings)
    return validation.validate(snap, result, settings)


def codes(issues):
    return sorted({i.code for i in issues})


class GlobalRuleTests(unittest.TestCase):
    def test_clean_asset_has_no_blocking_issues(self):
        issues = run(F.snapshot(F.selected(F.mesh("Crate"))))
        self.assertFalse(validation.has_blocking(issues), [i.message for i in issues])

    def test_duplicate_unreal_paths_case_insensitive(self):
        snap = F.snapshot(F.selected(F.mesh("Crate")), F.selected(F.mesh("crate")))
        issues = run(snap, auto_prefix=False)
        dupes = [i for i in issues if i.code == "E_DUPLICATE_UNREAL_PATH"]
        self.assertEqual(len(dupes), 2)

    def test_bad_unreal_root(self):
        self.assertIn("E_UNREAL_ROOT", codes(run(F.snapshot(F.selected(F.mesh("A"))), unreal_root="/Engine/X")))

    def test_export_root_missing_unwritable_and_not_permitted(self):
        snap = F.snapshot(F.selected(F.mesh("A")))
        self.assertIn("E_EXPORT_ROOT_MISSING", codes(run(snap, export_root="")))
        self.assertIn("E_OUTPUT_OUTSIDE_ROOT",
                      codes(run(snap, export_root="/tmp/out", permitted_roots=("/srv/allowed",))))
        settings = F.settings()
        result = discovery.discover(snap, settings)
        env = validation.ValidationEnv(export_root_writable=False, export_root_reason="read-only")
        self.assertIn("E_PATH_UNWRITABLE", codes(validation.validate(snap, result, settings, env)))

    def test_materials_requested_warning(self):
        self.assertIn("W_MATERIALS_REQUESTED", codes(run(F.snapshot(F.selected(F.mesh("A"))), import_materials=True)))

    def test_duplicate_uuid_warning_has_fix(self):
        snap = F.snapshot(F.selected(F.mesh("A", uuid="same")), F.mesh("B", uuid="same"))
        issue = [i for i in run(snap) if i.code == "W_DUPLICATE_UUID"][0]
        self.assertEqual(issue.fix_id, validation.FIX_REPAIR_UUIDS)

    def test_developer_override(self):
        issues = run(F.snapshot(F.selected(F.mesh("UCX_Ghost_00"))))
        self.assertFalse(validation.can_export(issues, F.settings()))
        self.assertTrue(validation.can_export(issues, F.settings(developer_mode=True)))

    def test_issue_ordering_is_stable(self):
        snap = F.snapshot(F.selected(F.mesh("A", mesh=F.stats(uv_layers=(), ngon_count=3))))
        first = run(snap)
        second = run(snap)
        self.assertEqual(first, second)
        severities = [i.severity for i in first]
        self.assertEqual(severities, sorted(severities, key=lambda s: {"ERROR": 0, "WARNING": 1, "INFO": 2}[s]))


class GeometryRuleTests(unittest.TestCase):
    def test_geometry_warnings(self):
        bad = F.stats(non_manifold_edge_count=4, degenerate_face_count=2, uv_layers=(), ngon_count=3,
                      material_slots=("A", "", "C"))
        issues = run(F.snapshot(F.selected(F.mesh("Rock", mesh=bad))))
        self.assertTrue({"W_NON_MANIFOLD", "W_DEGENERATE_FACES", "W_MISSING_UV0", "W_NGONS",
                         "W_EMPTY_MATERIAL_SLOT"} <= set(codes(issues)))

    def test_lightmap_overlap(self):
        stats = F.stats(uv_layers=("UVMap", "Lightmap"), uv1_area_sum=1.4)
        self.assertIn("W_LIGHTMAP_UV_OVERLAP", codes(run(F.snapshot(F.selected(F.mesh("A", mesh=stats))))))

    def test_too_many_material_slots(self):
        stats = F.stats(material_slots=tuple("M%d" % i for i in range(10)))
        self.assertIn("W_MATERIAL_SLOTS", codes(run(F.snapshot(F.selected(F.mesh("A", mesh=stats))))))

    def test_missing_geometry_is_blocking(self):
        issues = run(F.snapshot(F.selected(F.mesh("A", mesh=F.stats(polygon_count=0)))))
        self.assertIn("E_MISSING_DATA", codes(issues))

    def test_transform_warnings(self):
        ob = F.mesh("A", rotation_quaternion=(0.707, 0.707, 0.0, 0.0), scale=(-1.0, 2.0, 1.0))
        issues = codes(run(F.snapshot(F.selected(ob))))
        self.assertTrue({"W_UNAPPLIED_TRANSFORM", "W_NEGATIVE_SCALE", "W_NON_UNIFORM_SCALE"} <= set(issues))


class CollisionRuleTests(unittest.TestCase):
    def test_collision_name_mismatch_is_blocking(self):
        root = F.mesh("SM_Box")
        snap = F.snapshot(F.selected(root),
                          F.mesh("Hull", role=C.ROLE_COLLISION, owner_uuid=root.uuid, collision_shape=C.SHAPE_CONVEX))
        issue = [i for i in run(snap) if i.code == "E_COLLISION_NAME_MISMATCH"][0]
        self.assertEqual(issue.fix_id, validation.FIX_RENAME_HELPERS)
        self.assertTrue(issue.is_blocking)

    def test_primitive_and_convexity_checks(self):
        snap = F.snapshot(
            F.selected(F.mesh("SM_A")),
            F.mesh("UBX_SM_A_00", mesh=F.stats(box_fit_error=0.2)),
            F.mesh("USP_SM_A_01", mesh=F.stats(sphere_fit_error=0.3), scale=(1.0, 2.0, 1.0)),
            F.mesh("UCX_SM_A_02", mesh=F.stats(is_convex=False, non_manifold_edge_count=3)),
        )
        found = codes(run(snap))
        self.assertTrue({"W_PRIMITIVE_DEFORMED", "W_PRIMITIVE_SCALE", "W_UCX_NOT_CONVEX", "W_UCX_OPEN"} <= set(found))

    def test_collision_without_polygons(self):
        snap = F.snapshot(F.selected(F.mesh("SM_A")), F.mesh("UCX_SM_A_00", mesh=F.stats(polygon_count=0)))
        self.assertIn("E_MISSING_DATA", codes(run(snap)))


class SocketRuleTests(unittest.TestCase):
    def test_duplicate_socket_names(self):
        root = F.mesh("SM_A")
        snap = F.snapshot(
            F.selected(root),
            F.empty("SOCKET_SM_A_Grip"),
            F.empty("Other", role=C.ROLE_SOCKET, owner_uuid=root.uuid, socket_name="grip"),
        )
        self.assertIn("E_DUPLICATE_SOCKET", codes(run(snap)))

    def test_far_socket(self):
        snap = F.snapshot(F.selected(F.mesh("SM_A")), F.empty("SOCKET_SM_A_Far", location=(10.0, 0.0, 0.0)))
        self.assertIn("W_SOCKET_FAR", codes(run(snap)))
        near = F.snapshot(F.selected(F.mesh("SM_A")), F.empty("SOCKET_SM_A_Near", location=(0.6, 0.0, 0.0)))
        self.assertNotIn("W_SOCKET_FAR", codes(run(near)))


class LodRuleTests(unittest.TestCase):
    def test_lod_triangles_must_decrease(self):
        snap = F.snapshot(
            F.selected(F.mesh("SM_A", mesh=F.stats(triangle_count=100))),
            F.mesh("SM_A_LOD1", mesh=F.stats(triangle_count=120)),
        )
        self.assertIn("W_LOD_TRIS_NOT_DECREASING", codes(run(snap)))

    def test_duplicate_lod_indices(self):
        root = F.mesh("SM_A")
        snap = F.snapshot(
            F.selected(root),
            F.mesh("SM_A_LOD1"),
            F.mesh("Extra", role=C.ROLE_LOD, owner_uuid=root.uuid, lod_index=1),
        )
        found = codes(run(snap))
        self.assertIn("E_LOD_DUPLICATE_INDEX", found)
        self.assertIn("W_LOD_NAME_MISMATCH", found)

    def test_lod_gap(self):
        snap = F.snapshot(F.selected(F.mesh("SM_A")), F.mesh("SM_A_LOD2", mesh=F.stats(triangle_count=4)))
        self.assertIn("W_LOD_GAP", codes(run(snap)))

    def test_lod_offset(self):
        snap = F.snapshot(F.selected(F.mesh("SM_A")),
                          F.mesh("SM_A_LOD1", location=(3.0, 0.0, 0.0), mesh=F.stats(triangle_count=6)))
        self.assertIn("W_LOD_OFFSET", codes(run(snap)))


class SkeletalRuleTests(unittest.TestCase):
    def _snap(self, arm=None, body=None, actions=()):
        arm = arm or F.armature("Hero")
        body = body or F.skinned("Body", "Hero")
        return F.snapshot(F.selected(arm), body, actions=actions)

    def test_clean_rig(self):
        issues = run(self._snap(), profile=C.PROFILE_SKELETAL_MESH)
        self.assertFalse(validation.has_blocking(issues), [i.message for i in issues])

    def test_duplicate_bones_case_insensitive(self):
        bones = (BoneRecord("root"), BoneRecord("Spine", "root"), BoneRecord("spine", "root"))
        issues = run(self._snap(arm=replace(F.armature("Hero"), bones=bones)), profile=C.PROFILE_SKELETAL_MESH)
        self.assertIn("E_DUPLICATE_BONES", codes(issues))

    def test_multiple_root_bones(self):
        bones = (BoneRecord("root"), BoneRecord("ik_target"))
        issues = run(self._snap(arm=replace(F.armature("Hero"), bones=bones)), profile=C.PROFILE_SKELETAL_MESH)
        self.assertIn("E_MULTIPLE_ROOT_BONES", codes(issues))

    def test_non_deform_roots_are_ignored_with_deform_only(self):
        bones = (BoneRecord("root"), BoneRecord("spine", "root"), BoneRecord("ctrl", "", use_deform=False))
        issues = run(self._snap(arm=replace(F.armature("Hero"), bones=bones)), profile=C.PROFILE_SKELETAL_MESH)
        self.assertNotIn("E_MULTIPLE_ROOT_BONES", codes(issues))

    def test_unweighted_and_influences(self):
        body = F.skinned("Body", "Hero", mesh=F.stats(unweighted_vertex_count=5, max_bone_influences=12,
                                                       vertex_groups=("root",)))
        found = codes(run(self._snap(body=body), profile=C.PROFILE_SKELETAL_MESH))
        self.assertIn("E_UNWEIGHTED_VERTICES", found)
        self.assertIn("W_BONE_INFLUENCES", found)

    def test_shape_key_policies(self):
        mods = (ModifierRecord("Armature", "ARMATURE", target="Hero"), ModifierRecord("Subsurf", "SUBSURF"))
        body = F.skinned("Body", "Hero", modifiers=mods, mesh=F.stats(shape_keys=("Smile",)))
        self.assertIn("W_MORPH_WITH_MODIFIERS", codes(run(self._snap(body=body), profile=C.PROFILE_SKELETAL_MESH)))
        self.assertIn("W_SHAPE_KEYS_DISABLED", codes(run(self._snap(body=body), profile=C.PROFILE_SKELETAL_MESH,
                                                         export_morph_targets=False)))

    def test_bone_named_like_staged_armature(self):
        bones = (BoneRecord("Armature"), BoneRecord("spine", "Armature"))
        issues = run(self._snap(arm=replace(F.armature("Hero"), bones=bones)), profile=C.PROFILE_SKELETAL_MESH)
        self.assertIn("E_DUPLICATE_BONES", codes(issues))

    def test_lod_skeleton_mismatch(self):
        snap = F.snapshot(
            F.selected(F.armature("Hero")), F.armature("Other"),
            F.skinned("Body", "Hero"),
            F.skinned("Body_LOD1", "Other", mesh=F.stats(triangle_count=2, vertex_groups=("root",))),
        )
        self.assertIn("E_LOD_SKELETON_MISMATCH", codes(run(snap, profile=C.PROFILE_SKELETAL_MESH)))


class AnimationRuleTests(unittest.TestCase):
    def test_reversed_range_and_object_animation(self):
        snap = F.snapshot(F.selected(F.armature("Hero", active_action="Run", is_animated=True)),
                          actions=(F.action("Run", start=10, end=2),))
        found = codes(run(snap, profile=C.PROFILE_ANIMATION))
        self.assertIn("E_FRAME_RANGE", found)
        self.assertIn("W_ARMATURE_OBJECT_ANIMATED", found)

    def test_object_to_root_policy_silences_object_animation(self):
        snap = F.snapshot(F.selected(F.armature("Hero", active_action="Run", is_animated=True)),
                          actions=(F.action("Run"),))
        found = codes(run(snap, profile=C.PROFILE_ANIMATION, root_motion=C.ROOT_MOTION_OBJECT_TO_ROOT))
        self.assertNotIn("W_ARMATURE_OBJECT_ANIMATED", found)

    def test_bad_skeleton_override(self):
        snap = F.snapshot(F.selected(F.armature("Hero", active_action="Run", skeleton_path_override="not a path")),
                          actions=(F.action("Run"),))
        self.assertIn("E_ANIM_NO_SKELETON", codes(run(snap, profile=C.PROFILE_ANIMATION)))

    def test_sample_step(self):
        snap = F.snapshot(F.selected(F.armature("Hero", active_action="Run")), actions=(F.action("Run"),))
        self.assertIn("E_SAMPLE_STEP", codes(run(snap, profile=C.PROFILE_ANIMATION, sample_step=0.0)))


if __name__ == "__main__":
    unittest.main()
