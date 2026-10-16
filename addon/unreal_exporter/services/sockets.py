"""Create sockets and preview their Unreal-relative transforms."""

import bmesh
import bpy
from mathutils import Matrix, Vector

from .. import constants as C
from ..domain import naming, planning
from ..domain.unreal_math import rotation_to_unreal_rotator
from . import ids
from .collisions import helpers_of


class SocketError(RuntimeError):
    pass


def socket_names(owner) -> set:
    names = set()
    for ob in helpers_of(owner, C.ROLE_SOCKET):
        p = ids.props(ob)
        if p.socket_name:
            names.add(p.socket_name)
        else:
            parsed = naming.parse_socket_name(ob.name, [owner.name])
            if parsed:
                names.add(parsed[1])
    return names


def placement(context, owner, mode) -> Matrix:
    """World matrix for a new socket according to ``mode``."""
    if mode == "CURSOR":
        return context.scene.cursor.matrix.copy()
    if mode == "ORIGIN":
        loc, rot, _scale = owner.matrix_world.decompose()
        return Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
    active = context.active_object
    if mode == "SELECTION":
        if active is not None and active.mode == "EDIT" and active.type == "MESH":
            bm = bmesh.from_edit_mesh(active.data)
            points = [active.matrix_world @ v.co for v in bm.verts if v.select]
        else:
            points = [ob.matrix_world.translation.copy() for ob in context.selected_objects]
        if not points:
            raise SocketError("Nothing is selected.")
        return Matrix.Translation(sum(points, Vector()) / len(points))
    if mode == "ACTIVE":
        if active is not None and active.mode == "EDIT" and active.type == "MESH":
            bm = bmesh.from_edit_mesh(active.data)
            element = bm.select_history.active
            if isinstance(element, bmesh.types.BMVert):
                return Matrix.Translation(active.matrix_world @ element.co)
            if element is not None:
                center = element.calc_center_median() if hasattr(element, "calc_center_median") else None
                if center is not None:
                    return Matrix.Translation(active.matrix_world @ center)
            raise SocketError("There is no active vertex.")
        if active is not None and active.type == "ARMATURE" and active.mode == "POSE":
            bone = context.active_pose_bone
            if bone is None:
                raise SocketError("There is no active bone.")
            loc, rot, _ = (active.matrix_world @ bone.matrix).decompose()
            return Matrix.Translation(loc) @ rot.to_matrix().to_4x4()
        raise SocketError("Active-element placement needs Edit Mode (mesh) or Pose Mode (armature).")
    raise SocketError("Unknown placement mode %r." % mode)


def _tag(ob, owner, socket_name):
    p = ids.props(ob)
    p.role = C.ROLE_SOCKET
    p.owner_uuid = ids.ensure_uuid(owner)
    p.socket_name = socket_name
    ids.ensure_uuid(ob)


def create_socket(context, owner, name, world_matrix):
    if owner.type != "MESH":
        raise SocketError("Sockets belong to mesh objects (static meshes).")
    clean = naming.sanitize_name(name or "Socket", 0).value or "Socket"
    socket_name = naming.unique_socket_name(socket_names(owner), clean)
    object_name = naming.socket_object_name(owner.name, socket_name)
    if object_name in bpy.data.objects:
        raise SocketError("An object named '%s' already exists." % object_name)
    ob = bpy.data.objects.new(object_name, None)
    for coll in owner.users_collection:
        coll.objects.link(ob)
    ob.empty_display_type = "ARROWS"
    ob.empty_display_size = max(max(owner.dimensions) * 0.15, 0.05) if owner.dimensions.length else 0.25
    ob.parent = owner
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = owner.matrix_world.inverted() @ world_matrix
    ob.hide_render = True
    _tag(ob, owner, socket_name)
    return ob


def convert_empties(owner, empties) -> list:
    """Turn existing empties into sockets of ``owner`` (renames them explicitly)."""
    converted = []
    taken = socket_names(owner)
    for empty in empties:
        if empty.type != "EMPTY" or empty == owner:
            continue
        base = empty.name
        parsed = naming.parse_socket_name(base, [owner.name])
        if parsed:
            base = parsed[1]
        socket_name = naming.unique_socket_name(taken, naming.sanitize_name(base, 0).value or "Socket")
        taken.add(socket_name)
        wanted = naming.socket_object_name(owner.name, socket_name)
        if wanted in bpy.data.objects and bpy.data.objects[wanted] != empty:
            raise SocketError("An object named '%s' already exists." % wanted)
        world = empty.matrix_world.copy()
        empty.name = wanted
        if empty.parent != owner:
            empty.parent = owner
            empty.matrix_parent_inverse = Matrix.Identity(4)
            empty.matrix_basis = owner.matrix_world.inverted() @ world
        _tag(empty, owner, socket_name)
        converted.append(empty)
    return converted


def unreal_preview(owner, socket_ob, unit_scale, world_origin=False) -> dict:
    """Expected Unreal socket transform, relative to the asset pivot (owner origin or world origin)."""
    pivot = Matrix.Identity(4) if world_origin else Matrix.Translation(owner.matrix_world.translation)
    relative = pivot.inverted() @ socket_ob.matrix_world
    loc, rot, scale = relative.decompose()
    k = planning.cm_per_unit(unit_scale)
    m3 = rot.to_matrix()
    roll, pitch, yaw = rotation_to_unreal_rotator([[m3[r][c] for c in range(3)] for r in range(3)])
    return {
        "location": (loc.x * k, -loc.y * k, loc.z * k),
        "rotation": (roll, pitch, yaw),
        "scale": tuple(scale),
    }
