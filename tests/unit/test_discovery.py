import unittest
from dataclasses import replace

from tests.unit import factories as F
from unreal_exporter import constants as C
from unreal_exporter.domain import discovery
from unreal_exporter.domain.models import CollectionRecord


def codes(result):
    return sorted(i.code for i in result.issues)


class HelperIndexTests(unittest.TestCase):
    def test_name_convention_helpers(self):
        snap = F.snapshot(
            F.mesh("SM_Crate"),
            F.mesh("UCX_SM_Crate_00"),
            F.mesh("UBX_SM_Crate_01"),
            F.empty("SOCKET_SM_Crate_Handle"),
            F.mesh("SM_Crate_LOD1"),
            F.mesh("SM_Crate_LOD2"),
        )
        index = discovery.build_helper_index(snap)
        self.assertEqual([(c.object_name, c.shape, c.index) for c in index.collisions["SM_Crate"]],
                         [("UCX_SM_Crate_00", C.SHAPE_CONVEX, 0), ("UBX_SM_Crate_01", C.SHAPE_BOX, 1)])
        self.assertEqual([(s.object_name, s.socket_name) for s in index.sockets["SM_Crate"]],
                         [("SOCKET_SM_Crate_Handle", "Handle")])
        self.assertEqual([(lod.index, lod.object_name) for lod in index.lods["SM_Crate"]],
                         [(1, "SM_Crate_LOD1"), (2, "SM_Crate_LOD2")])
        self.assertEqual(index.mismatched, {})

    def test_metadata_helpers_and_mismatch(self):
        root = F.mesh("SM_Box")
        snap = F.snapshot(
            root,
            F.mesh("Hull", role=C.ROLE_COLLISION, owner_uuid=root.uuid, collision_shape=C.SHAPE_CONVEX),
            F.empty("Grip", role=C.ROLE_SOCKET, owner_uuid=root.uuid, socket_name="Grip"),
            F.mesh("Simple", role=C.ROLE_LOD, owner_uuid=root.uuid, lod_index=1, lod_generated=True),
        )
        index = discovery.build_helper_index(snap)
        self.assertEqual(index.owner_of["Hull"], "SM_Box")
        self.assertEqual(index.mismatched["Hull"], ("SM_Box", "collision"))
        self.assertEqual(index.mismatched["Grip"], ("SM_Box", "socket"))
        self.assertEqual(index.mismatched["Simple"], ("SM_Box", "lod"))
        self.assertEqual(index.sockets["SM_Box"][0].socket_name, "Grip")
        self.assertTrue(index.lods["SM_Box"][0].generated)

    def test_clashing_collision_indices_are_renumbered(self):
        snap = F.snapshot(F.mesh("A"), F.mesh("UCX_A_00"), F.mesh("UBX_A_00"), F.mesh("USP_A"))
        entries = discovery.build_helper_index(snap).collisions["A"]
        self.assertEqual(sorted(e.index for e in entries), [0, 1, 2])
        self.assertEqual({e.object_name: e.index for e in entries}["UBX_A_00"], 0)

    def test_orphan_collision(self):
        snap = F.snapshot(F.mesh("UCX_Ghost_00"))
        index = discovery.build_helper_index(snap)
        self.assertIn("UCX_Ghost_00", index.orphans)

    def test_lod_suffix_without_owner_is_not_helper(self):
        snap = F.snapshot(F.mesh("Rock_LOD1"))
        self.assertNotIn("Rock_LOD1", discovery.build_helper_index(snap).owner_of)

    def test_lod0_named_root_owns_lods(self):
        snap = F.snapshot(F.mesh("Tree_LOD0"), F.mesh("Tree_LOD1"))
        index = discovery.build_helper_index(snap)
        self.assertEqual(index.owner_of["Tree_LOD1"], "Tree_LOD0")


