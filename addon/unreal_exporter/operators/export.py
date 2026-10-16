"""Export operator: modal (progress + Esc to cancel) in the UI, synchronous in background."""

import bpy
from bpy.props import BoolProperty, EnumProperty

from .. import constants as C
from ..properties import DESTINATION_ITEMS
from ..services import export_service
from . import common


class UEX_OT_export(bpy.types.Operator):
    """Validate, then export the scope to FBX files with a manifest"""

    bl_idname = "uex.export"
    bl_label = "Export"
    bl_options = {"REGISTER"}

    destination: EnumProperty(name="Destination", items=DESTINATION_ITEMS, default=C.DEST_SCRIPT)
    confirm_warnings: BoolProperty(default=False, options={"SKIP_SAVE", "HIDDEN"})
    from_dialog: BoolProperty(default=False, options={"SKIP_SAVE", "HIDDEN"})

    _job = None
    _timer = None
    _warnings = 0

    @classmethod
    def description(cls, context, properties):
        if properties.destination == C.DEST_DISK:
            return "Export FBX files and the manifest to the export folder"
        return "Export FBX files, the manifest and import_to_unreal.py to the export folder"

    def _prepare(self, context):
        try:
            prepared = export_service.prepare(context, self.destination)
        except Exception as exc:
            common.report_exception(self, exc, "Export preparation")
            return None
        common.store_issues(context, prepared.issues, len(prepared.discovery.assets))
        if prepared.plan is None or prepared.blocked:
            counts = prepared.counts
            self.report({"ERROR"}, "Export blocked: %d error(s). See the Validation panel." % counts[C.SEVERITY_ERROR])
            return None
        return prepared

    def invoke(self, context, event):
        prepared = self._prepare(context)
        if prepared is None:
            return {"CANCELLED"}
        warnings = prepared.counts[C.SEVERITY_WARNING]
        if warnings and not self.confirm_warnings:
            self._warnings = warnings
            self.from_dialog = True
            return context.window_manager.invoke_props_dialog(
                self, width=360, title="Export with %d warning(s)?" % warnings, confirm_text="Export Anyway")
        return self._start_modal(context, prepared)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="Validation found warnings (no blocking errors).", icon="ERROR")
        col.label(text="Review them in the Validation panel, or export anyway.")

    def execute(self, context):
        if self.from_dialog:
            bpy.ops.uex.export("INVOKE_DEFAULT", destination=self.destination, confirm_warnings=True)
            return {"FINISHED"}
        prepared = self._prepare(context)
        if prepared is None:
            return {"CANCELLED"}
        try:
            result = export_service.ExportJob(context, prepared).run_all()
        except Exception as exc:
            common.report_exception(self, exc, "Export")
            return {"CANCELLED"}
        return self._report_result(context, prepared, result)

    # -- modal

    def _start_modal(self, context, prepared):
        self._job = export_service.ExportJob(context, prepared)
        try:
            self._job.start()
        except Exception as exc:
            self._job.finish(cancelled=True)
            common.report_exception(self, exc, "Export")
            return {"CANCELLED"}
        wm = context.window_manager
        wm.progress_begin(0, max(self._job.total, 1))
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        self._status(context)
        return {"RUNNING_MODAL"}

    def _status(self, context):
        if context.workspace is None:
            return
        job = self._job
        name = job.plan.assets[job.index].asset_name if not job.done else ""
        context.workspace.status_text_set("Unreal Export: %d/%d %s  (Esc to cancel)" % (job.index, job.total, name))

    def modal(self, context, event):
        try:
            if event.type == "ESC" and event.value == "PRESS":
                return self._end(context, cancelled=True)
            if event.type != "TIMER":
                return {"RUNNING_MODAL"}  # consume input so the scene cannot change between assets
            more = self._job.step()
            context.window_manager.progress_update(self._job.index)
            if more:
                self._status(context)
                return {"RUNNING_MODAL"}
            return self._end(context, cancelled=False)
        except Exception as exc:  # never leave the job (and its ContextGuard) open
            common.report_exception(self, exc, "Export")
            if self._job is not None:
                return self._end(context, cancelled=True)
            return {"CANCELLED"}

    def _end(self, context, cancelled):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        if context.workspace is not None:
            context.workspace.status_text_set(None)
        result = self._job.finish(cancelled=cancelled)
        status = self._report_result(context, self._job.prepared, result)
        self._job = None
        return {"CANCELLED"} if cancelled else status

    def _report_result(self, context, prepared, result):
        common.store_result(context, result, prepared.settings.export_root)
        written = sum(1 for r in result.files if r.status == "written")
        if result.cancelled:
            self.report({"WARNING"}, "Export cancelled after %d asset(s)." % written)
        elif result.failures:
            self.report({"ERROR"}, "Exported %d asset(s); %d failed: %s" % (written, len(result.failures),
                                                                           result.failures[0]))
        else:
            self.report({"INFO"}, "Exported %d asset(s) to %s" % (written, prepared.settings.export_root))
        return {"FINISHED"} if written else {"CANCELLED"}


CLASSES = (UEX_OT_export,)
