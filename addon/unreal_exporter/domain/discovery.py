"""Resolve the export scope into :class:`ExportAsset` records.

Discovery is pure: it reads a :class:`SceneSnapshot` and :class:`ExportSettings`
and returns assets plus structured issues. Helpers (collisions, sockets, LODs)
are resolved against the whole snapshot, so exporting a selected mesh also
exports its unselected helpers, and selecting a helper exports its owner.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .. import constants as C
from . import naming
from .models import (
    CollisionEntry,
    ExportAsset,
    ExportSettings,
    LodEntry,
    ObjectRecord,
    SceneSnapshot,
    SocketEntry,
    ValidationIssue,
)


@dataclass(frozen=True)
class HelperIndex:
    collisions: dict  # owner name -> tuple[CollisionEntry]
    sockets: dict  # owner name -> tuple[SocketEntry]
    lods: dict  # owner name -> tuple[LodEntry]
    owner_of: dict  # helper name -> owner name
    orphans: dict  # helper name -> reason (no resolvable owner)
    mismatched: dict  # helper name -> (owner name, kind) where the name does not match the owner


@dataclass(frozen=True)
class DiscoveryResult:
    assets: tuple
    issues: tuple
    helpers: HelperIndex


def _issue(code, severity, message, obj="", fix="", asset="", **details):
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        object_id=obj,
        fix_id=fix,
        details=tuple(sorted((k, v) for k, v in details.items())),
        asset_id=asset,
    )


# ---------------------------------------------------------------- helpers


def build_helper_index(snapshot: SceneSnapshot) -> HelperIndex:
    """Map every collision/socket/LOD helper in the snapshot to its owner."""
    mesh_names = {ob.name for ob in snapshot.objects if ob.type == "MESH"}
    collisions = defaultdict(list)
    sockets = defaultdict(list)
    lods = defaultdict(list)
    owner_of = {}
    orphans = {}
    mismatched = {}

    def owner_by_uuid(ob):
        owner = snapshot.object_by_uuid(ob.owner_uuid)
        if owner is not None and owner.name != ob.name:
            return owner
        return None

    for ob in sorted(snapshot.objects, key=lambda o: o.name):
        role = ob.role
        if role == C.ROLE_NONE:
            role = _role_from_name(ob, snapshot, mesh_names)
        if role == C.ROLE_NONE:
            continue

        owner = owner_by_uuid(ob) if ob.owner_uuid else None
        if ob.owner_uuid and owner is None and ob.role != C.ROLE_NONE:
            # Metadata points at an object that no longer exists.
            name_owner = _owner_from_name(ob, role, snapshot, mesh_names)
            if name_owner:
                mismatched[ob.name] = (name_owner, "stale-owner")
                owner = snapshot.object(name_owner)
            else:
                orphans[ob.name] = "owner-missing"
                continue
        if owner is None:
            name_owner = _owner_from_name(ob, role, snapshot, mesh_names)
            if not name_owner:
                orphans[ob.name] = "no-owner-name"
                continue
            owner = snapshot.object(name_owner)
            if owner is None:
                orphans[ob.name] = "no-owner-name"
                continue

        owner_of[ob.name] = owner.name
        if role == C.ROLE_COLLISION:
            parsed = naming.parse_collision_name(ob.name)
            shape = ob.collision_shape or (parsed[0] if parsed else C.SHAPE_CONVEX)
            if not naming.collision_matches_owner(ob.name, owner.name):
                mismatched.setdefault(ob.name, (owner.name, "collision"))
            collisions[owner.name].append(CollisionEntry(object_name=ob.name, shape=shape, index=0))
        elif role == C.ROLE_SOCKET:
            socket = ob.socket_name
            parsed = naming.parse_socket_name(ob.name, [owner.name])
            if parsed and parsed[0] == owner.name:
                socket = socket or parsed[1]
            else:
                mismatched.setdefault(ob.name, (owner.name, "socket"))
                if not socket and parsed:
                    socket = parsed[1]
            sockets[owner.name].append(SocketEntry(object_name=ob.name, socket_name=socket or ob.name))
        elif role == C.ROLE_LOD:
            index = ob.lod_index
            parsed = naming.parse_lod_name(ob.name)
            if index < 1 and parsed:
                index = parsed[1]
            expected = naming.lod_object_name(naming.asset_base_name(owner.name), index)
            if ob.name != expected:
                mismatched.setdefault(ob.name, (owner.name, "lod"))
            lods[owner.name].append(LodEntry(index=index, object_name=ob.name, generated=ob.lod_generated))

    collisions_out = {owner: _number_collisions(entries) for owner, entries in collisions.items()}
    return HelperIndex(
        collisions=collisions_out,
        sockets={k: tuple(sorted(v, key=lambda e: e.object_name)) for k, v in sockets.items()},
        lods={k: tuple(sorted(v, key=lambda e: (e.index, e.object_name))) for k, v in lods.items()},
        owner_of=owner_of,
        orphans=orphans,
        mismatched=mismatched,
    )


def _number_collisions(entries) -> tuple:
    """Keep each helper's own ``_NN`` index when unique; number the rest after them."""
    ordered = sorted(entries, key=lambda e: e.object_name)
    used = set()
    kept = {}
    for entry in ordered:
        parsed = naming.parse_collision_name(entry.object_name)
        index = parsed[2] if parsed else None
        if index is not None and index not in used:
            kept[entry.object_name] = index
            used.add(index)
    out = []
    next_free = 0
    for entry in ordered:
        index = kept.get(entry.object_name)
        if index is None:
            while next_free in used:
                next_free += 1
            index = next_free
            used.add(index)
        out.append(CollisionEntry(object_name=entry.object_name, shape=entry.shape, index=index))
    return tuple(sorted(out, key=lambda e: (e.index, e.object_name)))


