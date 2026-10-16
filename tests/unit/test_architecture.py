"""Static architecture rules, checked by parsing the add-on sources."""

import ast
import os
import unittest

from tests.unit import ADDON_DIR

PACKAGE_DIR = os.path.join(ADDON_DIR, "unreal_exporter")
BLENDER_MODULES = {"bpy", "bmesh", "mathutils", "bpy_extras", "addon_utils", "gpu", "blf"}
PURE_MODULES = [
    "constants.py",
    "domain/models.py",
    "domain/naming.py",
    "domain/discovery.py",
    "domain/validation.py",
    "domain/planning.py",
    "domain/unreal_math.py",
    "services/manifest.py",
    "services/logging.py",
    "services/unreal_script.py",
]


def python_files():
    for root, _dirs, files in os.walk(PACKAGE_DIR):
        if "__pycache__" in root or "unreal_templates" in root:
            continue
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def imported_roots(path):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], 0
        elif isinstance(node, ast.ImportFrom):
            yield (node.module or "").split(".")[0], node.level


class ArchitectureTests(unittest.TestCase):
    def test_pure_layers_do_not_import_blender(self):
        for rel in PURE_MODULES:
            path = os.path.join(PACKAGE_DIR, *rel.split("/"))
            for root, level in imported_roots(path):
                if level == 0:
                    self.assertNotIn(root, BLENDER_MODULES, "%s imports %s" % (rel, root))

    def test_package_root_does_not_import_bpy_at_module_level(self):
        with open(os.path.join(PACKAGE_DIR, "__init__.py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                self.assertFalse(any(n.split(".")[0] == "bpy" for n in names))

    def test_intra_package_imports_are_relative(self):
        for path in python_files():
            for root, level in imported_roots(path):
                if level == 0:
                    self.assertNotEqual(root, "unreal_exporter",
                                        "%s uses an absolute package import; installed extensions live at "
                                        "bl_ext.<repo>.unreal_exporter" % os.path.relpath(path, ADDON_DIR))

    def test_importer_template_is_standard_library_only(self):
        allowed = {"datetime", "hashlib", "json", "os", "traceback", "math", "unreal"}
        path = os.path.join(PACKAGE_DIR, "unreal_templates", "importer_core.py")
        for root, level in imported_roots(path):
            self.assertEqual(level, 0)
            self.assertIn(root, allowed, "importer_core imports %s" % root)

    def test_every_module_is_reloaded_on_script_reload(self):
        with open(os.path.join(PACKAGE_DIR, "__init__.py"), encoding="utf-8") as handle:
            text = handle.read()
        for path in python_files():
            rel = os.path.relpath(path, PACKAGE_DIR)[:-3].replace(os.sep, ".")
            if rel.endswith("__init__"):
                continue
            self.assertIn('"%s"' % rel, text, "%s missing from the reload order in __init__.py" % rel)


if __name__ == "__main__":
    unittest.main()
