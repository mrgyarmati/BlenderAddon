"""LOD operators."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty

from .. import constants as C
from ..services import ids, lods, mesh_stats
from . import common
from .collision import selected_roots


def _mesh_roots(context):
    return [ob for ob in selected_roots(context) if ob.type == "MESH" and ids.props(ob).role == C.ROLE_NONE]


def _refresh_stats(context, owner):
    st = common.state(context)
    st.lod_stats.clear()
    st.lod_stats_owner = owner.name if owner else ""
    if owner is None:
        return
    for index, name, triangles, generated in lods.stats(context, owner):
        item = st.lod_stats.add()
        item.index = index
        item.object_name = name
        item.triangles = triangles
        item.generated = generated


class UEX_OT_lod_generate(bpy.types.Operator):
    """Generate (or update) automatic LODs with non-destructive Decimate modifiers"""

    bl_idname = "uex.lod_generate"
    bl_label = "Generate LODs"
    bl_options = {"REGISTER", "UNDO"}

    overwrite_authored: BoolProperty(name="Replace Authored LODs", default=False,
                                     description="Replace authored LODs at the same index (they are deleted)")

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def invoke(self, context, event):
        authored = []
        for owner in _mesh_roots(context):
            for _index, lod in lods.lods_of(owner).items():
                if not ids.props(lod).lod_generated:
                    authored.append(lod.name)
        if authored and not self.overwrite_authored:
            return context.window_manager.invoke_props_dialog(self, width=420,
                                                              title="Authored LODs found: %s" % ", ".join(authored[:3]))
        return self.execute(context)

    def draw(self, context):
        col = self.layout.column()
        col.label(text="Authored LODs are kept unless you allow replacing them.")
        col.prop(self, "overwrite_authored")

    def execute(self, context):
        s = common.settings(context)
        owners = _mesh_roots(context)
        if not owners:
            self.report({"ERROR"}, "Select one or more render meshes.")
            return {"CANCELLED"}
        summary = []
        try:
            depsgraph = context.evaluated_depsgraph_get()
            for owner in owners:
                base = mesh_stats.triangle_count(owner, depsgraph)
                ratios = lods.ratios_for(s.lod_preset, s.lod_mode, s.lod_custom, base)
                report = lods.generate(context, owner, ratios, overwrite_authored=self.overwrite_authored)
                summary.append("%s: %d new, %d updated, %d authored kept" % (
                    owner.name, len(report["created"]), len(report["updated"]), len(report["skipped_authored"])))
        except Exception as exc:
            common.report_exception(self, exc, "Generate LODs")
            return {"CANCELLED"}
        _refresh_stats(context, owners[0])
        self.report({"INFO"}, "; ".join(summary))
        return {"FINISHED"}


class UEX_OT_lod_update(bpy.types.Operator):
    """Re-sync generated LODs with their owner's mesh and modifiers"""

    bl_idname = "uex.lod_update"
    bl_label = "Update LODs"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        owners = _mesh_roots(context)
        names = []
        for owner in owners:
            names.extend(lods.update(context, owner))
        if owners:
            _refresh_stats(context, owners[0])
        self.report({"INFO"}, "Updated %d LOD(s)" % len(names))
        return {"FINISHED"}


class UEX_OT_lod_remove(bpy.types.Operator):
    """Delete generated LODs (authored LODs are only un-assigned when allowed)"""

    bl_idname = "uex.lod_remove"
    bl_label = "Remove LODs"
    bl_options = {"REGISTER", "UNDO"}

    include_authored: BoolProperty(name="Also Un-assign Authored LODs", default=False)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, title="Remove LODs of the selected meshes?")

    def execute(self, context):
        removed = []
        owners = _mesh_roots(context)
        for owner in owners:
            removed.extend(lods.remove(owner, include_authored=self.include_authored))
        if owners:
            _refresh_stats(context, owners[0])
        self.report({"INFO"}, "Removed %d LOD(s)" % len(removed))
        return {"FINISHED"}


class UEX_OT_lod_assign(bpy.types.Operator):
    """Assign the selected mesh as an authored LOD of the active mesh"""

    bl_idname = "uex.lod_assign"
    bl_label = "Assign Authored LOD"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(name="LOD Index", default=1, min=1, max=7)
    rename: BoolProperty(name="Rename to <Name>_LOD#", default=True)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and len(context.selected_objects) == 2

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        owner = context.active_object
        others = [ob for ob in context.selected_objects if ob != owner]
        try:
            name = lods.assign(owner, others[0], self.index, rename=self.rename)
        except Exception as exc:
            common.report_exception(self, exc, "Assign LOD")
            return {"CANCELLED"}
        _refresh_stats(context, owner)
        self.report({"INFO"}, "'%s' is now LOD%d of '%s'" % (name, self.index, owner.name))
        return {"FINISHED"}


class UEX_OT_lod_refresh(bpy.types.Operator):
    """Recount LOD triangles for the active mesh"""

    bl_idname = "uex.lod_refresh"
    bl_label = "Refresh LOD Stats"
    bl_options = {"REGISTER"}

    def execute(self, context):
        roots = _mesh_roots(context)
        _refresh_stats(context, roots[0] if roots else None)
        return {"FINISHED"}


class UEX_OT_lod_audit(bpy.types.Operator):
    """Show LOD0..N side by side as temporary previews (never exported)"""

    bl_idname = "uex.lod_audit"
    bl_label = "LOD Audit"
    bl_options = {"REGISTER", "UNDO"}

    action: EnumProperty(items=(("BEGIN", "Begin", ""), ("END", "End", "")), default="BEGIN")

    def execute(self, context):
        if self.action == "END":
            count = lods.audit_end()
            self.report({"INFO"}, "Removed %d preview object(s)" % count)
            return {"FINISHED"}
        roots = _mesh_roots(context)
        if not roots:
            self.report({"ERROR"}, "Select a render mesh with LODs.")
            return {"CANCELLED"}
        created = lods.audit_begin(context, roots[0])
        _refresh_stats(context, roots[0])
        self.report({"INFO"}, "Previewing %d LOD level(s); end the audit to remove the previews" % len(created))
        return {"FINISHED"}


CLASSES = (UEX_OT_lod_generate, UEX_OT_lod_update, UEX_OT_lod_remove, UEX_OT_lod_assign, UEX_OT_lod_refresh,
           UEX_OT_lod_audit)