class StaticDiscoveryTests(unittest.TestCase):
    def test_selected_mesh_exports_with_unselected_helpers(self):
        snap = F.snapshot(
            F.selected(F.mesh("Crate")),
            F.mesh("UCX_Crate_00"),
            F.empty("SOCKET_Crate_Lid"),
            F.mesh("Barrel"),
        )
        result = discovery.discover(snap, F.settings())
        self.assertEqual(len(result.assets), 1)
        asset = result.assets[0]
        self.assertEqual(asset.kind, C.KIND_STATIC_MESH)
        self.assertEqual(asset.asset_name, "SM_Crate")
        self.assertEqual(asset.unreal_path, "/Game/BlenderExports/SM_Crate")
        self.assertEqual(asset.file_relpath, "SM_Crate.fbx")
        self.assertEqual(asset.mesh_objects, ("Crate",))
        self.assertEqual(asset.collisions[0].object_name, "UCX_Crate_00")
        self.assertEqual(asset.sockets[0].socket_name, "Lid")
        self.assertEqual(asset.origin_object, "Crate")
        self.assertEqual(asset.id, "uuid-Crate")

    def test_selected_helper_resolves_to_owner(self):
        snap = F.snapshot(F.mesh("Crate"), F.selected(F.mesh("UCX_Crate_00")))
        result = discovery.discover(snap, F.settings())
        self.assertEqual([a.source_name for a in result.assets], ["Crate"])
        self.assertIn("I_HELPER_RESOLVED", codes(result))

    def test_orphan_collision_in_scope_is_blocking(self):
        snap = F.snapshot(F.selected(F.mesh("UCX_Ghost_00")))
        result = discovery.discover(snap, F.settings())
        self.assertIn("E_COLLISION_OWNER_MISSING", codes(result))
        self.assertEqual(result.assets, ())

    def test_missing_lod0(self):
        snap = F.snapshot(F.selected(F.mesh("Rock_LOD1")))
        self.assertIn("E_LOD_MISSING_LOD0", codes(discovery.discover(snap, F.settings())))

    def test_lod0_root_names_asset_without_suffix(self):
        snap = F.snapshot(F.selected(F.mesh("Tree_LOD0")), F.mesh("Tree_LOD1"))
        asset = discovery.discover(snap, F.settings()).assets[0]
        self.assertEqual(asset.asset_name, "SM_Tree")
        self.assertEqual([lod.object_name for lod in asset.lods], ["Tree_LOD1"])

    def test_overrides_and_prefix_toggle(self):
        snap = F.snapshot(F.selected(F.mesh("Crate", asset_name_override="Wooden Box", folder_override="Props/Wood")))
        asset = discovery.discover(snap, F.settings(auto_prefix=False, unreal_root="/Game/Env")).assets[0]
        self.assertEqual(asset.asset_name, "Wooden_Box")
        self.assertEqual(asset.unreal_path, "/Game/Env/Props/Wood/Wooden_Box")
        self.assertEqual(asset.file_relpath, "Props/Wood/Wooden_Box.fbx")
        self.assertEqual(asset.sanitized_from, "Wooden Box")

    def test_long_names_include_prefix_in_limit(self):
        snap = F.snapshot(F.selected(F.mesh("Prop_" + "VeryLongDescriptiveName" * 4)))
        asset = discovery.discover(snap, F.settings(max_name_length=64)).assets[0]
        self.assertLessEqual(len(asset.asset_name), 64)
        self.assertTrue(asset.asset_name.startswith("SM_Prop_VeryLong"))
        self.assertEqual(asset.sanitized_from, "Prop_" + "VeryLongDescriptiveName" * 4)

    def test_invalid_name(self):
        snap = F.snapshot(F.selected(F.mesh("日本")))
        result = discovery.discover(snap, F.settings())
        self.assertIn("E_INVALID_NAME", codes(result))

    def test_export_disabled_skipped(self):
        snap = F.snapshot(F.selected(F.mesh("Crate", export_enabled=False)))
        result = discovery.discover(snap, F.settings())
        self.assertIn("I_EXPORT_DISABLED", codes(result))
        self.assertIn("E_NO_ASSETS", codes(result))

    def test_world_origin_mode(self):
        snap = F.snapshot(F.selected(F.mesh("Crate")))
        asset = discovery.discover(snap, F.settings(origin_mode=C.ORIGIN_WORLD)).assets[0]
        self.assertEqual(asset.origin_object, "")

    def test_mirror_collection_folders(self):
        props = CollectionRecord(name="Props", objects=("Crate",), children=("Kitchen",))
        kitchen = CollectionRecord(name="Kitchen", objects=("Pot",))
        master = CollectionRecord(name=C.MASTER_COLLECTION, children=("Props",))
        snap = F.snapshot(
            F.selected(F.mesh("Crate", collections=("Props",))),
            F.selected(F.mesh("Pot", collections=("Kitchen",))),
            collections=(master, props, kitchen),
        )
        assets = discovery.discover(snap, F.settings(mirror_collections_as_folders=True)).assets
        self.assertEqual({a.unreal_path for a in assets},
                         {"/Game/BlenderExports/Props/SM_Crate", "/Game/BlenderExports/Props/Kitchen/SM_Pot"})