def _role_from_name(ob: ObjectRecord, snapshot: SceneSnapshot, mesh_names: set) -> str:
    if ob.type == "MESH" and naming.parse_collision_name(ob.name) is not None:
        return C.ROLE_COLLISION
    if ob.type == "EMPTY" and ob.name.startswith(C.SOCKET_PREFIX):
        return C.ROLE_SOCKET
    if ob.type == "MESH":
        parsed = naming.parse_lod_name(ob.name)
        if parsed and parsed[1] >= 1 and _lod_owner_name(parsed[0], snapshot, mesh_names):
            return C.ROLE_LOD
    return C.ROLE_NONE


def _lod_owner_name(base: str, snapshot: SceneSnapshot, mesh_names: set) -> str:
    for candidate in (base, naming.lod_object_name(base, 0)):
        if candidate in mesh_names:
            rec = snapshot.object(candidate)
            if rec is not None and rec.role in (C.ROLE_NONE,) and not naming.is_helper_name(candidate):
                return candidate
    return ""


def _owner_from_name(ob: ObjectRecord, role: str, snapshot: SceneSnapshot, mesh_names: set) -> str:
    if role == C.ROLE_COLLISION:
        parsed = naming.parse_collision_name(ob.name)
        if not parsed:
            return ""
        shape, body, _index = parsed
        rest = ob.name[len(C.COLLISION_PREFIXES[shape]):]
        for candidate in (body, rest):
            if candidate in mesh_names and candidate != ob.name:
                return candidate
        return ""
    if role == C.ROLE_SOCKET:
        candidates = [n for n in mesh_names if not naming.is_helper_name(n)]
        parsed = naming.parse_socket_name(ob.name, candidates)
        return parsed[0] if parsed else ""
    if role == C.ROLE_LOD:
        parsed = naming.parse_lod_name(ob.name)
        if parsed and parsed[1] >= 1:
            return _lod_owner_name(parsed[0], snapshot, mesh_names)
    return ""


# ---------------------------------------------------------------- scope


def scope_objects(snapshot: SceneSnapshot, settings: ExportSettings, issues: list) -> tuple:
    """Objects selected by the export scope, sorted by name."""
    names = []
    if settings.scope == C.SCOPE_SELECTED:
        names = [ob.name for ob in snapshot.objects if ob.selected]
    elif settings.scope == C.SCOPE_ACTIVE_COLLECTION:
        if not snapshot.active_collection:
            issues.append(_issue("E_NO_ACTIVE_COLLECTION", C.SEVERITY_ERROR, "There is no active collection to export."))
        else:
            names = list(snapshot.collection_all_objects(snapshot.active_collection))
    elif settings.scope == C.SCOPE_CHOSEN_COLLECTIONS:
        if not settings.chosen_collections:
            issues.append(_issue("E_NO_COLLECTIONS", C.SEVERITY_ERROR, "No collections are chosen for export."))
        for coll in settings.chosen_collections:
            if snapshot.collection(coll) is None:
                issues.append(_issue("E_COLLECTION_MISSING", C.SEVERITY_ERROR,
                                     "Chosen collection '%s' does not exist." % coll, obj=coll))
                continue
            names.extend(snapshot.collection_all_objects(coll))
    out = []
    seen = set()
    for name in sorted(set(names)):
        rec = snapshot.object(name)
        if rec is not None and name not in seen:
            seen.add(name)
            out.append(rec)
    return tuple(out)


