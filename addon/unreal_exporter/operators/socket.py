"""Socket creation."""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .. import constants as C
from ..properties import SOCKET_MODE_ITEMS
from ..services import ids, sockets
from ..services.rename import asset_root
from . import common


def _owner(context):
    active = context.active_object
    if active is not None and active.type == "MESH":
        return asset_root(active)
    for ob in context.selected_objects:
        if ob.type == "MESH":
            return asset_root(ob)
    return None


class UEX_OT_add_socket(bpy.types.Operator):
    """Add a SOCKET_ empty to the active mesh"""

    bl_idname = "uex.add_socket"
    bl_label = "Add Socket"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(name="Place At", items=SOCKET_MODE_ITEMS, default="CURSOR")
    socket_name: StringProperty(name="Name", default="Socket")
    use_settings: BoolProperty(default=True, options={"SKIP_SAVE", "HIDDEN"})

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def invoke(self, context, event):
        if self.use_settings:
            s = common.settings(context)
            if not self.properties.is_property_set("mode"):
                self.mode = s.socket_mode
            if not self.properties.is_property_set("socket_name"):
                self.socket_name = s.socket_name
        return self.execute(context)

    def execute(self, context):
        try:
            if self.mode == "EMPTY":
                owner = _owner(context)
                if owner is None:
                    raise sockets.SocketError("Make the target mesh active and select the empties to convert.")
                empties = [ob for ob in context.selected_objects if ob.type == "EMPTY"]
                if not empties:
                    raise sockets.SocketError("Select one or more empties.")
                converted = sockets.convert_empties(owner, empties)
                self.report({"INFO"}, "Converted %s" % ", ".join(ob.name for ob in converted))
                return {"FINISHED"}
            active = context.active_object
            if self.mode == "ACTIVE" and active is not None and active.type == "ARMATURE":
                owner = next((asset_root(ob) for ob in context.selected_objects
                              if ob.type == "MESH" and ob != active), None)
            else:
                owner = _owner(context)
            if owner is None or owner.type != "MESH" or ids.props(owner).role != C.ROLE_NONE:
                raise sockets.SocketError("Select the mesh that should own the socket.")
            matrix = sockets.placement(context, owner, self.mode)
            ob = sockets.create_socket(context, owner, self.socket_name, matrix)
        except Exception as exc:
            common.report_exception(self, exc, "Add socket")
            return {"CANCELLED"}
        self.report({"INFO"}, "Added %s" % ob.name)
        return {"FINISHED"}


CLASSES = (UEX_OT_add_socket,)
