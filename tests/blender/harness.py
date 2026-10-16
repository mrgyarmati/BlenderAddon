"""Shared helpers for tests that run inside Blender (background mode).

The add-on is loaded as a real extension (``bl_ext.<repo>.unreal_exporter``)
from a temporary local repository, so relative-import or packaging mistakes
fail here exactly as they would after installation.
"""

import importlib
import os
import shutil
import sys
import tempfile

import addon_utils
import bpy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPO_MODULE = "uex_tests"
PACKAGE = "unreal_exporter"
MODULE = "bl_ext.%s.%s" % (REPO_MODULE, PACKAGE)

_state = {"repo_dir": None, "module": None}


def load_addon(source_dir):
    """Register ``source_dir`` (a folder containing unreal_exporter/) as a repo and enable it."""
    prefs = bpy.context.preferences
    repo = prefs.extensions.repos.new(name="UEX Tests", module=REPO_MODULE, custom_directory=source_dir,
                                      source="USER")
    repo.use_custom_directory = True
    _state["repo_dir"] = source_dir
    bpy.ops.extensions.repo_refresh_all()
    module = addon_utils.enable(MODULE, default_set=True, handle_error=None)
    if module is None:
        raise RuntimeError("Could not enable %s from %s" % (MODULE, source_dir))
    _state["module"] = module
    return module


def addon():
    return _state["module"] or importlib.import_module(MODULE)


def submodule(name):
    return importlib.import_module(MODULE + "." + name)


def fresh_file():
    """Empty scene without resetting preferences (keeps the add-on enabled)."""
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.frame_start = 1
    scene.frame_end = 30
    return scene


class TempDir:
    def __init__(self, prefix="uex_test_"):
        self.path = tempfile.mkdtemp(prefix=prefix)

    def __enter__(self):
        return self.path

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def export_dir_settings(path):
    s = getattr(bpy.context.scene, "uex")
    s.export_dir = path
    return s


def select_only(*objects):
    view_layer = bpy.context.view_layer
    for ob in view_layer.objects:
        ob.select_set(False)
    for ob in objects:
        ob.select_set(True)
    if objects:
        view_layer.objects.active = objects[0]


def print_flush(*args):
    print(*args)
    sys.stdout.flush()
