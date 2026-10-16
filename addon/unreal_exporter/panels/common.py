"""Shared UI helpers and UILists."""

import textwrap

import bpy

from .. import constants as C

CATEGORY = "Unreal Export"

SEVERITY_ICONS = {C.SEVERITY_ERROR: "CANCEL", C.SEVERITY_WARNING: "ERROR", C.SEVERITY_INFO: "INFO"}
STATUS_ICONS = {"written": "CHECKMARK", "failed": "CANCEL", "skipped": "REMOVE", "pending": "TIME"}


def scene_settings(context):
    return getattr(context.scene, C.PROP_ATTR)


def state(context):
    return getattr(context.window_manager, C.PROP_ATTR)


def wrap(layout, text, width=48, icon="NONE"):
    lines = textwrap.wrap(text, width) or [""]
    col = layout.column(align=True)
    for index, line in enumerate(lines):
        col.label(text=line, icon=icon if index == 0 else "BLANK1" if icon != "NONE" else "NONE")
    return col


class UEX_UL_issues(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.message, icon=SEVERITY_ICONS.get(item.severity, "DOT"))
        if item.fix_id:
            row.label(text="", icon="TOOL_SETTINGS")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        show_info = data.show_info
        flags = [self.bitflag_filter_item if (show_info or it.severity != C.SEVERITY_INFO) else 0 for it in items]
        return flags, []


class UEX_UL_results(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        status = item.status.split(":")[-1] if item.status.startswith("unreal:") else item.status
        icon_name = "IMPORT" if item.status.startswith("unreal:") and status in ("created", "updated") else \
            STATUS_ICONS.get(status, "DOT")
        row = layout.row(align=True)
        row.label(text=item.asset_name, icon=icon_name)
        row.label(text="%.2fs" % item.seconds if not item.status.startswith("unreal:") else status)


class UEX_UL_collections(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.collection is not None:
            layout.label(text=item.collection.name, icon="OUTLINER_COLLECTION")
        else:
            layout.label(text="(missing)", icon="ERROR")


class UEX_UL_actions(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "export", text="")
        if item.action is not None:
            start, end = item.action.frame_range
            row.label(text=item.action.name, icon="ACTION")
            row.label(text="%g-%g" % (start, end))
        else:
            row.label(text="(missing)", icon="ERROR")


class UEX_UL_rename(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        bad = item.conflict and item.conflict != "unchanged"
        row.label(text=item.old_name, icon="ERROR" if bad else "FORWARD")
        row.label(text=item.new_name if not bad else item.conflict)


class UEX_UL_lod_stats(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text="LOD%d" % item.index, icon="MOD_DECIM" if item.generated else "MESH_DATA")
        row.label(text=item.object_name)
        base = data.lod_stats[0].triangles if len(data.lod_stats) else 0
        percent = (100.0 * item.triangles / base) if base else 0.0
        row.label(text="%d (%d%%)" % (item.triangles, round(percent)))


CLASSES = (UEX_UL_issues, UEX_UL_results, UEX_UL_collections, UEX_UL_actions, UEX_UL_rename, UEX_UL_lod_stats)
