"""Safe fixes offered by validation issues. Each fix has a preview and an apply step."""

import bpy

from .. import constants as C
from ..domain import discovery, naming
from ..domain.validation import FIX_REMOVE_EMPTY_SLOTS, FIX_RENAME_HELPERS, FIX_REPAIR_UUIDS
from . import ids, rename

FIX_LABELS = {
    FIX_RENAME_HELPERS: "Rename helpers to match their owner",
    FIX_REPAIR_UUIDS: "Give duplicated objects their own export id",
    FIX_REMOVE_EMPTY_SLOTS: "Remove empty material slots",
}


def _helper_role(ob) -> str:
    p = ids.props(ob)
    if p.role != C.ROLE_NONE:
        return p.role
    if naming.parse_collision_name(ob.name):
        return C.ROLE_COLLISION
    if ob.type == "EMPTY" and ob.name.startswith(C.SOCKET_PREFIX):
        return C.ROLE_SOCKET
    return C.ROLE_LOD


def _free_collision_index(helpers, owner_name, taken) -> int:
    for other in helpers.collisions.get(owner_name, ()):
        parsed = naming.parse_collision_name(other.object_name)
        if other.object_name not in helpers.mismatched and parsed and parsed[2] is not None:
            taken.add(parsed[2])
    index = 0
    while index in taken:
        index += 1
    taken.add(index)
    return index


def _rename_helper_ops(snapshot):
    """Rename operations that make every mismatched helper follow its owner's name."""
    helpers = discovery.build_helper_index(snapshot)
    ops = []
    taken_indices = {}
    for helper_name, (owner_name, _kind) in sorted(helpers.mismatched.items()):
        ob = bpy.data.objects.get(helper_name)
        if ob is None or owner_name not in bpy.data.objects:
            continue
        p = ids.props(ob)
        role = _helper_role(ob)
        if role == C.ROLE_COLLISION:
            parsed = naming.parse_collision_name(ob.name)
            shape = p.collision_shape if p.role == C.ROLE_COLLISION else parsed[0]
            index = _free_collision_index(helpers, owner_name, taken_indices.setdefault(owner_name, set()))
            new = naming.collision_object_name(shape, owner_name, index)
        elif role == C.ROLE_SOCKET:
            parsed = naming.parse_socket_name(ob.name, [])
            socket = p.socket_name or (parsed[1] if parsed else naming.sanitize_name(ob.name, 0).value) or "Socket"
            new = naming.socket_object_name(owner_name, socket)
        else:
            parsed = naming.parse_lod_name(ob.name)
            index = p.lod_index if p.role == C.ROLE_LOD else (parsed[1] if parsed else 1)
            new = naming.lod_object_name(naming.asset_base_name(owner_name), index)
        ops.append(rename.RenameOp(ob.name, new, role.lower()))
    return ops


def preview(fix_id, snapshot, object_names=()) -> list:
    """Human-readable lines describing what the fix would change."""
    if fix_id == FIX_RENAME_HELPERS:
        lines = []
        for op in _rename_helper_ops(snapshot):
            lines.append("%s -> %s%s" % (op.old, op.new, (" (blocked: %s)" % _conflict(op)) if _conflict(op) else ""))
        return lines
    if fix_id == FIX_REPAIR_UUIDS:
        report = ids.repair_all(dry_run=True)
        return ["%s gets a new export id" % name for name, _old, _new in report["objects"]] + \
               ["%s follows its duplicated owner" % name for name, _old, _new in report["helpers"]]
    if fix_id == FIX_REMOVE_EMPTY_SLOTS:
        lines = []
        for name in object_names:
            ob = bpy.data.objects.get(name)
            if ob is None:
                continue
            empty = [i for i, slot in enumerate(ob.material_slots) if slot.material is None]
            if empty:
                shared = " (mesh shared by %d objects)" % ob.data.users if ob.data and ob.data.users > 1 else ""
                lines.append("%s: remove slot(s) %s%s" % (name, ", ".join(str(i) for i in empty), shared))
        return lines
    return []


def _conflict(op) -> str:
    holder = bpy.data.objects.get(op.new)
    if holder is not None and holder.name != op.old:
        return "'%s' already exists" % op.new
    return ""


def apply(fix_id, snapshot, object_names=()) -> int:
    if fix_id == FIX_RENAME_HELPERS:
        ops = [rename.RenameOp(op.old, op.new, op.kind, _conflict(op)) for op in _rename_helper_ops(snapshot)]
        applied = rename.apply([op for op in ops if not op.conflict])
        # Name-matched helpers get explicit metadata so future renames follow.
        helpers = discovery.build_helper_index(snapshot)
        for op in ops:
            if op.conflict:
                continue
            ob = bpy.data.objects.get(op.new)
            owner = bpy.data.objects.get(helpers.owner_of.get(op.old, ""))
            if ob is not None and owner is not None:
                ids.props(ob).owner_uuid = ids.ensure_uuid(owner)
        return applied
    if fix_id == FIX_REPAIR_UUIDS:
        report = ids.repair_all()
        return len(report["objects"]) + len(report["helpers"]) + len(report["collections"]) + len(report["actions"])
    if fix_id == FIX_REMOVE_EMPTY_SLOTS:
        removed = 0
        for name in object_names:
            ob = bpy.data.objects.get(name)
            if ob is None or ob.data is None:
                continue
            for index in reversed([i for i, slot in enumerate(ob.material_slots) if slot.material is None]):
                if ob.material_slots[index].link == "DATA":
                    ob.data.materials.pop(index=index)
                    removed += 1
        return removed
    raise ValueError("Unknown fix %r." % fix_id)
