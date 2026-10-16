"""Animation staging: sample the source rig, bake keys onto a staged armature.

An evaluation copy of the source armature (constraints, drivers and IK
included) is sampled inside the staging scene, so the user's frame, NLA and
action assignment are never touched. Sampled armature-space bone matrices are
mapped into the staged centimetre armature and converted back to local
(basis) keys under full inheritance, which the FBX exporter then bakes.
"""

import math

import bpy
import numpy as np
from mathutils import Matrix

from .. import constants as C
from . import staging


def frame_samples(start: float, end: float, step: float) -> list:
    """Sample times from ``start`` to ``end`` inclusive, ``step`` frames apart."""
    if step <= 0:
        raise ValueError("sample step must be positive")
    count = int(math.floor((end - start) / step + 1e-6))
    frames = [start + i * step for i in range(max(count, 0) + 1)]
    if end - frames[-1] > 1e-6:
        frames.append(end)
    return frames


def assign_slot(adt, slot):
    """Assign ``slot`` only when it differs from the current one.

    Blender 5.2.0 crashes (null read in foreach_action_slot_use_with_references)
    when the slot that ``AnimData.action = ...`` already auto-assigned is assigned
    again; see docs/compatibility.md.
    """
    if slot is not None and adt.action_slot != slot:
        adt.action_slot = slot


def choose_slot(action, source=None):
    """Slot of ``action`` an object should use (its current one, else the first object slot)."""
    slots = list(getattr(action, "slots", ()))
    if not slots:
        return None
    adt = source.animation_data if source is not None else None
    if adt is not None and adt.action == action and adt.action_slot is not None:
        return adt.action_slot
    for slot in slots:
        if slot.target_id_type == "OBJECT":
            return slot
    return slots[0]


def _remap_self_references(copy, source):
    """Point the copy's drivers and constraints at itself instead of the source rig."""
    adt = copy.animation_data
    if adt is not None:
        for fcurve in adt.drivers:
            for variable in fcurve.driver.variables:
                for target in variable.targets:
                    if target.id_type == "OBJECT" and target.id == source:
                        target.id = copy
    constraint_lists = [copy.constraints] + [pb.constraints for pb in copy.pose.bones]
    for constraints in constraint_lists:
        for con in constraints:
            for attr in ("target", "pole_target"):
                if getattr(con, attr, None) == source:
                    setattr(con, attr, copy)
            for target in getattr(con, "targets", ()):
                if getattr(target, "target", None) == source:
                    target.target = copy


class PoseSampler:
    def __init__(self, session, source, action, nla_policy):
        self.session = session
        self.copy = source.copy()
        self.copy.name = "__uex_sampler"
        session.track_object(self.copy)
        self.copy.hide_viewport = False
        _remap_self_references(self.copy, source)
        if nla_policy == C.NLA_ACTION_ONLY:
            adt = self.copy.animation_data or self.copy.animation_data_create()
            for track in list(adt.nla_tracks):
                adt.nla_tracks.remove(track)
            adt.action = action
            assign_slot(adt, choose_slot(action, source))
            adt.action_influence = 1.0
            adt.action_blend_type = "REPLACE"
            adt.action_extrapolation = "HOLD"
        # Rebuild depsgraph relations for the new copy; frame_set alone does not.
        session.depsgraph()

    def sample(self, frames) -> list:
        scene = self.session.scene
        out = []
        for frame in frames:
            whole = math.floor(frame)
            scene.frame_set(int(whole), subframe=frame - whole)
            evaluated = self.copy.evaluated_get(self.session.view_layer.depsgraph)
            matrices = {pb.name: pb.matrix.copy() for pb in evaluated.pose.bones}
            out.append((frame, evaluated.matrix_world.copy(), matrices))
        return out

    def close(self):
        try:
            bpy.data.objects.remove(self.copy)
        except ReferenceError:
            pass


