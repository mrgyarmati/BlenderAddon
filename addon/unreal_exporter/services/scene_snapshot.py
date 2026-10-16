"""Adapter: live Blender data -> immutable domain records.

``take_snapshot`` is cheap (no geometry); ``measure`` adds :class:`MeshStats`
only for objects that belong to discovered assets.
"""

import os
import re
from dataclasses import replace

import bpy

from .. import constants as C
from ..domain.models import (
    ActionRecord,
    BoneRecord,
    CollectionRecord,
    ExportSettings,
    ModifierRecord,
    ObjectRecord,
    SceneSnapshot,
)
from ..domain.validation import ValidationEnv
from ..preferences import get_prefs
from . import mesh_stats

_BONE_PATH = re.compile(r'pose\.bones\["((?:[^"\\]|\\.)*)"\]')
_OBJECT_TRANSFORM_PATHS = {
    "location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale",
    "delta_location", "delta_rotation_euler", "delta_rotation_quaternion", "delta_scale",
}


# ---------------------------------------------------------------- settings


def resolve_export_root(raw: str):
    """Absolute export directory and a reason when it cannot be resolved."""
    raw = (raw or "").strip()
    if not raw:
        return "", "No export folder is set."
    if raw.startswith("//") and not bpy.data.filepath:
        return "", ("The export folder '%s' is relative to the .blend file; save the file first or choose an "
                    "absolute folder." % raw)
    return os.path.normpath(bpy.path.abspath(raw)), ""


def check_writable(path: str):
    if not path:
        return False, "no folder"
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if os.path.isfile(path):
        return False, "a file exists at the export folder path"
    if not probe or not os.path.isdir(probe):
        return False, "no existing parent folder"
    if not os.access(probe, os.W_OK):
        return False, "'%s' is read-only" % os.path.basename(probe)
    return True, ""


def build_settings(context, destination=None):
    """Scene settings + preferences -> (ExportSettings, ValidationEnv)."""
    s = getattr(context.scene, C.PROP_ATTR)
    prefs = get_prefs(context)
    root, reason = resolve_export_root(s.export_dir)
    permitted = tuple(os.path.normpath(bpy.path.abspath(p.strip()))
                      for p in prefs.permitted_roots.split(";") if p.strip())
    writable, why = check_writable(root) if root else (True, "")
    settings = ExportSettings(
        profile=s.profile,
        scope=s.scope,
        grouping=s.grouping,
        chosen_collections=tuple(ref.collection.name for ref in s.chosen_collections if ref.collection),
        export_root=root,
        permitted_roots=permitted,
        unreal_root=s.unreal_root,
        mirror_collections_as_folders=s.mirror_collections_as_folders,
        auto_prefix=s.auto_prefix,
        prefix_static=s.prefix_static,
        prefix_skeletal=s.prefix_skeletal,
        prefix_animation=s.prefix_animation,
        origin_mode=s.origin_mode,
        triangulate=s.triangulate,
        export_tangents=s.export_tangents,
        smoothing=s.smoothing,
        export_vertex_colors=s.export_vertex_colors,
        export_morph_targets=s.export_morph_targets,
        deform_bones_only=s.deform_bones_only,
        primary_bone_axis=s.primary_bone_axis,
        secondary_bone_axis=s.secondary_bone_axis,
        one_convex_hull_per_ucx=s.one_convex_hull_per_ucx,
        auto_generate_collision=s.auto_generate_collision,
        lod_collision_naming=s.lod_collision_naming,
        max_material_slots=s.max_material_slots,
        max_bone_influences=s.max_bone_influences,
        socket_distance_tolerance=s.socket_distance_tolerance,
        actions=tuple(ref.action.name for ref in s.actions if ref.action and ref.export),
        animation_name_includes_armature=s.animation_name_includes_armature,
        skeletal_include_animations=s.skeletal_include_animations,
        frame_range_mode=s.frame_range_mode,
        custom_frame_start=s.custom_frame_start,
        custom_frame_end=s.custom_frame_end,
        sample_step=s.sample_step,
        simplify=s.simplify,
        root_motion=s.root_motion,
        nla_policy=s.nla_policy,
        import_materials=s.import_materials,
        import_textures=s.import_textures,
        build_nanite=s.build_nanite,
        generate_lightmap_uvs=s.generate_lightmap_uvs,
        create_physics_asset=s.create_physics_asset,
        reimport_policy=s.reimport_policy,
        destination=destination or s.destination,
        developer_mode=prefs.developer_mode,
        debug_paths=prefs.debug_paths,
    )
    env = ValidationEnv(export_root_writable=writable, export_root_reason=reason or why)
    return settings, env