def scope_groups(snapshot: SceneSnapshot, settings: ExportSettings, objects: tuple) -> dict:
    """Collection name -> member object names, used for per-collection grouping."""
    groups = defaultdict(list)
    if settings.scope == C.SCOPE_ACTIVE_COLLECTION and snapshot.active_collection:
        groups[snapshot.active_collection] = [ob.name for ob in objects]
    elif settings.scope == C.SCOPE_CHOSEN_COLLECTIONS:
        for coll in settings.chosen_collections:
            if snapshot.collection(coll) is not None:
                groups[coll] = list(snapshot.collection_all_objects(coll))
    else:
        for ob in objects:
            groups[primary_collection(ob)].append(ob.name)
    return {k: tuple(sorted(set(v))) for k, v in groups.items()}


def primary_collection(ob: ObjectRecord) -> str:
    named = sorted(c for c in ob.collections if c != C.MASTER_COLLECTION)
    if named:
        return named[0]
    return C.MASTER_COLLECTION


def collection_folder(snapshot: SceneSnapshot, coll_name: str) -> str:
    """``Props/Kitchen`` style path of a collection below the scene collection."""
    parent_of = {}
    for coll in snapshot.collections:
        for child in coll.children:
            parent_of.setdefault(child, coll.name)
    chain = []
    current = coll_name
    guard = 0
    while current and current != C.MASTER_COLLECTION and guard < 64:
        chain.append(current)
        current = parent_of.get(current, "")
        guard += 1
    return "/".join(reversed(chain))


# ---------------------------------------------------------------- discovery


def discover(snapshot: SceneSnapshot, settings: ExportSettings) -> DiscoveryResult:
    issues = []
    helpers = build_helper_index(snapshot)
    candidates = scope_objects(snapshot, settings, issues)

    roots = []  # ordered unique ObjectRecords after helper resolution
    root_names = set()
    candidate_names = {ob.name for ob in candidates}
    for ob in candidates:
        if not ob.export_enabled:
            issues.append(_issue("I_EXPORT_DISABLED", C.SEVERITY_INFO,
                                 "'%s' has export disabled and is skipped." % ob.name, obj=ob.name))
            continue
        if ob.name in helpers.orphans:
            if ob.role == C.ROLE_COLLISION or naming.parse_collision_name(ob.name):
                issues.append(_issue("E_COLLISION_OWNER_MISSING", C.SEVERITY_ERROR,
                                     "Collision helper '%s' has no render mesh owner; its name must contain the "
                                     "exact render-mesh name (UCX_<Mesh>_NN)." % ob.name, obj=ob.name))
            else:
                issues.append(_issue("W_HELPER_OWNER_MISSING", C.SEVERITY_WARNING,
                                     "Helper '%s' has no owner and is skipped." % ob.name, obj=ob.name))
            continue
        owner_name = helpers.owner_of.get(ob.name)
        if owner_name:
            if owner_name not in candidate_names:
                issues.append(_issue("I_HELPER_RESOLVED", C.SEVERITY_INFO,
                                     "Helper '%s' exports with its owner '%s'." % (ob.name, owner_name), obj=ob.name))
            target = snapshot.object(owner_name)
        else:
            parsed = naming.parse_lod_name(ob.name)
            if ob.type == "MESH" and parsed and parsed[1] >= 1:
                issues.append(_issue("E_LOD_MISSING_LOD0", C.SEVERITY_ERROR,
                                     "'%s' looks like LOD%d but no LOD0 object '%s' or '%s' exists."
                                     % (ob.name, parsed[1], parsed[0], naming.lod_object_name(parsed[0], 0)),
                                     obj=ob.name))
                continue
            target = ob
        if target is not None and target.name not in root_names:
            if not target.export_enabled:
                issues.append(_issue("I_EXPORT_DISABLED", C.SEVERITY_INFO,
                                     "'%s' has export disabled and is skipped." % target.name, obj=target.name))
                continue
            root_names.add(target.name)
            roots.append(target)

    profile = settings.profile
    assets = []
    if profile == C.PROFILE_STATIC_MESH:
        for ob in roots:
            if ob.type == "ARMATURE":
                issues.append(_issue("I_PROFILE_SKIPPED", C.SEVERITY_INFO,
                                     "Armature '%s' is skipped by the Static Mesh profile." % ob.name, obj=ob.name))
    if profile in (C.PROFILE_SKELETAL_MESH, C.PROFILE_ANIMATION):
        for ob in roots:
            if ob.type == "MESH" and not _is_skinned(ob):
                issues.append(_issue("I_PROFILE_SKIPPED", C.SEVERITY_INFO,
                                     "'%s' is not deformed by an armature and is skipped by the %s profile."
                                     % (ob.name, profile.replace("_", " ").title()), obj=ob.name))
    if profile in (C.PROFILE_STATIC_MESH, C.PROFILE_COLLECTION_SCENE):
        assets.extend(_static_assets(snapshot, settings, roots, helpers, issues, include_skinned=profile == C.PROFILE_STATIC_MESH))
    if profile in (C.PROFILE_SKELETAL_MESH, C.PROFILE_COLLECTION_SCENE):
        assets.extend(_skeletal_assets(snapshot, settings, roots, helpers, issues))
    if profile == C.PROFILE_ANIMATION or (profile == C.PROFILE_SKELETAL_MESH and settings.skeletal_include_animations):
        assets.extend(_animation_assets(snapshot, settings, roots, issues))
    if profile not in (C.PROFILE_STATIC_MESH, C.PROFILE_SKELETAL_MESH, C.PROFILE_ANIMATION, C.PROFILE_COLLECTION_SCENE):
        issues.append(_issue("E_PROFILE", C.SEVERITY_ERROR, "Unknown export profile '%s'." % profile))

    assets = list(link_skeleton_assets(tuple(assets)))
    assets.sort(key=lambda a: (a.unreal_path.lower(), a.kind))
    if not assets and not any(i.is_blocking for i in issues):
        issues.append(_issue("E_NO_ASSETS", C.SEVERITY_ERROR,
                             "Nothing to export: the scope contains no objects matching the '%s' profile."
                             % profile.replace("_", " ").title()))
    return DiscoveryResult(assets=tuple(assets), issues=tuple(issues), helpers=helpers)