class ScopeTests(unittest.TestCase):
    def test_active_collection_scope(self):
        snap = F.snapshot(F.mesh("A", collections=("Props",)), F.mesh("B", collections=("Other",)),
                          active_collection="Props")
        assets = discovery.discover(snap, F.settings(scope=C.SCOPE_ACTIVE_COLLECTION)).assets
        self.assertEqual([a.source_name for a in assets], ["A"])

    def test_chosen_collections_missing(self):
        snap = F.snapshot(F.mesh("A"))
        result = discovery.discover(snap, F.settings(scope=C.SCOPE_CHOSEN_COLLECTIONS, chosen_collections=("Nope",)))
        self.assertIn("E_COLLECTION_MISSING", codes(result))

    def test_no_active_collection(self):
        snap = F.snapshot(F.mesh("A"))
        result = discovery.discover(snap, F.settings(scope=C.SCOPE_ACTIVE_COLLECTION))
        self.assertIn("E_NO_ACTIVE_COLLECTION", codes(result))


class CollectionGroupingTests(unittest.TestCase):
    def test_one_asset_per_collection_with_offset(self):
        props = CollectionRecord(name="Props", uuid="coll-props", objects=("Wall", "Roof", "UCX_Wall_00"),
                                 instance_offset=(1.0, 2.0, 0.0))
        master = CollectionRecord(name=C.MASTER_COLLECTION, children=("Props",))
        snap = F.snapshot(
            F.mesh("Wall"), F.mesh("Roof"), F.mesh("UCX_Wall_00"),
            collections=(master, props), active_collection="Props",
        )
        result = discovery.discover(snap, F.settings(scope=C.SCOPE_ACTIVE_COLLECTION, grouping=C.GROUP_PER_COLLECTION))
        self.assertEqual(len(result.assets), 1)
        asset = result.assets[0]
        self.assertEqual(asset.asset_name, "SM_Props")
        self.assertEqual(asset.id, "coll-props")
        self.assertEqual(asset.mesh_objects, ("Roof", "Wall"))
        self.assertEqual([c.object_name for c in asset.collisions], ["UCX_Wall_00"])
        self.assertEqual(asset.origin_offset, (1.0, 2.0, 0.0))

    def test_collections_do_not_leak_helpers(self):
        a = CollectionRecord(name="A", objects=("Wall", "UCX_Wall_00"))
        b = CollectionRecord(name="B", objects=("Door", "SOCKET_Door_Knob"))
        master = CollectionRecord(name=C.MASTER_COLLECTION, children=("A", "B"))
        snap = F.snapshot(
            F.mesh("Wall", collections=("A",)), F.mesh("UCX_Wall_00", collections=("A",)),
            F.mesh("Door", collections=("B",)), F.empty("SOCKET_Door_Knob", collections=("B",)),
            collections=(master, a, b),
        )
        result = discovery.discover(snap, F.settings(scope=C.SCOPE_CHOSEN_COLLECTIONS, chosen_collections=("A", "B"),
                                                     grouping=C.GROUP_PER_COLLECTION))
        by_name = {asset.asset_name: asset for asset in result.assets}
        self.assertEqual([c.object_name for c in by_name["SM_A"].collisions], ["UCX_Wall_00"])
        self.assertEqual(by_name["SM_A"].sockets, ())
        self.assertEqual([s.object_name for s in by_name["SM_B"].sockets], ["SOCKET_Door_Knob"])
        self.assertEqual(by_name["SM_B"].collisions, ())


