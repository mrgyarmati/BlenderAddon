"""Phase 0: the extension registers, exposes its panel, and unregisters cleanly (twice)."""

import unittest

import bpy

from tests.blender import harness


def _counts():
    handlers = {name: len(getattr(bpy.app.handlers, name)) for name in dir(bpy.app.handlers)
                if not name.startswith("_") and isinstance(getattr(bpy.app.handlers, name), list)}
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    keymaps = sum(len(km.keymap_items) for km in keyconfig.keymaps) if keyconfig else 0
    return handlers, keymaps


class RegistrationTests(unittest.TestCase):
    def test_register_unregister_twice(self):
        registration = harness.submodule("registration")
        classes = registration.all_classes()
        self.assertIn("UEX_PT_main", [cls.__name__ for cls in classes])
        handlers_before, keymaps_before = _counts()
        for _cycle in range(2):
            registration.unregister()
            for cls in classes:
                self.assertFalse(cls.is_registered, "%s still registered" % cls.__name__)
            self.assertFalse(hasattr(bpy.types, "UEX_PT_main"))
            for id_type in (bpy.types.Object, bpy.types.Scene, bpy.types.Collection, bpy.types.Action,
                            bpy.types.WindowManager):
                self.assertFalse(hasattr(id_type, "uex"), "%s.uex left behind" % id_type.__name__)
            registration.register()
            registration.register()  # idempotent
            for cls in classes:
                self.assertTrue(cls.is_registered, "%s missing after register" % cls.__name__)
            self.assertTrue(hasattr(bpy.types.Object, "uex"))
        self.assertEqual(_counts(), (handlers_before, keymaps_before))

    def test_panel_and_settings_exist(self):
        harness.fresh_file()
        self.assertEqual(bpy.types.UEX_PT_main.bl_category, "Unreal Export")
        self.assertEqual(bpy.types.UEX_PT_main.bl_label, "Unreal Export")
        s = bpy.context.scene.uex
        self.assertEqual(s.unreal_root, "/Game/BlenderExports")
        self.assertEqual(bpy.context.window_manager.uex.issues.__len__(), 0)

    def test_preferences_fallback(self):
        prefs = harness.submodule("preferences").get_prefs(bpy.context)
        self.assertFalse(prefs.developer_mode)

    def test_manifest_version_matches_constants(self):
        constants = harness.submodule("constants")
        import os
        import tomllib

        path = os.path.join(harness.REPO_ROOT, "addon", "unreal_exporter", "blender_manifest.toml")
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        self.assertEqual(data["version"], constants.ADDON_VERSION_STRING)
        self.assertEqual(data["blender_version_min"], "5.2.0")


if __name__ == "__main__":
    unittest.main()
