"""Batch rename asset roots and every linked helper, with conflict detection."""

import re
from dataclasses import dataclass

import bpy

from .. import constants as C
from ..domain import naming
from . import ids
from .collisions import helpers_of


@dataclass(frozen=True)
class RenameOp:
    old: str
    new: str
    kind: str  # root | collision | socket | lod
    conflict: str = ""


def asset_root(ob):
    """The asset root an object belongs to (helpers resolve to their owner)."""
    p = ids.props(ob)
    if p.role != C.ROLE_NONE and p.owner_uuid:
        for candidate in bpy.data.objects:
            if ids.props(candidate).uuid == p.owner_uuid:
                return candidate
    if p.role == C.ROLE_NONE:
        parsed = naming.parse_collision_name(ob.name)
        if parsed:
            for candidate in (parsed[1], ob.name[len(C.COLLISION_PREFIXES[parsed[0]]):]):
                if candidate in bpy.data.objects:
                    return bpy.data.objects[candidate]
        lod = naming.parse_lod_name(ob.name)
        if lod and lod[1] >= 1:
            for candidate in (lod[0], naming.lod_object_name(lod[0], 0)):
                if candidate in bpy.data.objects:
                    return bpy.data.objects[candidate]
    return ob


def make_transform(mode, find="", replace="", prefix="", suffix="", new_name="", case_sensitive=True):
    if mode == "REPLACE":
        if not find:
            raise ValueError("Enter text to find.")
        pattern = re.compile(re.escape(find), 0 if case_sensitive else re.IGNORECASE)
        return lambda name: pattern.sub(lambda _m: replace, name)
    if mode == "AFFIX":
        if not prefix and not suffix:
            raise ValueError("Enter a prefix or a suffix.")
        return lambda name: prefix + name + suffix
    if mode == "SET":
        if not new_name:
            raise ValueError("Enter the new name.")
        return lambda _name: new_name
    raise ValueError("Unknown rename mode %r." % mode)


def _helper_ops(root, new_root):
    ops = []
    for ob in helpers_of(root, C.ROLE_COLLISION):
        parsed = naming.parse_collision_name(ob.name)
        shape = ids.props(ob).collision_shape if ids.props(ob).role == C.ROLE_COLLISION else (
            parsed[0] if parsed else C.SHAPE_CONVEX)
        prefix = C.COLLISION_PREFIXES[shape]
        if parsed and naming.collision_matches_owner(ob.name, root.name):
            tail = ob.name[len(prefix) + len(root.name):]
            new = prefix + new_root + tail
        else:
            index = parsed[2] if parsed and parsed[2] is not None else len(ops)
            new = naming.collision_object_name(shape, new_root, index)
        ops.append(RenameOp(ob.name, new, "collision"))
    for ob in helpers_of(root, C.ROLE_SOCKET):
        parsed = naming.parse_socket_name(ob.name, [root.name])
        socket = ids.props(ob).socket_name or (parsed[1] if parsed else ob.name)
        ops.append(RenameOp(ob.name, naming.socket_object_name(new_root, socket), "socket"))
    new_base = naming.asset_base_name(new_root)
    for ob in helpers_of(root, C.ROLE_LOD):
        p = ids.props(ob)
        index = p.lod_index if p.role == C.ROLE_LOD else naming.parse_lod_name(ob.name)[1]
        ops.append(RenameOp(ob.name, naming.lod_object_name(new_base, index), "lod"))
    return ops


def plan(roots, transform) -> list:
    """Rename operations for ``roots`` and their helpers, conflicts annotated."""
    ops = []
    seen_roots = set()
    for root in roots:
        if root.name in seen_roots:
            continue
        seen_roots.add(root.name)
        new_root = transform(root.name)
        ops.append(RenameOp(root.name, new_root, "root"))
        ops.extend(_helper_ops(root, new_root))
    renamed_away = {op.old for op in ops}
    targets = {}
    for op in ops:
        targets.setdefault(op.new, []).append(op.old)
    out = []
    for op in ops:
        conflict = ""
        if not op.new.strip():
            conflict = "empty name"
        elif op.new == op.old:
            conflict = "unchanged"
        elif len(targets[op.new]) > 1:
            conflict = "several objects would be named '%s'" % op.new
        elif op.new in bpy.data.objects and op.new not in renamed_away:
            conflict = "'%s' already exists" % op.new
        out.append(RenameOp(op.old, op.new, op.kind, conflict))
    return out


def apply(ops) -> int:
    """Apply non-conflicting renames in two phases. Returns the number applied."""
    todo = [op for op in ops if not op.conflict]
    blocking = [op for op in ops if op.conflict and op.conflict != "unchanged"]
    if blocking:
        raise ValueError("Resolve %d conflict(s) before renaming." % len(blocking))
    objects = bpy.data.objects
    staged = []
    for index, op in enumerate(todo):
        ob = objects.get(op.old)
        if ob is None:
            raise ValueError("'%s' no longer exists; refresh the preview." % op.old)
        temp = "__uex_rename_%d" % index
        ob.name = temp
        staged.append((ob, op))
    for ob, op in staged:
        ob.name = op.new
        if ob.name != op.new:
            raise ValueError("Could not rename '%s' to '%s' (got '%s')." % (op.old, op.new, ob.name))
        p = ids.props(ob)
        if p.uuid:
            p.uuid_name_hint = ob.name
    return len(staged)
