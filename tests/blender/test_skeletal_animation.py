"""Skeletal mesh and animation export, verified by re-importing the FBX into Blender."""

import json
import os
import unittest

import bpy

from tests.blender import fixtures, harness
from tests.blender.fbx_inspect import FbxFile
from tests.blender.test_static_export import data_counts, leftover_names


class SkeletalTestBase(unittest.TestCase):
    def setUp(self):
        harness.fresh_file()
        self._tmp = harness.TempDir()
        self.out = self._tmp.__enter__()
        self.settings = harness.export_dir_settings(self.out)
        self.cs = harness.submodule("services.context_guard")

    def tearDown(self):
        self._tmp.__exit__(None, None, None)

    def manifest(self):
        with open(os.path.join(self.out, "unreal_export_manifest.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def reimport(self, filename):
        """Import an exported FBX into an empty file; return the imported armature."""
        bpy.ops.wm.read_homefile(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=os.path.join(self.out, filename))
        arms = [ob for ob in bpy.context.scene.objects if ob.type == "ARMATURE"]
        self.assertEqual(len(arms), 1)
        return arms[0]

    def head_at(self, arm, bone, frame):
        bpy.context.scene.frame_set(frame)
        return arm.matrix_world @ arm.pose.bones[bone].head


class SkeletalMeshTests(SkeletalTestBase):
    def test_skeletal_mesh_structure_and_scale(self):
        arm, meshes, _action = fixtures.rig("Hero")
        decoy = fixtures.link(bpy.data.objects.new("Armature", None))  # name the staged rig needs
        harness.select_only(arm)
        self.settings.profile = "SKELETAL_MESH"
        before = self.cs.ContextState(bpy.context)
        counts = data_counts()
        self.assertEqual(bpy.ops.uex.export(destination="DISK"), {"FINISHED"})
        self.assertEqual(before.diff(self.cs.ContextState(bpy.context)), [])
        self.assertEqual(data_counts(), counts)
        self.assertEqual(leftover_names(), [])
        self.assertEqual(decoy.name, "Armature")

        fbx = FbxFile(os.path.join(self.out, "SK_Hero.fbx"))
        self.assertEqual(fbx.unit_scale, 1.0)
        # Blender writes skinned meshes at the scene root, bound through a Skin deformer.
        self.assertEqual(fbx.roots(), ["Armature", "Hero_Body"])
        self.assertEqual(fbx.models["root"]["type"], "LimbNode")
        self.assertEqual(fbx.models["root"]["parent"], "Armature")
        self.assertEqual(fbx.models["spine"]["parent"], "root")
        lo, hi = fbx.bounds("Hero_Body")
        self.assertAlmostEqual(lo[2], 50.0, places=3)
        self.assertAlmostEqual(hi[2], 150.0, places=3)
        asset = self.manifest()["assets"][0]
        self.assertEqual(asset["kind"], "SKELETAL_MESH")
        self.assertEqual(asset["skeleton"]["unreal_skeleton_path"], "/Game/BlenderExports/SK_Hero_Skeleton")
        self.assertEqual(asset["root_bones"], ["root"])
        self.assertEqual(asset["material_slots"], ["M_Skin"])

    def test_bind_pose_survives_round_trip(self):
        arm, _meshes, _action = fixtures.rig("Hero", location=(3.0, 0.0, 0.0))
        harness.select_only(arm)
        self.settings.profile = "SKELETAL_MESH"
        bpy.ops.uex.export(destination="DISK")
        imported = self.reimport("SK_Hero.fbx")
        bpy.context.view_layer.update()
        spine = imported.matrix_world @ imported.data.bones["spine"].head_local
        self.assertAlmostEqual(spine.z, 0.5, places=3)
        self.assertAlmostEqual(spine.x, 0.0, places=3)  # pivot at the armature origin

    def test_morph_targets(self):
        arm, _meshes, _action = fixtures.rig("Hero", shape_key=True)
        harness.select_only(arm)
        self.settings.profile = "SKELETAL_MESH"
        bpy.ops.uex.export(destination="DISK")
        asset = self.manifest()["assets"][0]
        self.assertEqual(asset["morph_targets"], ["Bulge"])
        with open(os.path.join(self.out, "SK_Hero.fbx"), "rb") as handle:
            data = handle.read()
        self.assertIn(b"BlendShape", data)
        self.assertIn(b"Bulge", data)


class AnimationTests(SkeletalTestBase):
    def export_wave(self, **overrides):
        arm, _meshes, action = fixtures.rig("Hero")
        harness.select_only(arm)
        self.settings.profile = "ANIMATION"
        ref = self.settings.actions.add()
        ref.action = action
        for key, value in overrides.items():
            setattr(self.settings, key, value)
        return arm, action

    def test_animation_file_and_manifest(self):
        arm, action = self.export_wave()
        bpy.context.scene.frame_set(4)
        before = self.cs.ContextState(bpy.context)
        counts = data_counts()
        self.assertEqual(bpy.ops.uex.export(destination="DISK"), {"FINISHED"})
        self.assertEqual(before.diff(self.cs.ContextState(bpy.context)), [])
        self.assertEqual(data_counts(), counts)
        self.assertEqual(arm.animation_data.action, action)
        fbx = FbxFile(os.path.join(self.out, "A_Hero_Wave.fbx"))
        self.assertEqual(len(fbx.anim_stacks), 1)
        self.assertFalse([n for n, m in fbx.models.items() if m["type"] == "Mesh"])
        asset = self.manifest()["assets"][0]
        anim = asset["animation"]
        self.assertEqual((anim["frame_start"], anim["frame_end"]), (1.0, 10.0))
        self.assertEqual(anim["fps"], 30.0)
        self.assertAlmostEqual(anim["expected_length_seconds"], 0.3, places=6)
        self.assertEqual(asset["skeleton"]["unreal_skeleton_path"], "/Game/BlenderExports/SK_Hero_Skeleton")

    def test_keys_round_trip(self):
        self.export_wave()
        bpy.ops.uex.export(destination="DISK")
        imported = self.reimport("A_Hero_Wave.fbx")
        start = self.head_at(imported, "root", 1)
        end = self.head_at(imported, "root", 10)
        self.assertAlmostEqual(end.x - start.x, 2.0, places=3)
        spine_start = self.head_at(imported, "spine", 1)
        self.assertAlmostEqual(spine_start.z, 0.5, places=3)

    def test_in_place_removes_root_translation(self):
        self.export_wave(root_motion="IN_PLACE")
        bpy.ops.uex.export(destination="DISK")
        imported = self.reimport("A_Hero_Wave.fbx")
        self.assertAlmostEqual((self.head_at(imported, "root", 10) - self.head_at(imported, "root", 1)).length,
                               0.0, places=3)

    def test_object_motion_baked_into_root(self):
        arm, _action = self.export_wave(root_motion="OBJECT_TO_ROOT")
        action = arm.animation_data.action
        slot = arm.animation_data.action_slot
        harness.submodule("services.scene_snapshot")  # keep import side effects consistent
        fcurve = action.fcurve_ensure_for_datablock(arm, "location", index=0)
        fcurve.keyframe_points.insert(1, 0.0)
        fcurve.keyframe_points.insert(10, 3.0)
        self.assertEqual(arm.animation_data.action_slot, slot)
        bpy.ops.uex.export(destination="DISK")
        imported = self.reimport("A_Hero_Wave.fbx")
        self.assertAlmostEqual(self.head_at(imported, "root", 10).x - self.head_at(imported, "root", 1).x, 5.0,
                               places=3)

    def test_action_only_ignores_active_action(self):
        arm, wave = self.export_wave()
        idle = bpy.data.actions.new("Hero_Idle")
        arm.animation_data.action = idle
        bpy.ops.uex.export(destination="DISK")
        self.assertEqual(arm.animation_data.action, idle)
        imported = self.reimport("A_Hero_Wave.fbx")
        self.assertAlmostEqual(self.head_at(imported, "root", 10).x, 2.0, places=3)


if __name__ == "__main__":
    unittest.main()
