"""Results, receipts and list-management utilities."""

import json
import os

import bpy
from bpy.props import StringProperty

from .. import constants as C
from ..domain import discovery
from ..services import scene_snapshot
from . import common


class UEX_OT_open_folder(bpy.types.Operator):
    """Open the export folder in the system file browser"""

    bl_idname = "uex.open_folder"
    bl_label = "Open Export Folder"
    bl_options = {"REGISTER"}

    path: StringProperty(subtype="DIR_PATH")

    def execute(self, context):
        path = self.path or common.state(context).result_dir
        if not path or not os.path.isdir(path):
            self.report({"ERROR"}, "The export folder does not exist yet.")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=path)
        return {"FINISHED"}


class UEX_OT_copy_import_command(bpy.types.Operator):
    """Copy the Unreal Python console command that runs the generated import script"""

    bl_idname = "uex.copy_import_command"
    bl_label = "Copy Unreal Import Command"
    bl_options = {"REGISTER"}

    def execute(self, context):
        script = common.state(context).script_path
        if not common.exists(script):
            self.report({"ERROR"}, "No import script yet; export with 'Disk + Import Script'.")
            return {"CANCELLED"}
        context.window_manager.clipboard = 'py "%s"' % script.replace("\\", "/")
        self.report({"INFO"}, "Copied. Paste it into Unreal's Python console (Cmd: py).")
        return {"FINISHED"}


class UEX_OT_load_receipt(bpy.types.Operator):
    """Read Unreal's import receipt and show the imported asset paths"""

    bl_idname = "uex.load_receipt"
    bl_label = "Load Import Receipt"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = common.state(context)
        path = os.path.join(st.result_dir, C.RECEIPT_FILENAME) if st.result_dir else ""
        if not common.exists(path):
            self.report({"ERROR"}, "No %s found; run the import script in Unreal first." % C.RECEIPT_FILENAME)
            return {"CANCELLED"}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                receipt = json.load(handle)
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, "Could not read the receipt: %s" % exc)
            return {"CANCELLED"}
        by_path = {}
        for entry in receipt.get("results", []):
            by_path[(entry.get("unreal_path") or "").lower()] = entry
        ok = sum(1 for e in receipt.get("results", []) if e.get("status") in ("created", "updated"))
        failed = sum(1 for e in receipt.get("results", []) if e.get("status") == "failed")
        for item in st.results:
            entry = by_path.get(item.unreal_path.lower())
            if entry is not None:
                item.status = "unreal:" + entry.get("status", "?")
                item.message = "; ".join(entry.get("messages", []))
        stale = bool(st.last_plan_id) and receipt.get("plan_id") != st.last_plan_id
        st.receipt_summary = "Unreal %s: %d imported, %d failed%s" % (
            receipt.get("engine_version", "?").split("-")[0], ok, failed,
            " (receipt is from an earlier export)" if stale else "")
        self.report({"WARNING"} if failed else {"INFO"}, st.receipt_summary)
        return {"FINISHED"}


class UEX_OT_collection_add(bpy.types.Operator):
    """Add the active collection to the chosen collections"""

    bl_idname = "uex.collection_add"
    bl_label = "Add Active Collection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        coll = context.view_layer.active_layer_collection.collection
        if coll == context.scene.collection:
            self.report({"ERROR"}, "Make a collection (not the Scene Collection) active first.")
            return {"CANCELLED"}
        s = common.settings(context)
        if any(ref.collection == coll for ref in s.chosen_collections):
            return {"CANCELLED"}
        s.chosen_collections.add().collection = coll
        s.chosen_collections_index = len(s.chosen_collections) - 1
        return {"FINISHED"}


class UEX_OT_collection_remove(bpy.types.Operator):
    """Remove the highlighted collection from the list"""

    bl_idname = "uex.collection_remove"
    bl_label = "Remove Collection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = common.settings(context)
        if 0 <= s.chosen_collections_index < len(s.chosen_collections):
            s.chosen_collections.remove(s.chosen_collections_index)
            s.chosen_collections_index = max(0, s.chosen_collections_index - 1)
        return {"FINISHED"}


class UEX_OT_actions_refresh(bpy.types.Operator):
    """List the actions that animate bones of the active armature"""

    bl_idname = "uex.actions_refresh"
    bl_label = "Refresh Actions"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == "ARMATURE"

    def execute(self, context):
        s = common.settings(context)
        snapshot = scene_snapshot.take_snapshot(context)
        arm = snapshot.object(context.active_object.name)
        names = discovery.compatible_actions(snapshot, arm)
        keep = {ref.action.name: ref.export for ref in s.actions if ref.action}
        s.actions.clear()
        for name in names:
            ref = s.actions.add()
            ref.action = bpy.data.actions[name]
            ref.export = keep.get(name, True)
        self.report({"INFO"}, "%d compatible action(s)" % len(names))
        return {"FINISHED"}


CLASSES = (UEX_OT_open_folder, UEX_OT_copy_import_command, UEX_OT_load_receipt, UEX_OT_collection_add,
           UEX_OT_collection_remove, UEX_OT_actions_refresh)
