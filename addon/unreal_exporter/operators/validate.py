"""Validation, issue navigation and safe fixes."""

import bpy
from bpy.props import CollectionProperty, StringProperty

from ..domain.validation import FIX_REMOVE_EMPTY_SLOTS
from ..services import export_service, fixes, scene_snapshot
from . import common


class UEX_OT_validate(bpy.types.Operator):
    """Check the export scope for problems before exporting"""

    bl_idname = "uex.validate"
    bl_label = "Validate"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            prepared = export_service.prepare(context)  # flushes Edit Mode and restores the context itself
        except Exception as exc:
            common.report_exception(self, exc, "Validation")
            return {"CANCELLED"}
        common.store_issues(context, prepared.issues, len(prepared.discovery.assets))
        common.issue_report(self, prepared)
        return {"FINISHED"}


class UEX_OT_select_object(bpy.types.Operator):
    """Select and activate the object an issue refers to"""

    bl_idname = "uex.select_object"
    bl_label = "Select Object"
    bl_options = {"REGISTER", "UNDO"}

    name: StringProperty()

    def execute(self, context):
        ob = context.scene.objects.get(self.name)
        if ob is None:
            self.report({"WARNING"}, "'%s' is not in this scene." % self.name)
            return {"CANCELLED"}
        if context.mode != "OBJECT" and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        for other in context.selected_objects:
            other.select_set(False)
        if ob.hide_get():
            ob.hide_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        return {"FINISHED"}


class UEX_FixLine(bpy.types.PropertyGroup):
    text: StringProperty()


class UEX_OT_fix(bpy.types.Operator):
    """Preview and apply a safe fix for a validation issue"""

    bl_idname = "uex.fix"
    bl_label = "Apply Fix"
    bl_options = {"REGISTER", "UNDO"}

    fix_id: StringProperty()
    object_name: StringProperty()
    preview_lines: CollectionProperty(type=UEX_FixLine, options={"SKIP_SAVE", "HIDDEN"})

    def _targets(self, context):
        if self.fix_id == FIX_REMOVE_EMPTY_SLOTS:
            if self.object_name:
                return (self.object_name,)
            return tuple(sorted({i.object_name for i in common.state(context).issues if i.fix_id == self.fix_id}))
        return ()

    def invoke(self, context, event):
        snapshot = scene_snapshot.take_snapshot(context)
        lines = fixes.preview(self.fix_id, snapshot, self._targets(context))
        if not lines:
            self.report({"INFO"}, "Nothing to fix.")
            return {"CANCELLED"}
        self.preview_lines.clear()
        for line in lines:
            self.preview_lines.add().text = line
        return context.window_manager.invoke_props_dialog(self, width=520, title=fixes.FIX_LABELS.get(self.fix_id, "Fix"))

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="These changes will be made (undo with Ctrl+Z):")
        for line in list(self.preview_lines)[:30]:
            col.label(text=line.text)
        if len(self.preview_lines) > 30:
            col.label(text="... and %d more" % (len(self.preview_lines) - 30))

    def execute(self, context):
        try:
            snapshot = scene_snapshot.take_snapshot(context)
            changed = fixes.apply(self.fix_id, snapshot, self._targets(context))
        except Exception as exc:
            common.report_exception(self, exc, "Fix")
            return {"CANCELLED"}
        self.report({"INFO"}, "%s: %d change(s). Validate again to confirm." % (
            fixes.FIX_LABELS.get(self.fix_id, self.fix_id), changed))
        bpy.ops.uex.validate()
        return {"FINISHED"}


CLASSES = (UEX_OT_validate, UEX_OT_select_object, UEX_FixLine, UEX_OT_fix)
