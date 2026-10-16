"""Collision, socket, LOD, rename, fix and id services."""

import math
import unittest

import bpy
from mathutils import Matrix, Vector

from tests.blender import fixtures, harness


class HelperTestBase(unittest.TestCase):
    def setUp(self):
        harness.fresh_file()
        self.ctx = bpy.context
        self.collisions = harness.submodule("services.collisions")
        self.sockets = harness.submodule("services.sockets")
        self.lods = harness.submodule("services.lods")
        self.rename = harness.submodule("services.rename")
        self.ids = harness.submodule("services.ids")
        self.snapshot = harness.submodule("services.scene_snapshot")
        self.fixes = harness.submodule("services.fixes")
        self.crate = fixtures.crate("SM_Crate", location=(1.0, 0.0, 0.0), bevel=True)


class CollisionTests(HelperTestBase):
    def test_every_shape_is_named_parented_and_tagged(self):
        made = [self.collisions.create_collision(self.ctx, self.crate, shape)
                for shape in ("BOX", "SPHERE", "CAPSULE", "CONVEX", "CYLINDER")]
        self.assertEqual([ob.name for ob in made],
                         ["UBX_SM_Crate_00", "USP_SM_Crate_01", "UCP_SM_Crate_02", "UCX_SM_Crate_03", "UCX_SM_Crate_04"])
        bpy.context.view_layer.update()
        for ob in made:
            self.assertEqual(ob.parent, self.crate)
            self.assertEqual(ob.uex.role, "COLLISION")
            self.assertEqual(ob.uex.owner_uuid, self.crate.uex.uuid)
            self.assertTrue(ob.hide_render)
            self.assertEqual(ob.display_type, "WIRE")
            self.assertTrue((ob.matrix_world.translation - self.crate.matrix_world.translation).length < 1e-6)

    def test_box_fits_bounds_exactly(self):
        box = self.collisions.create_collision(self.ctx, self.crate, "BOX")
        xs = [v.co.x for v in box.data.vertices]
        self.assertEqual(len(box.data.vertices), 8)
        self.assertAlmostEqual(min(xs), -0.5, places=5)
        self.assertAlmostEqual(max(xs), 0.5, places=5)

    def test_capsule_follows_longest_axis_with_poles(self):
        self.crate.modifiers.clear()
        self.crate.data.transform(Matrix.Diagonal((1.0, 1.0, 3.0, 1.0)))
        capsule = self.collisions.create_collision(self.ctx, self.crate, "CAPSULE")
        self.assertLess(len(capsule.data.vertices), 200)
        zs = sorted(v.co.z for v in capsule.data.vertices)
        self.assertEqual(sum(1 for z in zs if abs(z - zs[0]) < 1e-6), 1)  # single pole vertex
        self.assertEqual(sum(1 for z in zs if abs(z - zs[-1]) < 1e-6), 1)
        self.assertAlmostEqual(zs[-1] - zs[0], 3.0, places=4)

    def test_convex_hull_is_convex(self):
        hull = self.collisions.create_collision(self.ctx, self.crate, "CONVEX")
        stats = harness.submodule("services.mesh_stats").compute(hull, self.ctx.evaluated_depsgraph_get(),
                                                                 collision=True)
        self.assertTrue(stats.is_convex)
        self.assertEqual(stats.non_manifold_edge_count, 0)

    def test_edit_mode_fit_to_selection(self):
        harness.select_only(self.crate)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for v in self.crate.data.vertices:
            v.select = v.co.z > 0.0
        bpy.ops.object.mode_set(mode="EDIT")
        result = bpy.ops.uex.add_collision(shape="BOX")
        bpy.ops.object.mode_set(mode="OBJECT")
        self.assertEqual(result, {"FINISHED"})
        box = bpy.data.objects["UBX_SM_Crate_00"]
        self.assertGreaterEqual(min(v.co.z for v in box.data.vertices), 0.0 - 1e-6)

    def test_visibility_operator(self):
        hull = self.collisions.create_collision(self.ctx, self.crate, "CONVEX")
        harness.select_only(self.crate)
        bpy.ops.uex.helpers_visibility(kind="COLLISION", action="HIDE")
        self.assertTrue(hull.hide_get())
        bpy.ops.uex.helpers_visibility(kind="COLLISION", action="SHOW")
        self.assertFalse(hull.hide_get())


