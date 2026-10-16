"""Draw every panel through a validating fake layout.

Background Blender has no UI regions, so panels cannot draw for real. The fake
layout accepts the UILayout calls our panels make and asserts that every
property, operator and UI list they reference actually exists -- a typo in
draw code fails here instead of in a user's sidebar.
"""

import unittest

import bpy

from tests.blender import fixtures, harness


class FakeOperatorProps:
    def __init__(self, idname, test):
        module, name = idname.split(".")
        self._rna = getattr(getattr(bpy.ops, module), name).get_rna_type()
        self._test = test

    def __setattr__(self, key, value):
        if key.startswith("_"):
            object.__setattr__(self, key, value)
            return
        self._test.assertIn(key, self._rna.properties.keys(), "operator property %s" % key)


class FakeLayout:
    def __init__(self, test):
        self.test = test
        self.active = True
        self.enabled = True
        self.scale_y = 1.0
        self.use_property_split = False
        self.use_property_decorate = True
        self.alert = False

    def _child(self, *args, **kwargs):
        return FakeLayout(self.test)

    row = column = box = split = _child

    def label(self, text="", icon="NONE", **kwargs):
        self._icon(icon)

    def _icon(self, icon):
        if icon and icon != "NONE":
            items = bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items.keys()
            self.test.assertIn(icon, items, "icon %s" % icon)

    def prop(self, data, prop, **kwargs):
        self.test.assertIn(prop, data.bl_rna.properties.keys(), "%s.%s" % (data.bl_rna.identifier, prop))
        self._icon(kwargs.get("icon", "NONE"))

    def operator(self, idname, **kwargs):
        module, name = idname.split(".")
        self.test.assertTrue(hasattr(getattr(bpy.ops, module), name), "operator %s" % idname)
        self._icon(kwargs.get("icon", "NONE"))
        return FakeOperatorProps(idname, self.test)

    def template_list(self, listtype, list_id, data, propname, active_data, active_propname, **kwargs):
        self.test.assertTrue(hasattr(bpy.types, listtype), "UIList %s" % listtype)
        self.test.assertIn(propname, data.bl_rna.properties.keys())
        self.test.assertIn(active_propname, active_data.bl_rna.properties.keys())

    def separator(self, *args, **kwargs):
        pass


class FakePanel:
    def __init__(self, layout):
        self.layout = layout


PANELS = ("UEX_PT_main", "UEX_PT_asset", "UEX_PT_collision", "UEX_PT_sockets", "UEX_PT_lods", "UEX_PT_animation",
          "UEX_PT_rename", "UEX_PT_options", "UEX_PT_validation", "UEX_PT_results")


class PanelDrawTests(unittest.TestCase):
    def draw_all(self):
        for name in PANELS:
            cls = getattr(bpy.types, name)
            if hasattr(cls, "poll") and not cls.poll(bpy.context):
                continue
            panel = FakePanel(FakeLayout(self))
            if hasattr(cls, "draw_header"):
                cls.draw_header(panel, bpy.context)
            cls.draw(panel, bpy.context)

    def test_panels_in_many_states(self):
        harness.fresh_file()
        self.draw_all()  # empty scene, nothing validated
        collisions = harness.submodule("services.collisions")
        crate = fixtures.crate("SM_Crate")
        hull = collisions.create_collision(bpy.context, crate, "CONVEX")
        harness.select_only(crate)
        s = bpy.context.scene.uex
        for profile in ("STATIC_MESH", "SKELETAL_MESH", "ANIMATION", "COLLECTION_SCENE"):
            s.profile = profile
            for scope in ("SELECTED", "ACTIVE_COLLECTION", "CHOSEN_COLLECTIONS"):
                s.scope = scope
                self.draw_all()
        s.profile = "STATIC_MESH"
        s.scope = "SELECTED"
        s.lod_preset = "CUSTOM"
        for mode in ("REPLACE", "AFFIX", "SET"):
            s.rename_mode = mode
            self.draw_all()
        harness.select_only(hull)  # helper selected
        self.draw_all()
        arm, _meshes, _action = fixtures.rig("Hero")
        harness.select_only(arm)
        self.draw_all()
        harness.select_only(crate)
        bpy.ops.uex.validate()  # unsaved file + relative folder: reports a blocking issue
        self.assertIn("E_EXPORT_ROOT_MISSING", [i.code for i in bpy.context.window_manager.uex.issues])
        self.draw_all()
        with harness.TempDir() as out:
            s.export_dir = out
            bpy.ops.uex.validate()
            self.draw_all()
            bpy.ops.uex.export(destination="SCRIPT")
            bpy.ops.uex.lod_refresh()
            self.draw_all()


if __name__ == "__main__":
    unittest.main()