def _object_id(ob: ObjectRecord) -> str:
    return ob.uuid or "obj:" + ob.name


def _folder_for_object(snapshot, settings, ob: ObjectRecord) -> str:
    if ob.folder_override:
        return naming.sanitize_folder(ob.folder_override, settings.max_name_length)
    if settings.mirror_collections_as_folders:
        return naming.sanitize_folder(collection_folder(snapshot, primary_collection(ob)), settings.max_name_length)
    return ""


def _name(settings, raw: str, prefix: str, obj: str, issues: list, asset_id: str):
    """Sanitize, prefix, then truncate (so the prefix counts toward the length limit)."""
    clean = naming.sanitize_name(raw, 0)
    if not clean.valid:
        issues.append(_issue("E_INVALID_NAME", C.SEVERITY_ERROR,
                             "'%s' does not produce a valid Unreal asset name after sanitization "
                             "(only letters, digits and underscores survive)." % raw, obj=obj, asset=asset_id))
        return "", raw
    full = naming.apply_prefix(clean.value, prefix) if settings.auto_prefix else clean.value
    value = naming.truncate_name(full, settings.max_name_length, raw)
    changed = clean.changed or value != full
    if changed:
        issues.append(_issue("I_NAME_SANITIZED", C.SEVERITY_INFO,
                             "Unreal asset name for '%s' sanitized to '%s'." % (raw, value), obj=obj, asset=asset_id))
    return value, raw if changed else ""


def _is_skinned(ob: ObjectRecord) -> bool:
    return ob.type == "MESH" and bool(ob.armature_targets)