class SocketTests(HelperTestBase):
    def test_socket_at_cursor_and_preview(self):
        self.ctx.scene.cursor.location = (1.0, 0.0, 0.5)
        self.ctx.scene.cursor.rotation_euler = (0.0, 0.0, math.radians(90.0))
        harness.select_only(self.crate)
        self.assertEqual(bpy.ops.uex.add_socket(mode="CURSOR", socket_name="Lid"), {"FINISHED"})
        socket = bpy.data.objects["SOCKET_SM_Crate_Lid"]
        self.assertEqual(socket.parent, self.crate)
        self.assertEqual(socket.uex.socket_name, "Lid")
        preview = self.sockets.unreal_preview(self.crate, socket, 1.0)
        self.assertAlmostEqual(preview["location"][2], 50.0, places=4)
        self.assertAlmostEqual(preview["rotation"][2], -90.0, places=4)

    def test_unique_socket_names(self):
        harness.select_only(self.crate)
        bpy.ops.uex.add_socket(mode="ORIGIN", socket_name="Grip")
        bpy.ops.uex.add_socket(mode="ORIGIN", socket_name="Grip")
        self.assertIn("SOCKET_SM_Crate_Grip_1", bpy.data.objects)

    def test_convert_selected_empties(self):
        empty = fixtures.link(bpy.data.objects.new("Handle", None))
        empty.location = (1.0, 0.0, 1.0)
        harness.select_only(self.crate, empty)
        self.assertEqual(bpy.ops.uex.add_socket(mode="EMPTY"), {"FINISHED"})
        self.assertEqual(empty.name, "SOCKET_SM_Crate_Handle")
        self.assertTrue((empty.matrix_world.translation - Vector((1.0, 0.0, 1.0))).length < 1e-6)

    def test_selection_median(self):
        other = fixtures.crate("Other", location=(3.0, 0.0, 0.0))
        harness.select_only(self.crate, other)
        bpy.ops.uex.add_socket(mode="SELECTION", socket_name="Mid")
        socket = bpy.data.objects["SOCKET_SM_Crate_Mid"]
        self.assertAlmostEqual(socket.matrix_world.translation.x, 2.0, places=5)


class LodTests(HelperTestBase):
    def test_generate_update_remove(self):
        report = self.lods.generate(self.ctx, self.crate, [0.5, 0.25])
        self.assertEqual(report["created"], ["SM_Crate_LOD1", "SM_Crate_LOD2"])
        lod1 = bpy.data.objects["SM_Crate_LOD1"]
        self.assertEqual(lod1.data, self.crate.data)
        self.assertEqual([m.type for m in lod1.modifiers], ["BEVEL", "DECIMATE"])
        self.assertTrue(lod1.hide_get())
        stats = self.lods.stats(self.ctx, self.crate)
        self.assertGreater(stats[0][2], stats[1][2])
        self.assertGreater(stats[1][2], stats[2][2])
        self.crate.modifiers["Bevel"].segments = 3
        self.assertEqual(self.lods.update(self.ctx, self.crate), ["SM_Crate_LOD1", "SM_Crate_LOD2"])
        self.assertEqual(lod1.modifiers["Bevel"].segments, 3)
        report = self.lods.generate(self.ctx, self.crate, [0.5])
        self.assertEqual(report["removed"], ["SM_Crate_LOD2"])
        self.assertEqual(self.lods.remove(self.crate), ["SM_Crate_LOD1"])
        self.assertEqual(len(self.crate.data.vertices), 8)  # source mesh untouched

    def test_authored_lods_are_protected(self):
        authored = fixtures.crate("Simple", location=(1.0, 0.0, 0.0), size=0.9)
        self.lods.assign(self.crate, authored, 1)
        self.assertEqual(authored.name, "SM_Crate_LOD1")
        report = self.lods.generate(self.ctx, self.crate, [0.5, 0.25])
        self.assertEqual(report["skipped_authored"], ["SM_Crate_LOD1"])
        self.assertEqual(report["created"], ["SM_Crate_LOD2"])
        self.assertIn("SM_Crate_LOD1", bpy.data.objects)
        self.assertEqual(self.lods.remove(self.crate), ["SM_Crate_LOD2"])
        self.assertIn("SM_Crate_LOD1", bpy.data.objects)

    def test_ratios(self):
        self.assertEqual(self.lods.ratios_for("HALVES_3", "RATIO", "", 100), [0.5, 0.25, 0.125])
        self.assertEqual(self.lods.ratios_for("CUSTOM", "RATIO", "60, 30%", 100), [0.6, 0.3])
        self.assertEqual(self.lods.ratios_for("CUSTOM", "TRIANGLES", "50,10", 100), [0.5, 0.1])
        with self.assertRaises(self.lods.LodError):
            self.lods.ratios_for("CUSTOM", "RATIO", "150", 100)

    def test_audit_preview_is_not_exported(self):
        self.lods.generate(self.ctx, self.crate, [0.5])
        created = self.lods.audit_begin(self.ctx, self.crate)
        self.assertEqual(len(created), 2)
        snapshot = self.snapshot.take_snapshot(self.ctx)
        self.assertFalse(any(name in created for name in (o.name for o in snapshot.objects)))
        self.assertEqual(self.lods.audit_end(), 2)
        self.assertFalse(self.lods.audit_active())


