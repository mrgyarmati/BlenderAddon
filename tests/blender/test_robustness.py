"""Source preservation fingerprint, cancellation and a larger scene."""

import hashlib
import json
import os
import time
import unittest

import bpy
import numpy as np

from tests.blender import fixtures, harness


def scene_fingerprint() -> str:
    """Deep hash of user data an export must never change (names, transforms, geometry, rigs, keys)."""
    h = hashlib.sha256()
    for ob in sorted(bpy.data.objects, key=lambda o: o.name):
        h.update(("%s|%s|%s|%s|%s" % (ob.name, ob.type, ob.data.name if ob.data else "",
                                      ob.parent.name if ob.parent else "", ob.parent_type)).encode())
        h.update(np.round(np.array(ob.matrix_basis), 6).tobytes())
        h.update(("%s|%s|%s" % (ob.hide_viewport, ob.hide_render, ob.hide_select)).encode())
        for mod in ob.modifiers:
            h.update(("%s:%s:%s" % (mod.name, mod.type, mod.show_viewport)).encode())
        for slot in ob.material_slots:
            h.update(("%s:%s" % (slot.link, slot.material.name if slot.material else "")).encode())
        adt = ob.animation_data
        if adt is not None:
            h.update(("%s|%s|%d" % (adt.action.name if adt.action else "", adt.action_slot.identifier
                                    if adt.action_slot else "", len(adt.nla_tracks))).encode())
        h.update(json.dumps(sorted((k, str(v)) for k, v in ob.items())).encode())
    for mesh in sorted(bpy.data.meshes, key=lambda m: m.name):
        co = np.empty(len(mesh.vertices) * 3)
        mesh.vertices.foreach_get("co", co)
        h.update(mesh.name.encode())
        h.update(np.round(co, 6).tobytes())
        h.update(("%d|%d|%s" % (len(mesh.polygons), len(mesh.uv_layers),
                                [m.name if m else "" for m in mesh.materials])).encode())
        if mesh.shape_keys:
            h.update(str([kb.name for kb in mesh.shape_keys.key_blocks]).encode())
    for arm in sorted(bpy.data.armatures, key=lambda a: a.name):
        for bone in arm.bones:
            h.update(bone.name.encode())
            h.update(np.round(np.array(bone.matrix_local), 6).tobytes())
    for action in sorted(bpy.data.actions, key=lambda a: a.name):
        h.update(action.name.encode())
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for fcurve in bag.fcurves:
                        co = np.empty(len(fcurve.keyframe_points) * 2)
                        fcurve.keyframe_points.foreach_get("co", co)
                        h.update(fcurve.data_path.encode())
                        h.update(np.round(co, 6).tobytes())
    for coll in sorted(bpy.data.collections, key=lambda c: c.name):
        h.update(("%s|%s" % (coll.name, sorted(o.name for o in coll.objects))).encode())
    return h.hexdigest()


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        harness.fresh_file()
        self._tmp = harness.TempDir()
        self.out = self._tmp.__enter__()
        self.settings = harness.export_dir_settings(self.out)
        self.service = harness.submodule("services.export_service")

    def tearDown(self):
        self._tmp.__exit__(None, None, None)

    def build_mixed(self):
        collisions = harness.submodule("services.collisions")
        lods = harness.submodule("services.lods")
        crate = fixtures.crate("SM_Crate", location=(1.0, 2.0, 0.0), bevel=True)
        collisions.create_collision(bpy.context, crate, "CONVEX")
        lods.generate(bpy.context, crate, [0.5])
        arm, _meshes, action = fixtures.rig("Hero", location=(0.0, 4.0, 0.0), shape_key=True)
        return crate, arm, action

    def test_source_fingerprint_unchanged_by_every_profile(self):
        crate, arm, action = self.build_mixed()
        ids = harness.submodule("services.ids")
        ids.ensure_uuids(bpy.data.objects)  # ids are the only data an export may add
        ids.ensure_uuids(bpy.data.actions)
        ids.ensure_uuids(bpy.data.collections)
        before = scene_fingerprint()
        for profile, selection in (("STATIC_MESH", [crate]), ("SKELETAL_MESH", [arm]), ("ANIMATION", [arm]),
                                   ("COLLECTION_SCENE", [crate, arm])):
            self.settings.profile = profile
            self.settings.actions.clear()
            self.settings.actions.add().action = action
            harness.select_only(*selection)
            self.assertEqual(bpy.ops.uex.export(destination="SCRIPT"), {"FINISHED"}, profile)
            self.assertEqual(scene_fingerprint(), before, "export with %s changed source data" % profile)

    def test_fingerprint_unchanged_after_forced_failure(self):
        crate, arm, _action = self.build_mixed()
        harness.submodule("services.ids").ensure_uuids(bpy.data.objects)
        before = scene_fingerprint()
        self.settings.profile = "COLLECTION_SCENE"
        harness.select_only(crate, arm)
        prepared = self.service.prepare(bpy.context, "DISK")
        for asset in prepared.plan.assets:
            result = self.service.ExportJob(bpy.context, prepared, fail_after_staging=asset.id).run_all()
            self.assertTrue(result.failures)
            self.assertEqual(scene_fingerprint(), before)

    def test_cancel_marks_remaining_assets_skipped(self):
        meshes = [fixtures.crate("SM_Box%02d" % i, location=(i * 2.0, 0.0, 0.0)) for i in range(4)]
        harness.select_only(*meshes)
        prepared = self.service.prepare(bpy.context, "DISK")
        job = self.service.ExportJob(bpy.context, prepared)
        job.start()
        job.step()
        result = job.cancel()
        self.assertTrue(result.cancelled)
        self.assertEqual([r.status for r in result.files], ["written", "skipped", "skipped", "skipped"])
        with open(os.path.join(self.out, "unreal_export_manifest.json"), encoding="utf-8") as handle:
            statuses = [a["status"] for a in json.load(handle)["assets"]]
        self.assertEqual(statuses, ["written", "skipped", "skipped", "skipped"])
        self.assertFalse([o.name for o in bpy.data.objects if "__uex" in o.name])

    def test_excluded_and_hidden_collections(self):
        """Regression: ContextState called hide_get() on objects outside the view layer."""
        excluded = fixtures.collection("Excluded")
        fixtures.crate("InExcluded", collection=excluded)
        hidden = fixtures.collection("Hidden")
        fixtures.crate("InHidden", collection=hidden)
        layers = bpy.context.view_layer.layer_collection.children
        layers["Excluded"].exclude = True
        layers["Hidden"].hide_viewport = True
        hidden.hide_viewport = True
        crate = fixtures.crate("SM_Visible")
        harness.select_only(crate)
        guard = harness.submodule("services.context_guard")
        before = guard.ContextState(bpy.context)
        self.assertEqual(bpy.ops.uex.export(destination="DISK"), {"FINISHED"})
        self.assertEqual(before.diff(guard.ContextState(bpy.context)), [])
        self.assertTrue(layers["Excluded"].exclude)

    def test_edit_mode_changes_are_validated(self):
        """Regression: export validation read stale object data (weights) while in Edit Mode."""
        import bmesh

        arm, meshes, _action = fixtures.rig("Hero")
        body = meshes[0]
        self.settings.profile = "SKELETAL_MESH"
        harness.select_only(body)
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(body.data)
        deform = bm.verts.layers.deform.active
        bm.verts.ensure_lookup_table()
        bm.verts[0][deform].clear()
        bmesh.update_edit_mesh(body.data)
        self.assertTrue(body.data.vertices[0].groups)  # object data is stale until Edit Mode is flushed
        with self.assertRaises(RuntimeError):  # blocking error -> export refused
            bpy.ops.uex.export(destination="DISK")
        self.assertEqual(bpy.context.mode, "EDIT_MESH")
        codes = [item.code for item in bpy.context.window_manager.uex.issues]
        self.assertIn("E_UNWEIGHTED_VERTICES", codes)
        bpy.ops.object.mode_set(mode="OBJECT")

    def test_linked_library_object_exports(self):
        """Linked data is read-only: it exports with a name-based id and is never written to."""
        library = os.path.join(self.out, "library.blend")
        source = fixtures.crate("SM_Linked")
        bpy.data.libraries.write(library, {source})
        bpy.data.objects.remove(source)
        with bpy.data.libraries.load(library, link=True) as (data_from, data_to):
            data_to.objects = ["SM_Linked"]
        linked = data_to.objects[0]
        bpy.context.scene.collection.objects.link(linked)
        export_dir = os.path.join(self.out, "export")
        self.settings.export_dir = export_dir
        harness.select_only(linked)
        self.assertEqual(bpy.ops.uex.export(destination="DISK"), {"FINISHED"})
        self.assertEqual(linked.uex.uuid, "")
        with open(os.path.join(export_dir, "unreal_export_manifest.json"), encoding="utf-8") as handle:
            asset = json.load(handle)["assets"][0]
        self.assertEqual(asset["id"], "obj:SM_Linked")
        self.assertEqual(asset["status"], "written")

    def test_larger_scene(self):
        collisions = harness.submodule("services.collisions")
        sockets = harness.submodule("services.sockets")
        from mathutils import Matrix

        roots = []
        for i in range(40):
            crate = fixtures.crate("SM_Prop%03d" % i, location=(i % 8 * 2.0, i // 8 * 2.0, 0.0))
            collisions.create_collision(bpy.context, crate, "BOX")
            sockets.create_socket(bpy.context, crate, "Top", Matrix.Translation(crate.location))
            roots.append(crate)
        harness.select_only(*roots)
        started = time.perf_counter()
        self.assertEqual(bpy.ops.uex.export(destination="SCRIPT"), {"FINISHED"})
        elapsed = time.perf_counter() - started
        with open(os.path.join(self.out, "unreal_export_manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(len(manifest["assets"]), 40)
        self.assertEqual(len({a["unreal_path"] for a in manifest["assets"]}), 40)
        self.assertLess(elapsed, 60.0, "40-asset export took %.1fs" % elapsed)
        print("larger scene: 40 assets in %.2fs" % elapsed)


if __name__ == "__main__":
    unittest.main()