def _static_assets(snapshot, settings, roots, helpers, issues, include_skinned):
    meshes = [ob for ob in roots if ob.type == "MESH" and (include_skinned or not _is_skinned(ob))]
    for ob in roots:
        if ob.type not in ("MESH", "ARMATURE") and ob.name not in helpers.owner_of:
            issues.append(_issue("I_UNSUPPORTED_TYPE", C.SEVERITY_INFO,
                                 "'%s' (%s) is not exportable as a mesh and is skipped." % (ob.name, ob.type.title()),
                                 obj=ob.name))
    if settings.grouping == C.GROUP_PER_COLLECTION:
        return _static_collection_assets(snapshot, settings, meshes, helpers, issues)
    assets = []
    for ob in meshes:
        asset_id = _object_id(ob)
        raw = ob.asset_name_override or naming.asset_base_name(ob.name)
        name, sanitized_from = _name(settings, raw, settings.prefix_static, ob.name, issues, asset_id)
        if not name:
            continue
        folder = _folder_for_object(snapshot, settings, ob)
        lods = helpers.lods.get(ob.name, ())
        assets.append(ExportAsset(
            id=asset_id,
            kind=C.KIND_STATIC_MESH,
            asset_name=name,
            source_name=ob.name,
            unreal_path=naming.build_unreal_path(settings.unreal_root, folder, name),
            file_relpath=naming.file_relpath(folder, name),
            origin_object=ob.name if settings.origin_mode == C.ORIGIN_OBJECT else "",
            mesh_objects=(ob.name,),
            lods=lods,
            collisions=helpers.collisions.get(ob.name, ()),
            sockets=helpers.sockets.get(ob.name, ()),
            source_object_ids=_ids(snapshot, [ob.name] + _helper_names(helpers, ob.name)),
            collection=primary_collection(ob),
            sanitized_from=sanitized_from,
        ))
    return assets


def _helper_names(helpers: HelperIndex, owner: str) -> list:
    names = [c.object_name for c in helpers.collisions.get(owner, ())]
    names += [s.object_name for s in helpers.sockets.get(owner, ())]
    names += [lod.object_name for lod in helpers.lods.get(owner, ())]
    return names


def _ids(snapshot: SceneSnapshot, names) -> tuple:
    out = []
    for name in sorted(set(names)):
        rec = snapshot.object(name)
        if rec is not None:
            out.append(_object_id(rec))
    return tuple(out)


def _static_collection_assets(snapshot, settings, meshes, helpers, issues):
    mesh_names = {ob.name for ob in meshes}
    groups = scope_groups(snapshot, settings, tuple(meshes))
    assets = []
    for coll_name, members in sorted(groups.items()):
        member_meshes = [n for n in members if n in mesh_names]
        if not member_meshes:
            continue
        coll = snapshot.collection(coll_name)
        is_master = coll_name == C.MASTER_COLLECTION or coll is None
        asset_id = (coll.uuid if coll is not None and coll.uuid else "coll:" + coll_name)
        raw = (coll.asset_name_override if coll is not None and coll.asset_name_override else
               (snapshot.scene_name if is_master else coll_name))
        name, sanitized_from = _name(settings, raw, settings.prefix_static, coll_name, issues, asset_id)
        if not name:
            continue
        if coll is not None and coll.folder_override:
            folder = naming.sanitize_folder(coll.folder_override, settings.max_name_length)
        elif settings.mirror_collections_as_folders and not is_master:
            parent_folder = collection_folder(snapshot, coll_name).rpartition("/")[0]
            folder = naming.sanitize_folder(parent_folder, settings.max_name_length)
        else:
            folder = ""
        collisions = []
        sockets = []
        for member in member_meshes:
            collisions.extend(helpers.collisions.get(member, ()))
            sockets.extend(helpers.sockets.get(member, ()))
            if helpers.lods.get(member):
                issues.append(_issue("W_LOD_IGNORED_IN_COLLECTION", C.SEVERITY_WARNING,
                                     "LODs of '%s' are not exported when meshes are combined per collection." % member,
                                     obj=member, asset=asset_id))
        collisions = tuple(sorted(collisions, key=lambda e: e.object_name))
        offset = coll.instance_offset if (coll is not None and settings.origin_mode == C.ORIGIN_OBJECT) else (0.0, 0.0, 0.0)
        helper_names = []
        for member in member_meshes:
            helper_names.extend(_helper_names(helpers, member))
        assets.append(ExportAsset(
            id=asset_id,
            kind=C.KIND_STATIC_MESH,
            asset_name=name,
            source_name=coll_name,
            unreal_path=naming.build_unreal_path(settings.unreal_root, folder, name),
            file_relpath=naming.file_relpath(folder, name),
            origin_object="",
            origin_offset=tuple(offset),
            mesh_objects=tuple(member_meshes),
            collisions=collisions,
            sockets=tuple(sorted(sockets, key=lambda e: e.object_name)),
            source_object_ids=_ids(snapshot, list(member_meshes) + helper_names),
            collection=coll_name,
            sanitized_from=sanitized_from,
        ))
    return assets