class SkeletalDiscoveryTests(unittest.TestCase):
    def _rig(self, **arm_kw):
        return F.snapshot(
            F.selected(F.armature("Hero", **arm_kw)),
            F.skinned("Hero_Body", "Hero"),
            F.skinned("Hero_Hair", "Hero"),
            actions=(F.action("Run"), F.action("Idle"), F.action("Unrelated", bones=("tail",))),
        )

    def test_skeletal_asset(self):
        result = discovery.discover(self._rig(), F.settings(profile=C.PROFILE_SKELETAL_MESH))
        self.assertEqual(len(result.assets), 1)
        asset = result.assets[0]
        self.assertEqual(asset.kind, C.KIND_SKELETAL_MESH)
        self.assertEqual(asset.asset_name, "SK_Hero")
        self.assertEqual(asset.mesh_objects, ("Hero_Body", "Hero_Hair"))
        self.assertEqual(asset.skeleton_path, "/Game/BlenderExports/SK_Hero_Skeleton")

    def test_selecting_skinned_mesh_resolves_armature(self):
        snap = F.snapshot(F.armature("Hero"), F.selected(F.skinned("Hero_Body", "Hero")))
        asset = discovery.discover(snap, F.settings(profile=C.PROFILE_SKELETAL_MESH)).assets[0]
        self.assertEqual(asset.armature, "Hero")

    def test_armature_without_meshes(self):
        snap = F.snapshot(F.selected(F.armature("Lonely")))
        result = discovery.discover(snap, F.settings(profile=C.PROFILE_SKELETAL_MESH))
        self.assertIn("E_MISSING_DATA", codes(result))

    def test_mesh_with_two_armatures(self):
        from unreal_exporter.domain.models import ModifierRecord
        mods = (ModifierRecord(name="A", type="ARMATURE", target="RigA"),
                ModifierRecord(name="B", type="ARMATURE", target="RigB"))
        snap = F.snapshot(F.armature("RigA"), F.armature("RigB"), F.selected(F.skinned("Body", "RigA", modifiers=mods)))
        result = discovery.discover(snap, F.settings(profile=C.PROFILE_SKELETAL_MESH))
        self.assertIn("E_MULTIPLE_ARMATURES", codes(result))

    def test_animation_assets_per_action(self):
        result = discovery.discover(self._rig(), F.settings(profile=C.PROFILE_ANIMATION, actions=("Run", "Idle", "Unrelated")))
        names = [a.asset_name for a in result.assets]
        self.assertEqual(names, ["A_Idle", "A_Run"])
        run = [a for a in result.assets if a.action == "Run"][0]
        self.assertEqual(run.skeleton_path, "/Game/BlenderExports/SK_Hero_Skeleton")
        self.assertEqual((run.frame_start, run.frame_end), (1.0, 24.0))
        self.assertEqual(run.mesh_objects, ())
        self.assertIn("I_ACTION_INCOMPATIBLE", codes(result))

    def test_animation_uses_active_action_by_default(self):
        snap = F.snapshot(F.selected(F.armature("Hero", active_action="Run")), actions=(F.action("Run"),))
        assets = discovery.discover(snap, F.settings(profile=C.PROFILE_ANIMATION)).assets
        self.assertEqual([a.action for a in assets], ["Run"])

    def test_animation_without_action(self):
        snap = F.snapshot(F.selected(F.armature("Hero")))
        result = discovery.discover(snap, F.settings(profile=C.PROFILE_ANIMATION))
        self.assertIn("E_NO_ACTION", codes(result))

    def test_skeletal_with_animations_links_skeleton(self):
        settings = F.settings(profile=C.PROFILE_SKELETAL_MESH, skeletal_include_animations=True, actions=("Run",))
        assets = discovery.discover(self._rig(), settings).assets
        sk = [a for a in assets if a.kind == C.KIND_SKELETAL_MESH][0]
        anim = [a for a in assets if a.kind == C.KIND_ANIMATION][0]
        self.assertEqual(anim.skeleton_asset_id, sk.id)

    def test_frame_range_modes(self):
        snap = F.snapshot(F.selected(F.armature("Hero", active_action="Run")), actions=(F.action("Run", start=5, end=9),),
                          frame_start=1, frame_end=100)
        scene = discovery.discover(snap, F.settings(profile=C.PROFILE_ANIMATION, frame_range_mode=C.FRAME_RANGE_SCENE))
        custom = discovery.discover(snap, F.settings(profile=C.PROFILE_ANIMATION, frame_range_mode=C.FRAME_RANGE_CUSTOM,
                                                     custom_frame_start=2, custom_frame_end=3))
        action = discovery.discover(snap, F.settings(profile=C.PROFILE_ANIMATION))
        self.assertEqual((scene.assets[0].frame_start, scene.assets[0].frame_end), (1.0, 100.0))
        self.assertEqual((custom.assets[0].frame_start, custom.assets[0].frame_end), (2.0, 3.0))
        self.assertEqual((action.assets[0].frame_start, action.assets[0].frame_end), (5.0, 9.0))

    def test_collection_scene_mixes_static_and_skeletal(self):
        snap = F.snapshot(
            F.armature("Hero", collections=("Level",)),
            F.skinned("Hero_Body", "Hero", collections=("Level",)),
            F.mesh("Crate", collections=("Level",)),
            active_collection="Level",
        )
        assets = discovery.discover(snap, F.settings(profile=C.PROFILE_COLLECTION_SCENE,
                                                     scope=C.SCOPE_ACTIVE_COLLECTION)).assets
        self.assertEqual(sorted((a.kind, a.asset_name) for a in assets),
                         [(C.KIND_SKELETAL_MESH, "SK_Hero"), (C.KIND_STATIC_MESH, "SM_Crate")])

    def test_static_profile_exports_skinned_mesh_as_static(self):
        snap = F.snapshot(F.armature("Hero"), F.selected(F.skinned("Body", "Hero")))
        assets = discovery.discover(snap, F.settings(profile=C.PROFILE_STATIC_MESH)).assets
        self.assertEqual([(a.kind, a.asset_name) for a in assets], [(C.KIND_STATIC_MESH, "SM_Body")])


if __name__ == "__main__":
    unittest.main()