class RenameTests(HelperTestBase):
    def test_rename_propagates_to_helpers(self):
        self.collisions.create_collision(self.ctx, self.crate, "CONVEX")
        self.sockets.create_socket(self.ctx, self.crate, "Lid", Matrix.Translation((1.0, 0.0, 0.5)))
        self.lods.generate(self.ctx, self.crate, [0.5])
        transform = self.rename.make_transform("REPLACE", find="Crate", replace="Barrel")
        ops = self.rename.plan([self.crate], transform)
        self.assertEqual(sorted((op.old, op.new) for op in ops), [
            ("SM_Crate", "SM_Barrel"), ("SM_Crate_LOD1", "SM_Barrel_LOD1"),
            ("SOCKET_SM_Crate_Lid", "SOCKET_SM_Barrel_Lid"), ("UCX_SM_Crate_00", "UCX_SM_Barrel_00")])
        self.assertEqual(self.rename.apply(ops), 4)
        for name in ("SM_Barrel", "SM_Barrel_LOD1", "SOCKET_SM_Barrel_Lid", "UCX_SM_Barrel_00"):
            self.assertIn(name, bpy.data.objects)

    def test_conflicts_block_apply(self):
        fixtures.crate("SM_Barrel", location=(5.0, 0.0, 0.0))
        ops = self.rename.plan([self.crate], self.rename.make_transform("SET", new_name="SM_Barrel"))
        self.assertTrue(ops[0].conflict)
        with self.assertRaises(ValueError):
            self.rename.apply(ops)
        self.assertIn("SM_Crate", bpy.data.objects)

    def test_swap_names_within_set(self):
        other = fixtures.crate("B", location=(5.0, 0.0, 0.0))
        self.crate.name = "A"
        mapping = {"A": "B", "B": "A"}
        ops = self.rename.plan([self.crate, other], lambda name: mapping[name])
        self.assertFalse(any(op.conflict for op in ops))
        self.rename.apply(ops)
        self.assertEqual(self.crate.name, "B")
        self.assertEqual(other.name, "A")


class IdAndFixTests(HelperTestBase):
    def test_duplicate_ids_are_repaired_and_helpers_follow(self):
        hull = self.collisions.create_collision(self.ctx, self.crate, "CONVEX")
        copy = self.crate.copy()
        copy.name = "SM_Crate.001"
        fixtures.link(copy)
        hull_copy = hull.copy()
        hull_copy.name = "UCX_SM_Crate_00.001"
        fixtures.link(hull_copy)
        report = self.ids.repair_all()
        self.assertEqual(sorted(name for name, _o, _n in report["objects"]), ["SM_Crate.001", "UCX_SM_Crate_00.001"])
        self.assertNotEqual(copy.uex.uuid, self.crate.uex.uuid)
        self.assertEqual(hull_copy.uex.owner_uuid, copy.uex.uuid)
        self.assertEqual(hull.uex.owner_uuid, self.crate.uex.uuid)

    def test_rename_helpers_fix(self):
        hull = self.collisions.create_collision(self.ctx, self.crate, "CONVEX")
        hull.name = "MyHull"
        snapshot = self.snapshot.take_snapshot(self.ctx)
        lines = self.fixes.preview("RENAME_HELPERS", snapshot)
        self.assertEqual(lines, ["MyHull -> UCX_SM_Crate_00"])
        self.fixes.apply("RENAME_HELPERS", snapshot)
        self.assertEqual(hull.name, "UCX_SM_Crate_00")


if __name__ == "__main__":
    unittest.main()