def _armatures_for_roots(snapshot, roots, issues) -> list:
    """Armature records referenced by the roots (armatures directly or via skinned meshes)."""
    out = []
    seen = set()
    for ob in roots:
        names = []
        if ob.type == "ARMATURE":
            names = [ob.name]
        elif _is_skinned(ob):
            names = list(ob.armature_targets)
            if len(names) > 1:
                issues.append(_issue("E_MULTIPLE_ARMATURES", C.SEVERITY_ERROR,
                                     "'%s' is deformed by several armatures (%s); a skeletal asset needs exactly "
                                     "one root armature." % (ob.name, ", ".join(names)), obj=ob.name))
                continue
        for name in names:
            rec = snapshot.object(name)
            if rec is None or rec.type != "ARMATURE":
                issues.append(_issue("E_MISSING_ARMATURE", C.SEVERITY_ERROR,
                                     "'%s' references armature '%s', which does not exist." % (ob.name, name),
                                     obj=ob.name))
                continue
            if name not in seen:
                seen.add(name)
                out.append(rec)
    return out


def skinned_meshes_of(snapshot: SceneSnapshot, armature_name: str, helpers: HelperIndex) -> tuple:
    """Render meshes deformed by ``armature_name`` (LOD helpers excluded)."""
    out = []
    for ob in snapshot.objects:
        if ob.type != "MESH" or not ob.export_enabled:
            continue
        if armature_name in ob.armature_targets and ob.name not in helpers.owner_of:
            out.append(ob.name)
    return tuple(sorted(out))


def skeletal_asset_name(settings, arm: ObjectRecord, issues: list):
    raw = arm.asset_name_override or arm.name
    return _name(settings, raw, settings.prefix_skeletal, arm.name, issues, _object_id(arm))


def _skeletal_assets(snapshot, settings, roots, helpers, issues):
    assets = []
    for arm in _armatures_for_roots(snapshot, roots, issues):
        asset_id = _object_id(arm)
        name, sanitized_from = skeletal_asset_name(settings, arm, issues)
        if not name:
            continue
        meshes = skinned_meshes_of(snapshot, arm.name, helpers)
        for mesh_name in meshes:
            rec = snapshot.object(mesh_name)
            if rec is not None and len(rec.armature_targets) > 1:
                issues.append(_issue("E_MULTIPLE_ARMATURES", C.SEVERITY_ERROR,
                                     "'%s' is deformed by several armatures (%s)." % (mesh_name, ", ".join(rec.armature_targets)),
                                     obj=mesh_name, asset=asset_id))
        if not meshes:
            issues.append(_issue("E_MISSING_DATA", C.SEVERITY_ERROR,
                                 "Armature '%s' deforms no mesh, so there is no skeletal mesh to export." % arm.name,
                                 obj=arm.name, asset=asset_id))
            continue
        lods = ()
        if len(meshes) == 1:
            lods = helpers.lods.get(meshes[0], ())
        else:
            for mesh_name in meshes:
                if helpers.lods.get(mesh_name):
                    issues.append(_issue("W_LOD_IGNORED_MULTI_MESH", C.SEVERITY_WARNING,
                                         "LODs of '%s' are ignored: skeletal LODs need a single render mesh." % mesh_name,
                                         obj=mesh_name, asset=asset_id))
        folder = _folder_for_object(snapshot, settings, arm)
        unreal_path = naming.build_unreal_path(settings.unreal_root, folder, name)
        helper_names = []
        for mesh_name in meshes:
            helper_names.extend(_helper_names(helpers, mesh_name))
        assets.append(ExportAsset(
            id=asset_id,
            kind=C.KIND_SKELETAL_MESH,
            asset_name=name,
            source_name=arm.name,
            unreal_path=unreal_path,
            file_relpath=naming.file_relpath(folder, name),
            origin_object=arm.name if settings.origin_mode == C.ORIGIN_OBJECT else "",
            mesh_objects=meshes,
            lods=lods,
            armature=arm.name,
            skeleton_path=arm.skeleton_path_override or default_skeleton_path(unreal_path),
            source_object_ids=_ids(snapshot, [arm.name] + list(meshes) + helper_names),
            collection=primary_collection(arm),
            sanitized_from=sanitized_from,
        ))
    return assets