def bake_keys(arm_data, samples, mappings, root_motion) -> dict:
    """Bone name -> (locations, quaternions, scales) in the staged armature."""
    rest = {b.name: b.matrix_local.copy() for b in arm_data.bones}
    parent = {b.name: (b.parent.name if b.parent else "") for b in arm_data.bones}
    local_rest_inv = {}
    for name, matrix in rest.items():
        p = parent[name]
        local = (rest[p].inverted() @ matrix) if p else matrix
        local_rest_inv[name] = local.inverted()
    roots = [name for name, p in parent.items() if not p]
    keys = {name: ([], [], []) for name in rest}
    previous = {}
    anchor = {}
    for (_frame, _world, matrices), mapping in zip(samples, mappings):
        scale = abs(mapping.to_3x3().determinant()) ** (1.0 / 3.0) or 1.0
        unscale = Matrix.Scale(1.0 / scale, 4)
        posed = {name: mapping @ matrices[name] @ unscale for name in rest if name in matrices}
        if root_motion == C.ROOT_MOTION_IN_PLACE:
            for name in roots:
                if name not in posed:
                    continue
                translation = posed[name].translation
                if name not in anchor:
                    anchor[name] = (translation.x, translation.y)
                translation.x, translation.y = anchor[name]
                posed[name].translation = translation
        for name in rest:
            if name not in posed:
                continue
            p = parent[name]
            relative = (posed[p].inverted() @ posed[name]) if p and p in posed else posed[name]
            basis = local_rest_inv[name] @ relative
            location, rotation, scale_vec = basis.decompose()
            last = previous.get(name)
            if last is not None and last.dot(rotation) < 0.0:
                rotation.negate()
            previous[name] = rotation
            locs, quats, scales = keys[name]
            locs.append(tuple(location))
            quats.append(tuple(rotation))
            scales.append(tuple(scale_vec))
    return keys


def write_action(session, arm_obj, frames, keys, name):
    action = bpy.data.actions.new("__uex_action")
    session.adopt("actions", action, name)
    slot = action.slots.new(id_type="OBJECT", name=arm_obj.name)
    adt = arm_obj.animation_data_create()
    adt.action = action
    assign_slot(adt, slot)
    times = np.array(frames, dtype=np.float64)
    for bone_name, (locs, quats, scales) in keys.items():
        pose_bone = arm_obj.pose.bones.get(bone_name)
        if pose_bone is None or not locs:
            continue
        pose_bone.rotation_mode = "QUATERNION"
        escaped = bpy.utils.escape_identifier(bone_name)
        for prop, values, width in (("location", locs, 3), ("rotation_quaternion", quats, 4), ("scale", scales, 3)):
            data = np.array(values, dtype=np.float64).reshape((-1, width))
            path = 'pose.bones["%s"].%s' % (escaped, prop)
            for index in range(width):
                fcurve = action.fcurve_ensure_for_datablock(arm_obj, path, index=index, group_name=bone_name)
                points = fcurve.keyframe_points
                points.add(len(times))
                co = np.empty(len(times) * 2, dtype=np.float64)
                co[0::2] = times
                co[1::2] = data[:, index]
                points.foreach_set("co", co)
                fcurve.update()
    return action


def stage_animation(session, asset, settings) -> "staging.StagedAsset":
    staged = staging.StagedAsset(session, asset)
    source = bpy.data.objects[asset.armature]
    action = bpy.data.actions[asset.action]
    scene = session.scene
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    frames = frame_samples(asset.frame_start, asset.frame_end, settings.sample_step)

    sampler = PoseSampler(session, source, action, settings.nla_policy)
    try:
        samples = sampler.sample(frames)
    finally:
        sampler.close()

    first_world = samples[0][1]
    pivot = Matrix.Translation(first_world.translation) if asset.origin_object else Matrix.Identity(4)
    to_staged = Matrix.Scale(session.cm_per_unit, 4) @ pivot.inverted()
    rest_mapping = to_staged @ first_world
    arm = staging.staged_armature(session, source, rest_mapping, normalize_inheritance=True)
    arm.data.pose_position = "POSE"
    session.depsgraph()  # a new armature object has no pose until it is evaluated once
    if settings.root_motion == C.ROOT_MOTION_OBJECT_TO_ROOT:
        mappings = [to_staged @ world for _frame, world, _m in samples]
    else:
        mappings = [rest_mapping] * len(samples)
    keys = bake_keys(arm.data, samples, mappings, settings.root_motion)
    # Keys start at time zero in the FBX (source frame_start -> FBX time 0) so the
    # Unreal sequence never depends on how a non-zero take start is interpreted.
    local_frames = [frame - frames[0] for frame in frames]
    write_action(session, arm, local_frames, keys, asset.asset_name)

    scene.frame_start = 0
    scene.frame_end = max(int(math.ceil(local_frames[-1] - 1e-6)), 0)
    scene.frame_set(0)
    staged.extras = {
        "animation": {
            "fps": round(fps, 6),
            "frame_start": asset.frame_start,
            "frame_end": asset.frame_end,
            "expected_length_seconds": round((asset.frame_end - asset.frame_start) / fps, 6) if fps else 0.0,
            "samples": len(frames),
            "bones": len(keys),
        },
        "triangles": 0,
        "material_slots": [],
    }
    return staged