# ---------------------------------------------------------------- snapshot


def _matrix16(matrix) -> tuple:
    return tuple(float(v) for row in matrix for v in row)


def action_fcurves(action, slot=None):
    """F-curves of a (slotted) action, optionally limited to one slot."""
    for layer in getattr(action, "layers", ()):
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue
            if slot is not None:
                bag = strip.channelbag(slot)
                if bag is not None:
                    yield from bag.fcurves
                continue
            for bag in strip.channelbags:
                yield from bag.fcurves


def _object_transform_animated(ob) -> bool:
    adt = ob.animation_data
    if adt is None or adt.action is None:
        return False
    slot = getattr(adt, "action_slot", None)
    for fcurve in action_fcurves(adt.action, slot):
        if fcurve.data_path in _OBJECT_TRANSFORM_PATHS:
            return True
    return False


def _object_collections(ob, scene, scene_collections: set) -> tuple:
    names = [coll.name for coll in ob.users_collection if coll.name in scene_collections]
    if ob.name in scene.collection.objects:
        names.append(C.MASTER_COLLECTION)
    return tuple(sorted(set(names)))


def _object_record(ob, scene, view_layer, scene_collections) -> ObjectRecord:
    p = getattr(ob, C.PROP_ATTR)
    loc, rot, scale = ob.matrix_world.decompose()
    modifiers = []
    for mod in ob.modifiers:
        target = ""
        if mod.type == "ARMATURE" and mod.object is not None:
            target = mod.object.name
        modifiers.append(ModifierRecord(name=mod.name, type=mod.type, enabled=mod.show_viewport, target=target))
    bones = ()
    if ob.type == "ARMATURE":
        bones = tuple(BoneRecord(name=b.name, parent=b.parent.name if b.parent else "", use_deform=b.use_deform)
                      for b in ob.data.bones)
    try:
        selected = ob.select_get(view_layer=view_layer)
    except RuntimeError:
        selected = False
    adt = ob.animation_data
    return ObjectRecord(
        name=ob.name,
        type=ob.type,
        uuid=p.uuid,
        data_name=ob.data.name if ob.data is not None else "",
        parent=ob.parent.name if ob.parent else "",
        parent_type=ob.parent_type,
        collections=_object_collections(ob, scene, scene_collections),
        matrix_world=_matrix16(ob.matrix_world),
        location=tuple(loc),
        rotation_quaternion=tuple(rot),
        scale=tuple(scale),
        selected=selected,
        visible=ob.visible_get(view_layer=view_layer) if ob.name in view_layer.objects else False,
        role=p.role,
        owner_uuid=p.owner_uuid,
        collision_shape=p.collision_shape if p.role == C.ROLE_COLLISION else "",
        lod_index=p.lod_index if p.role == C.ROLE_LOD else -1,
        lod_generated=p.lod_generated,
        socket_name=p.socket_name if p.role == C.ROLE_SOCKET else "",
        export_enabled=p.export_enabled,
        asset_name_override=p.asset_name_override.strip(),
        folder_override=p.folder_override.strip(),
        skeleton_path_override=p.skeleton_path_override.strip(),
        modifiers=tuple(modifiers),
        bones=bones,
        is_animated=_object_transform_animated(ob),
        active_action=adt.action.name if adt is not None and adt.action is not None else "",
        empty_display_size=ob.empty_display_size if ob.type == "EMPTY" else 1.0,
    )


def _walk_collections(root):
    stack = list(root.children)
    seen = set()
    while stack:
        coll = stack.pop()
        if coll.name in seen:
            continue
        seen.add(coll.name)
        yield coll
        stack.extend(coll.children)