def default_skeleton_path(skeletal_unreal_path: str) -> str:
    """Unreal names the skeleton of an imported skeletal mesh ``<Mesh>_Skeleton``."""
    return skeletal_unreal_path + "_Skeleton"


def compatible_actions(snapshot: SceneSnapshot, arm: ObjectRecord) -> tuple:
    bone_names = {b.name for b in arm.bones}
    out = []
    for act in snapshot.actions:
        if not act.has_object_slot:
            continue
        if act.bone_names and not (set(act.bone_names) & bone_names):
            continue
        out.append(act.name)
    return tuple(sorted(out))


def _animation_assets(snapshot, settings, roots, issues):
    assets = []
    for arm in _armatures_for_roots(snapshot, roots, issues):
        arm_id = _object_id(arm)
        compatible = compatible_actions(snapshot, arm)
        if settings.actions:
            wanted = [a for a in settings.actions if a in compatible]
            for missing in sorted(set(settings.actions) - set(compatible)):
                if snapshot.action(missing) is None:
                    issues.append(_issue("W_ACTION_MISSING", C.SEVERITY_WARNING,
                                         "Chosen action '%s' does not exist." % missing, obj=arm.name))
                else:
                    issues.append(_issue("I_ACTION_INCOMPATIBLE", C.SEVERITY_INFO,
                                         "Action '%s' does not animate bones of '%s' and is skipped." % (missing, arm.name),
                                         obj=arm.name))
        elif arm.active_action:
            wanted = [arm.active_action]
        else:
            issues.append(_issue("E_NO_ACTION", C.SEVERITY_ERROR,
                                 "Armature '%s' has no active action and no actions are chosen." % arm.name, obj=arm.name))
            continue
        sk_name, _ = skeletal_asset_name(settings, arm, [])
        folder = _folder_for_object(snapshot, settings, arm)
        if arm.skeleton_path_override:
            skeleton_path = arm.skeleton_path_override
        elif sk_name:
            skeleton_path = default_skeleton_path(naming.build_unreal_path(settings.unreal_root, folder, sk_name))
        else:
            skeleton_path = ""
        for action_name in sorted(set(wanted)):
            act = snapshot.action(action_name)
            if act is None:
                continue
            raw = ("%s_%s" % (arm.name, action_name)) if settings.animation_name_includes_armature else action_name
            act_id = act.uuid or "act:" + act.name
            asset_id = "%s+%s" % (arm_id, act_id)
            name, sanitized_from = _name(settings, raw, settings.prefix_animation, arm.name, issues, asset_id)
            if not name:
                continue
            start, end = _frame_range(snapshot, settings, act)
            assets.append(ExportAsset(
                id=asset_id,
                kind=C.KIND_ANIMATION,
                asset_name=name,
                source_name=action_name,
                unreal_path=naming.build_unreal_path(settings.unreal_root, folder, name),
                file_relpath=naming.file_relpath(folder, name),
                origin_object=arm.name if settings.origin_mode == C.ORIGIN_OBJECT else "",
                armature=arm.name,
                action=action_name,
                skeleton_path=skeleton_path,
                frame_start=start,
                frame_end=end,
                source_object_ids=(arm_id,),
                collection=primary_collection(arm),
                sanitized_from=sanitized_from,
            ))
    return assets


def _frame_range(snapshot, settings, act) -> tuple:
    if settings.frame_range_mode == C.FRAME_RANGE_SCENE:
        return float(snapshot.frame_start), float(snapshot.frame_end)
    if settings.frame_range_mode == C.FRAME_RANGE_CUSTOM:
        return float(settings.custom_frame_start), float(settings.custom_frame_end)
    return float(act.frame_start), float(act.frame_end)


def link_skeleton_assets(assets: tuple) -> tuple:
    """Point animation assets at skeletal assets of the same armature in this plan."""
    by_armature = {a.armature: a for a in assets if a.kind == C.KIND_SKELETAL_MESH}
    out = []
    for asset in assets:
        if asset.kind == C.KIND_ANIMATION and asset.armature in by_armature:
            sk = by_armature[asset.armature]
            asset = _replace(asset, skeleton_asset_id=sk.id, skeleton_path=sk.skeleton_path)
        out.append(asset)
    return tuple(out)


def _replace(asset: ExportAsset, **changes) -> ExportAsset:
    from dataclasses import replace

    return replace(asset, **changes)
