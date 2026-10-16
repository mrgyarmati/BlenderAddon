"""Checks that need a real Blender window (undo and the modal export are unavailable in --background).

    blender --factory-startup --python tests/blender_gui/gui_checks.py -- <result.json> [--addon-dir DIR]

1. Undo/redo of every data-changing tool, each run the way a UI click runs it.
2. The interactive export: Export button (INVOKE_DEFAULT) -> modal timer loop -> results stored, files written,
   mode and selection restored.
3. The warning confirmation dialog opens without raising.
Writes a JSON result and quits Blender.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import traceback

import bpy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from tests.blender import fixtures, harness  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RESULT_PATH = argv[0] if argv else os.path.join(REPO_ROOT, "build", "gui_result.json")
ADDON_DIR = argv[argv.index("--addon-dir") + 1] if "--addon-dir" in argv else os.path.join(REPO_ROOT, "addon")
EXPORT_DIR = tempfile.mkdtemp(prefix="uex_gui_")
results = []
state = {"deadline": 0.0}


def add(name, ok, detail=""):
    results.append({"name": name, "ok": bool(ok), "detail": detail})


def object_state():
    return sorted((ob.name, ob.uex.role) for ob in bpy.data.objects)


def ui_override():
    """Window/area/region context: timer callbacks have none, and undo/invoke need it."""
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == "VIEW_3D")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region)


def check_undo(label, operator, **kwargs):
    """Run ``operator`` like a UI click (it pushes its own undo step), then undo and redo it."""
    before = object_state()
    outcome = operator("EXEC_DEFAULT", True, **kwargs)
    after = object_state()
    bpy.ops.ed.undo()
    restored = object_state() == before
    bpy.ops.ed.redo()
    redone = object_state() == after
    add("undo: " + label, "FINISHED" in outcome and after != before and restored and redone,
        "outcome=%s changed=%s restored=%s redone=%s" % (sorted(outcome), after != before, restored, redone))


def finish():
    with open(RESULT_PATH, "w", encoding="utf-8") as handle:
        json.dump({"checks": results}, handle, indent=1)
    shutil.rmtree(EXPORT_DIR, ignore_errors=True)
    bpy.ops.wm.quit_blender()


def start():
    try:
        harness.load_addon(ADDON_DIR)
        bpy.ops.wm.read_homefile(use_empty=True)
        with ui_override():
            crate = fixtures.crate("SM_Crate", bevel=True)
            harness.select_only(crate)
            bpy.ops.ed.undo_push(message="fixture")
            check_undo("add collision", bpy.ops.uex.add_collision, shape="CONVEX")
            check_undo("add socket", bpy.ops.uex.add_socket, mode="ORIGIN", socket_name="Grip")
            check_undo("generate LODs", bpy.ops.uex.lod_generate)
            check_undo("remove LODs", bpy.ops.uex.lod_remove)
            settings = bpy.context.scene.uex
            settings.rename_mode = "SET"
            settings.rename_name = "SM_Box"
            harness.select_only(bpy.data.objects["SM_Crate"])
            check_undo("batch rename", bpy.ops.uex.rename_apply)

            # Undo reloads data: every Python reference taken before it is now invalid,
            # and the redone rename means the mesh is now called SM_Box.
            settings = bpy.context.scene.uex
            settings.export_dir = EXPORT_DIR
            root = next(o for o in bpy.data.objects if o.type == "MESH" and o.uex.role == "NONE")
            state["root"] = root.name
            harness.select_only(root)
            bpy.ops.object.mode_set(mode="EDIT")
            outcome = bpy.ops.uex.export("INVOKE_DEFAULT", destination="SCRIPT", confirm_warnings=True)
        add("modal export starts", outcome == {"RUNNING_MODAL"}, str(sorted(outcome)))
        state["deadline"] = time.time() + 60.0
        bpy.app.timers.register(wait_for_export, first_interval=0.25)
    except Exception:
        add("gui session", False, traceback.format_exc())
        finish()
    return None


def wait_for_export():
    st = bpy.context.window_manager.uex
    if not st.result_summary:
        if time.time() < state["deadline"]:
            return 0.25
        add("modal export finishes", False, "timed out")
        finish()
        return None
    try:
        names = sorted(os.listdir(EXPORT_DIR))
        add("modal export finishes", st.result_ok, st.result_summary)
        add("modal export wrote files", {state["root"] + ".fbx", "unreal_export_manifest.json",
                                         "import_to_unreal.py"} <= set(names), str(names))
        add("results stored for the panel", bool(st.last_plan_id) and len(st.results) == 1, st.result_summary)
        add("edit mode restored after modal export", bpy.context.mode == "EDIT_MESH", bpy.context.mode)
        with ui_override():
            bpy.ops.object.mode_set(mode="OBJECT")
            crate = bpy.data.objects[state["root"]]
            crate.data.uv_layers.remove(crate.data.uv_layers[0])  # creates a warning
            harness.select_only(crate)
            outcome = bpy.ops.uex.export("INVOKE_DEFAULT", destination="DISK")
        add("warning dialog opens", outcome == {"RUNNING_MODAL"}, str(sorted(outcome)))
    except Exception:
        add("modal export checks", False, traceback.format_exc())
    finish()
    return None


bpy.app.timers.register(start, first_interval=1.0)
