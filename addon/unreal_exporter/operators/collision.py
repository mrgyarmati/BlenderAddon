"""Collision helper creation and helper visibility."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty

from .. import constants as C
from ..properties import CREATE_SHAPE_ITEMS
from ..services import collisions, ids
from ..services.rename import asset_root
from . import common


def selected_roots(context):
    """Selected objects resolved to asset roots (helpers -> owners), de-duplicated."""
    roots = []
    for ob in context.selected_objects:
        root = asset_root(ob)
        if root not in roots:
            roots.append(root)
    active = context.active_object
    if active is not None and not roots:
        roots.append(asset_root(active))
    return roots


class UEX_OT_add_collision(bpy.types.Operator):
    """Add a collision helper fitted to each selected mesh (or to the edit-mode selection)"""

    bl_idname = "uex.add_collision"
    bl_label = "Add Collision"
    bl_options = {"REGISTER", "UNDO"}

    shape: EnumProperty(name="Shape", items=CREATE_SHAPE_ITEMS, default=C.SHAPE_CONVEX)
    padding: FloatProperty(name="Padding", default=0.0, min=0.0, subtype="DISTANCE")
    segments: IntProperty(name="Segments", default=12, min=3, max=64)
    use_settings: BoolProperty(default=True, options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.active_object is not None or bool(context.selected_objects)

    def invoke(self, context, event):
        if self.use_settings:
            s = common.settings(context)
            if not self.properties.is_property_set("shape"):
                self.shape = s.collision_shape
            self.padding = s.collision_padding
            self.segments = s.collision_segments
        return self.execute(context)

    def execute(self, context):
        created = []
        try:
            if context.mode == "EDIT_MESH":
                owner = context.edit_object
                if ids.props(owner).role != C.ROLE_NONE:
                    raise collisions.CollisionError("'%s' is a helper; edit the render mesh instead." % owner.name)
                points = collisions.owner_points(owner, context.evaluated_depsgraph_get(), selected_only=True)
                created.append(collisions.create_collision(context, owner, self.shape, points=points,
                                                           padding=self.padding, segments=self.segments))
            else:
                owners = [ob for ob in selected_roots(context) if ob.type == "MESH"]
                if not owners:
                    raise collisions.CollisionError("Select one or more mesh objects.")
                for owner in owners:
                    created.append(collisions.create_collision(context, owner, self.shape, padding=self.padding,
                                                               segments=self.segments))
        except Exception as exc:
            common.report_exception(self, exc, "Add collision")
            return {"CANCELLED"}
        self.report({"INFO"}, "Added %s" % ", ".join(ob.name for ob in created))
        return {"FINISHED"}


class UEX_OT_helpers_visibility(bpy.types.Operator):
    """Show or hide collision, socket and LOD helpers"""

    bl_idname = "uex.helpers_visibility"
    bl_label = "Helper Visibility"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(name="Helpers", items=(
        ("ALL", "All", ""), (C.ROLE_COLLISION, "Collisions", ""), (C.ROLE_SOCKET, "Sockets", ""),
        (C.ROLE_LOD, "LODs", "")), default="ALL")
    action: EnumProperty(name="Action", items=(("SHOW", "Show", ""), ("HIDE", "Hide", ""),
                                               ("TOGGLE", "Toggle", "")), default="TOGGLE")
    only_selected: BoolProperty(name="Selected Assets Only", default=True)

    def execute(self, context):
        roles = (C.ROLE_COLLISION, C.ROLE_SOCKET, C.ROLE_LOD) if self.kind == "ALL" else (self.kind,)
        owners = selected_roots(context) if self.only_selected else [
            ob for ob in context.scene.objects if ids.props(ob).role == C.ROLE_NONE and ob.type == "MESH"]
        helpers = []
        for owner in owners:
            for role in roles:
                helpers.extend(ob for ob in collisions.helpers_of(owner, role) if ob.name in context.view_layer.objects)
        if not helpers:
            self.report({"INFO"}, "No helpers found.")
            return {"CANCELLED"}
        if self.action == "TOGGLE":
            hide = not any(ob.hide_get() for ob in helpers)
        else:
            hide = self.action == "HIDE"
        for ob in helpers:
            ob.hide_set(hide)
        self.report({"INFO"}, "%s %d helper(s)" % ("Hid" if hide else "Showed", len(helpers)))
        return {"FINISHED"}


CLASSES = (UEX_OT_add_collision, UEX_OT_helpers_visibility)