def _action_record(action) -> ActionRecord:
    bones = set()
    for fcurve in action_fcurves(action):
        match = _BONE_PATH.match(fcurve.data_path)
        if match:
            bones.add(match.group(1).replace('\\"', '"'))
    start, end = action.frame_range
    slots = getattr(action, "slots", ())
    has_object_slot = (not slots) or any(slot.target_id_type in ("OBJECT", "UNSPECIFIED") for slot in slots)
    return ActionRecord(
        name=action.name,
        uuid=getattr(action, C.PROP_ATTR).uuid,
        frame_start=float(start),
        frame_end=float(end),
        bone_names=tuple(sorted(bones)),
        has_object_slot=has_object_slot,
    )


def take_snapshot(context) -> SceneSnapshot:
    scene = context.scene
    view_layer = context.view_layer
    collections = list(_walk_collections(scene.collection))
    scene_collections = {coll.name for coll in collections}

    objects = []
    for ob in scene.objects:
        if getattr(ob, C.PROP_ATTR).is_preview:
            continue
        objects.append(_object_record(ob, scene, view_layer, scene_collections))
    names = {ob.name for ob in objects}

    def members(coll):
        return tuple(sorted(ob.name for ob in coll.objects if ob.name in names))

    coll_records = [CollectionRecord(
        name=C.MASTER_COLLECTION,
        objects=members(scene.collection),
        children=tuple(sorted(c.name for c in scene.collection.children)),
    )]
    for coll in sorted(collections, key=lambda c: c.name):
        p = getattr(coll, C.PROP_ATTR)
        coll_records.append(CollectionRecord(
            name=coll.name,
            uuid=p.uuid,
            objects=members(coll),
            children=tuple(sorted(c.name for c in coll.children)),
            instance_offset=tuple(coll.instance_offset),
            asset_name_override=p.asset_name_override.strip(),
            folder_override=p.folder_override.strip(),
        ))

    active_layer = view_layer.active_layer_collection
    active_collection = ""
    if active_layer is not None:
        active_collection = (C.MASTER_COLLECTION if active_layer.collection == scene.collection
                             else active_layer.collection.name)
    active = view_layer.objects.active
    return SceneSnapshot(
        scene_name=scene.name,
        blender_version=bpy.app.version_string,
        blend_path=os.path.basename(bpy.data.filepath),
        unit_system=scene.unit_settings.system,
        unit_scale=scene.unit_settings.scale_length,
        fps=scene.render.fps / (scene.render.fps_base or 1.0),
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        objects=tuple(sorted(objects, key=lambda o: o.name)),
        collections=tuple(coll_records),
        actions=tuple(_action_record(a) for a in sorted(bpy.data.actions, key=lambda a: a.name)
                      if a.library is None),
        active_collection=active_collection,
        active_object=active.name if active else "",
    )


def measure(snapshot: SceneSnapshot, assets, context) -> SceneSnapshot:
    """Return a snapshot whose asset objects carry :class:`MeshStats`.

    Objects are measured through evaluation copies so hidden helpers (generated
    LODs, collisions) report their evaluated geometry too.
    """
    from .staging import EvaluationScene

    wanted = {}  # name -> (collision?, deform bone names or None)
    for asset in assets:
        deform = None
        if asset.armature:
            arm = snapshot.object(asset.armature)
            if arm is not None:
                deform = {b.name for b in arm.bones if b.use_deform}
        for name in asset.mesh_objects:
            wanted[name] = (False, deform if asset.kind == C.KIND_SKELETAL_MESH else None)
        for lod in asset.lods:
            wanted[lod.object_name] = (False, deform if asset.kind == C.KIND_SKELETAL_MESH else None)
        for col in asset.collisions:
            wanted[col.object_name] = (True, None)
    sources = [bpy.data.objects[name] for name in sorted(wanted)
               if name in bpy.data.objects and bpy.data.objects[name].type == "MESH"]
    if not sources:
        return snapshot
    stats = {}
    with EvaluationScene(context, sources) as evaluation:
        for ob in sources:
            collision, deform = wanted[ob.name]
            stats[ob.name] = mesh_stats.compute(evaluation.copy_of(ob), evaluation.depsgraph,
                                                collision=collision, deform_bone_names=deform)
    records = tuple(replace(r, mesh=stats[r.name]) if r.name in stats else r for r in snapshot.objects)
    return replace(snapshot, objects=records)
