"""Persistent export ids (UUIDs) on objects, collections and actions.

Ids are stored in the add-on PropertyGroup (``id.uex.uuid``). Only operators
call these functions: Blender forbids writing ID properties from draw code.

Duplicating an object (Shift+D) copies its id. :func:`repair_duplicates` keeps
the id on the copy whose name matches the recorded ``uuid_name_hint`` (the
original) and gives the others fresh ids; helpers duplicated together with
their owner (same ``.NNN`` suffix) are re-pointed to the new owner id.
"""

import re
import uuid as _uuid
from collections import defaultdict

import bpy

from .. import constants as C

_SUFFIX = re.compile(r"(\.\d{3,})$")


def new_uuid() -> str:
    return str(_uuid.uuid4())


def props(id_block):
    return getattr(id_block, C.PROP_ATTR)


def is_editable(id_block) -> bool:
    """Linked (library) data is read-only; it keeps the name-based fallback id."""
    return id_block.library is None


def ensure_uuid(id_block) -> str:
    p = props(id_block)
    if not p.uuid and is_editable(id_block):
        p.uuid = new_uuid()
        p.uuid_name_hint = id_block.name
    return p.uuid


def ensure_uuids(id_blocks) -> int:
    count = 0
    for id_block in id_blocks:
        if not props(id_block).uuid and is_editable(id_block):
            ensure_uuid(id_block)
            count += 1
    return count


def find_duplicates(id_collection) -> dict:
    groups = defaultdict(list)
    for id_block in id_collection:
        if id_block.library is not None:
            continue
        value = props(id_block).uuid
        if value:
            groups[value].append(id_block)
    return {k: v for k, v in groups.items() if len(v) > 1}


def _suffix(name: str) -> str:
    match = _SUFFIX.search(name)
    return match.group(1) if match else ""


def repair_duplicates(id_collection, dry_run: bool = False) -> list:
    """Give every copy sharing an id a fresh one. Returns ``[(name, old, new), ...]``."""
    changes = []
    for value, members in sorted(find_duplicates(id_collection).items()):
        hint = props(members[0]).uuid_name_hint
        keeper = next((m for m in members if m.name == hint), None)
        if keeper is None:
            keeper = sorted(members, key=lambda m: m.name)[0]
        for member in sorted(members, key=lambda m: m.name):
            if member == keeper:
                continue
            fresh = new_uuid()
            changes.append((member.name, value, fresh))
            if not dry_run:
                props(member).uuid = fresh
                props(member).uuid_name_hint = member.name
    return changes


def repoint_duplicated_helpers(changes, objects=None, dry_run: bool = False) -> list:
    """After owners got fresh ids, move helpers copied with them to the new owner."""
    objects = objects if objects is not None else bpy.data.objects
    moved = []
    for owner_name, old, new in changes:
        suffix = _suffix(owner_name)
        if not suffix:
            continue
        for ob in objects:
            p = props(ob)
            if p.owner_uuid == old and p.role != C.ROLE_NONE and ob.name.endswith(suffix):
                moved.append((ob.name, old, new))
                if not dry_run:
                    p.owner_uuid = new
    return moved


def repair_all(dry_run: bool = False) -> dict:
    """Repair ids across objects, collections and actions."""
    object_changes = repair_duplicates(bpy.data.objects, dry_run)
    helpers = repoint_duplicated_helpers(object_changes, dry_run=dry_run)
    return {
        "objects": object_changes,
        "helpers": helpers,
        "collections": repair_duplicates(bpy.data.collections, dry_run),
        "actions": repair_duplicates(bpy.data.actions, dry_run),
    }
