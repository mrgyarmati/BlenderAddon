"""Validation issue browser."""

import bpy

from .. import constants as C
from ..services import fixes
from . import common
from .common import CATEGORY


class UEX_PT_validation(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "Validation"
    bl_order = 10

    def draw_header(self, context):
        st = common.state(context)
        if st.validated:
            icon = "CANCEL" if st.issue_errors else ("ERROR" if st.issue_warnings else "CHECKMARK")
            self.layout.label(text="", icon=icon)

    def draw(self, context):
        layout = self.layout
        st = common.state(context)
        if not st.validated:
            layout.label(text="Run Validate to check the export scope.", icon="INFO")
            layout.operator("uex.validate", icon="CHECKMARK")
            return
        row = layout.row(align=True)
        row.label(text="%d" % st.issue_errors, icon="CANCEL")
        row.label(text="%d" % st.issue_warnings, icon="ERROR")
        row.prop(st, "show_info", text="%d" % st.issue_infos, icon="INFO", toggle=True)
        row.operator("uex.validate", text="", icon="FILE_REFRESH")
        if not len(st.issues):
            layout.label(text="No issues found.", icon="CHECKMARK")
            return
        layout.template_list("UEX_UL_issues", "", st, "issues", st, "issues_index", rows=5)
        if not 0 <= st.issues_index < len(st.issues):
            return
        issue = st.issues[st.issues_index]
        box = layout.box()
        common.wrap(box, issue.message, width=44, icon=common.SEVERITY_ICONS.get(issue.severity, "DOT"))
        box.label(text=issue.code, icon="BLANK1")
        row = box.row(align=True)
        if issue.object_name and issue.object_name in context.scene.objects:
            op = row.operator("uex.select_object", text="Select", icon="RESTRICT_SELECT_OFF")
            op.name = issue.object_name
        if issue.fix_id:
            op = row.operator("uex.fix", text=fixes.FIX_LABELS.get(issue.fix_id, "Fix"), icon="TOOL_SETTINGS")
            op.fix_id = issue.fix_id
            op.object_name = issue.object_name
        if issue.severity == C.SEVERITY_ERROR:
            box.label(text="Blocking: export is refused until fixed.", icon="LOCKED")


CLASSES = (UEX_PT_validation,)
