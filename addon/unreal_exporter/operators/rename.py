"""Batch rename with preview."""

import bpy

from ..services import rename
from . import common
from .collision import selected_roots


def _plan(context):
    s = common.settings(context)
    transform = rename.make_transform(s.rename_mode, s.rename_find, s.rename_replace, s.rename_prefix,
                                      s.rename_suffix, s.rename_name, s.rename_case_sensitive)
    roots = selected_roots(context)
    if s.rename_mode == "SET" and len(roots) != 1:
        raise ValueError("'Set Name' renames exactly one asset; select one.")
    if not roots:
        raise ValueError("Select the assets to rename.")
    return rename.plan(roots, transform)


class UEX_OT_rename_preview(bpy.types.Operator):
    """Preview renaming the selected assets and all their helpers"""

    bl_idname = "uex.rename_preview"
    bl_label = "Preview Rename"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = common.state(context)
        st.rename_preview.clear()
        try:
            ops = _plan(context)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for op in ops:
            item = st.rename_preview.add()
            item.old_name = op.old
            item.new_name = op.new
            item.kind = op.kind
            item.conflict = op.conflict
        conflicts = sum(1 for op in ops if op.conflict and op.conflict != "unchanged")
        self.report({"WARNING"} if conflicts else {"INFO"},
                    "%d rename(s), %d conflict(s)" % (len(ops), conflicts))
        return {"FINISHED"}


class UEX_OT_rename_apply(bpy.types.Operator):
    """Rename the selected assets and all their helpers"""

    bl_idname = "uex.rename_apply"
    bl_label = "Apply Rename"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            count = rename.apply(_plan(context))
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        common.state(context).rename_preview.clear()
        self.report({"INFO"}, "Renamed %d object(s)" % count)
        return {"FINISHED"}


CLASSES = (UEX_OT_rename_preview, UEX_OT_rename_apply)
