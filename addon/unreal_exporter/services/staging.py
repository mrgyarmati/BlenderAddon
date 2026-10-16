"""Stage export copies in a temporary scene, in centimetre space.

Source objects are never modified. Each asset is rebuilt from evaluated copies
inside a temporary scene whose unit scale is 0.01 (1 unit = 1 cm), with all
geometry scaled by ``cm_per_unit``; the FBX then carries no node scaling, which
is what keeps Unreal skeletons and sockets at scale 1 (docs/compatibility.md).

FBX node names come from object names, and object names are unique per .blend
file. :class:`NameJournal` temporarily renames source datablocks that hold a
name a staged copy needs and restores every rename on cleanup, success or not.
"""

import hashlib
import json
import math

import bpy
import numpy as np
from mathutils import Matrix

from .. import constants as C
from ..domain import naming, planning
from ..domain.unreal_math import rotation_to_unreal_rotator

STAGE_SCENE_NAME = "__uex_stage"
STAGE_COLLECTION_NAME = "__uex_export"
TEMP_SUFFIX = ".uexsrc"

# Unreal turns an FBX null by -90 degrees about its local X axis when it becomes
# a socket (measured in UE 5.6.1 and 5.8.3); staged sockets pre-rotate +90.
SOCKET_COMPENSATION = Matrix.Rotation(math.radians(90.0), 4, "X")


class StagingError(RuntimeError):
    pass


class NameJournal:
    """Free ID names for staged copies; restore the originals in reverse order."""

    def __init__(self):
        self._moves = []  # (holder ID, original name, temporary name)
        self.staged_uids = set()

    @staticmethod
    def _temp_name(id_collection, wanted):
        base = wanted[:48]
        for index in range(1, 10000):
            candidate = "%s%s%03d" % (base, TEMP_SUFFIX, index)
            if id_collection.get((candidate, None)) is None:
                return candidate
        raise StagingError("No temporary name available for '%s'." % wanted)

    def claim(self, id_collection, wanted: str, new_id) -> None:
        holder = id_collection.get((wanted, None))
        if holder is not None and holder != new_id:
            if holder.session_uid in self.staged_uids:
                raise StagingError("Two staged datablocks need the name '%s'." % wanted)
            temp = self._temp_name(id_collection, wanted)
            holder.name = temp
            if holder.name != temp:
                raise StagingError("Could not move '%s' aside for export." % wanted)
            self._moves.append((holder, wanted, temp))
        new_id.name = wanted
        if new_id.name != wanted:
            raise StagingError("Could not give the staged copy the name '%s'." % wanted)

    @property
    def moved(self) -> list:
        return [(original, temp) for _holder, original, temp in self._moves]

    def restore(self) -> list:
        errors = []
        while self._moves:
            holder, original, temp = self._moves.pop()
            try:
                holder.name = original
                if holder.name != original:
                    errors.append("'%s' could not be renamed back to '%s' (now '%s')." % (temp, original, holder.name))
            except ReferenceError:
                errors.append("'%s' disappeared before its name could be restored." % original)
        return errors


class StagingSession:
    """Temporary scene + export collection; tracks every datablock it creates."""

    def __init__(self, source_scene):
        self.source_scene = source_scene
        self.journal = NameJournal()
        self._ids = []  # (bpy.data attribute, ID) in creation order
        self.cm_per_unit = planning.cm_per_unit(source_scene.unit_settings.scale_length)
        self.scene = bpy.data.scenes.new(STAGE_SCENE_NAME)
        self._track("scenes", self.scene)
        units = self.scene.unit_settings
        units.system = "METRIC"
        units.scale_length = 0.01
        units.length_unit = "CENTIMETERS"
        self.scene.render.fps = source_scene.render.fps
        self.scene.render.fps_base = source_scene.render.fps_base
        # Shape-key and time-dependent evaluation must match what the user sees.
        self.scene.frame_current = source_scene.frame_current
        self.collection = bpy.data.collections.new(STAGE_COLLECTION_NAME)
        self._track("collections", self.collection)
        self.scene.collection.children.link(self.collection)
        self.view_layer = self.scene.view_layers[0]

    # -- bookkeeping

    def _track(self, attr, id_block):
        self._ids.append((attr, id_block))
        self.journal.staged_uids.add(id_block.session_uid)
        return id_block

    def adopt(self, attr, id_block, name):
        self._track(attr, id_block)
        self.journal.claim(getattr(bpy.data, attr), name, id_block)
        return id_block

    def new_object(self, name, data=None, parent=None, link=True):
        ob = bpy.data.objects.new("__uex_tmp_object", data)
        self.adopt("objects", ob, name)
        if link:
            self.collection.objects.link(ob)
        else:
            self.scene.collection.objects.link(ob)
        if parent is not None:
            ob.parent = parent
            ob.matrix_parent_inverse = Matrix.Identity(4)
        return ob

    def track_object(self, ob, link_to_scene=True):
        """Track an object copy that is used for evaluation only (never exported)."""
        self._track("objects", ob)
        if link_to_scene:
            self.scene.collection.objects.link(ob)
        return ob

    def track(self, attr, id_block):
        return self._track(attr, id_block)

    def evaluation_copy(self, source):
        """Visible, unparented, unanimated copy of ``source`` for evaluation in this scene.

        Hidden or excluded source objects are not evaluated by Blender, so every
        source is evaluated through such a copy. The world matrix is preserved so
        modifiers that depend on object placement (Boolean, Mirror...) match.
        """
        copy = source.copy()
        # A local copy of linked data keeps the bare source name; never let it hold
        # a name a staged node needs.
        copy.name = "__uex_eval"
        self.track_object(copy)
        world = source.matrix_world.copy()
        copy.animation_data_clear()
        copy.constraints.clear()
        copy.parent = None
        copy.matrix_world = world
        copy.hide_viewport = False
        return copy

    def discard(self, objects):
        for ob in objects:
            try:
                bpy.data.objects.remove(ob)
            except ReferenceError:
                pass

    def depsgraph(self):
        self.view_layer.update()
        return self.view_layer.depsgraph

    def exported_objects(self):
        return sorted(self.collection.all_objects, key=lambda ob: ob.name)

    def cleanup(self) -> list:
        errors = []
        for attr, id_block in reversed(self._ids):
            try:
                getattr(bpy.data, attr).remove(id_block)
            except ReferenceError:
                pass
            except Exception as exc:  # report, keep cleaning
                errors.append("could not remove temporary %s: %s" % (attr, exc))
        self._ids.clear()
        errors.extend(self.journal.restore())
        return errors


# ---------------------------------------------------------------- helpers


def pivot_matrix(asset) -> Matrix:
    if asset.origin_object:
        ob = bpy.data.objects[asset.origin_object]
        return Matrix.Translation(ob.matrix_world.translation)
    return Matrix.Translation(asset.origin_offset)


def staging_matrix(session, asset) -> Matrix:
    """World space (Blender units) -> staged space (centimetres, pivot at origin)."""
    return Matrix.Scale(session.cm_per_unit, 4) @ pivot_matrix(asset).inverted()


def _assign_materials(mesh, source_ob):
    """Make the staged mesh carry the source object's effective material slots.

    Slots are assigned in place: ``mesh.materials.clear()`` would also reset every
    face's material index to 0 and collapse multi-material meshes to one slot.
    """
    slots = [slot.material for slot in source_ob.material_slots]
    while len(mesh.materials) < len(slots):
        mesh.materials.append(None)
    while len(mesh.materials) > len(slots):
        mesh.materials.pop(index=len(mesh.materials) - 1)
    for index, material in enumerate(slots):
        if mesh.materials[index] != material:
            mesh.materials[index] = material


def evaluated_mesh(session, source_ob, depsgraph, matrix, name, keep_shape_keys=False, materials=True):
    """Copy ``source_ob``'s geometry (modifiers applied unless shape keys are kept)."""
    if keep_shape_keys:
        mesh = source_ob.data.copy()
    else:
        evaluated = source_ob.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
    session.adopt("meshes", mesh, name)
    mesh.transform(matrix, shape_keys=keep_shape_keys)
    if matrix.determinant() < 0.0:
        mesh.flip_normals()
    if materials:
        _assign_materials(mesh, source_ob)
    else:
        mesh.materials.clear()
    mesh.update()
    return mesh


def _triangles(mesh) -> int:
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def _unique(name, used: set) -> str:
    candidate = name
    index = 1
    while candidate.lower() in used:
        candidate = "%s_%d" % (name, index)
        index += 1
    used.add(candidate.lower())
    return candidate


def socket_transform(session, pivot, socket_ob):
    """(staged matrix, manifest entry) for a socket helper; ``pivot`` from :func:`pivot_matrix`."""
    relative = pivot.inverted() @ socket_ob.matrix_world
    location, rotation, scale = relative.decompose()
    location_cm = location * session.cm_per_unit
    staged = (Matrix.Translation(location_cm) @ rotation.to_matrix().to_4x4()
              @ Matrix.Diagonal(scale.to_4d()) @ SOCKET_COMPENSATION)
    rot3 = rotation.to_matrix()
    roll, pitch, yaw = rotation_to_unreal_rotator([[rot3[r][c] for c in range(3)] for r in range(3)])
    entry = {
        "location_cm": [round(location_cm.x, 4), round(-location_cm.y, 4), round(location_cm.z, 4)],
        "rotation": {"roll": roll, "pitch": pitch, "yaw": yaw},
        "scale": [round(v, 6) for v in scale],
    }
    return staged, entry


class StagedAsset:
    def __init__(self, session, asset):
        self.session = session
        self.asset = asset
        self.extras = {}
        self.collision_nodes = []
        self.lod0 = None
        self.needs_lod0_variant = False

    def content_hash(self, settings_payload: dict) -> str:
        return content_hash(self.session, settings_payload)

    def use_lod0_collision_layout(self):
        """Re-layout LOD collision for UE 5.6: ``UCX_<Asset>_LOD0_NN`` under the LOD0 node."""
        session = self.session
        for node, entry in self.collision_nodes:
            name = "%s%s_%02d" % (C.COLLISION_PREFIXES[entry.shape], self.lod0.name, entry.index)
            session.journal.claim(bpy.data.objects, name, node)
            session.journal.claim(bpy.data.meshes, name, node.data)
            node.parent = self.lod0
            node.matrix_parent_inverse = Matrix.Identity(4)


# ---------------------------------------------------------------- static


class EvaluationScene:
    """Evaluate objects (including hidden ones) through copies in a temporary scene.

    Blender does not evaluate hidden objects, so measuring a hidden generated LOD
    through its own evaluated data would ignore its Decimate modifier.
    """

    def __init__(self, context, objects):
        self.context = context
        self.objects = list(objects)
        self.session = None
        self.copies = {}
        self.depsgraph = None

    def __enter__(self):
        self.session = StagingSession(self.context.scene)
        try:
            for ob in self.objects:
                self.copies[ob.name] = self.session.evaluation_copy(ob)
            self.depsgraph = self.session.depsgraph()
        except BaseException:
            self.session.cleanup()
            raise
        return self

    def copy_of(self, ob):
        return self.copies[ob.name]

    def __exit__(self, *exc):
        self.session.cleanup()
        return False


def resolve_sources(names) -> dict:
    """Name -> object, resolved BEFORE staging claims any name.

    Once a staged copy takes a name (e.g. the LOD group empty becomes
    ``SM_Crate``), looking the source up by that name would return the copy.
    """
    return {name: bpy.data.objects[name] for name in dict.fromkeys(names)}


class _Evaluator:
    """Evaluate source objects through visible copies inside the staging scene."""

    def __init__(self, session, sources: dict, strip_armature=False):
        self.session = session
        self.copies = {}
        for name, source in sources.items():
            copy = session.evaluation_copy(source)
            if strip_armature:
                for mod in list(copy.modifiers):
                    if mod.type == "ARMATURE":
                        copy.modifiers.remove(mod)
            self.copies[name] = copy
        self.depsgraph = session.depsgraph() if self.copies else None

    def mesh(self, name, matrix, node_name, materials=True):
        return evaluated_mesh(self.session, self.copies[name], self.depsgraph, matrix, node_name,
                              materials=materials)

    def close(self):
        self.session.discard(self.copies.values())
        self.copies.clear()


def stage_static(session, asset, settings, owner_of) -> StagedAsset:
    staged = StagedAsset(session, asset)
    pivot = pivot_matrix(asset)
    G = Matrix.Scale(session.cm_per_unit, 4) @ pivot.inverted()
    render_nodes = {}
    lod0 = None
    lod_triangles = []
    geometry = list(asset.mesh_objects) + [lod.object_name for lod in asset.lods] + \
        [c.object_name for c in asset.collisions]
    objects = resolve_sources(geometry + [s.object_name for s in asset.sockets])
    evaluator = _Evaluator(session, {name: objects[name] for name in geometry})

    if asset.lods:
        group = session.new_object(asset.asset_name, None)
        group["fbx_type"] = "LodGroup"
        chain = [asset.mesh_objects[0]] + [lod.object_name for lod in sorted(asset.lods, key=lambda e: e.index)]
        for level, source_name in enumerate(chain):
            name = naming.lod_object_name(asset.asset_name, level)
            mesh = evaluator.mesh(source_name, G @ objects[source_name].matrix_world, name)
            node = session.new_object(name, mesh, parent=group)
            render_nodes[source_name] = node
            lod_triangles.append(_triangles(mesh))
        lod0 = render_nodes[chain[0]]
    elif len(asset.mesh_objects) == 1:
        source_name = asset.mesh_objects[0]
        mesh = evaluator.mesh(source_name, G @ objects[source_name].matrix_world, asset.asset_name)
        lod0 = session.new_object(asset.asset_name, mesh)
        render_nodes[source_name] = lod0
        lod_triangles.append(_triangles(mesh))
    else:
        used = {asset.asset_name.lower()}
        total = 0
        for source_name in asset.mesh_objects:
            node_name = _unique(naming.sanitize_name(source_name).value or "Mesh", used)
            mesh = evaluator.mesh(source_name, G @ objects[source_name].matrix_world, node_name)
            render_nodes[source_name] = session.new_object(node_name, mesh)
            total += _triangles(mesh)
        lod_triangles.append(total)

    staged.collision_nodes = []
    for entry in asset.collisions:
        source = objects[entry.object_name]
        prefix = C.COLLISION_PREFIXES[entry.shape]
        parent = None
        if asset.lods:
            # UE 5.8 matches LOD-group collision against the group name (root level);
            # UE 5.6 against the LOD0 node, and must find it under LOD0 or it also
            # merges the hull into higher LODs as render geometry.
            if settings.lod_collision_naming == C.LOD_COLLISION_LOD0:
                names = ["%s%s_%02d" % (prefix, lod0.name, entry.index)]
                parent = lod0
            else:
                names = ["%s%s_%02d" % (prefix, asset.asset_name, entry.index)]
        elif lod0 is not None:
            names = ["%s%s_%02d" % (prefix, asset.asset_name, entry.index)]
            parent = lod0
        else:
            owner_node = render_nodes.get(owner_of.get(entry.object_name, ""))
            if owner_node is None:
                raise StagingError("Collision '%s' has no render mesh in this asset." % entry.object_name)
            names = ["%s%s_%02d" % (prefix, owner_node.name, entry.index)]
            parent = owner_node
        for name in names:
            mesh = evaluator.mesh(entry.object_name, G @ source.matrix_world, name, materials=False)
            staged.collision_nodes.append((session.new_object(name, mesh, parent=parent), entry))
    evaluator.close()
    staged.lod0 = lod0
    staged.needs_lod0_variant = bool(asset.lods and asset.collisions
                                     and settings.lod_collision_naming == C.LOD_COLLISION_PER_ENGINE)

    sockets = []
    used_sockets = set()
    for entry in asset.sockets:
        source = objects[entry.object_name]
        socket_name = _unique(naming.sanitize_name(entry.socket_name, 0).value or "Socket", used_sockets)
        matrix, info = socket_transform(session, pivot, source)
        if lod0 is not None:
            parent = lod0
        else:
            parent = render_nodes.get(owner_of.get(entry.object_name, ""))
        node = session.new_object(C.SOCKET_PREFIX + socket_name, None, parent=parent)
        node.matrix_basis = matrix
        node.empty_display_size = 1.0
        info.update({"name": socket_name, "object": entry.object_name})
        sockets.append(info)

    first = lod0 if lod0 is not None else next(iter(render_nodes.values()))
    staged.extras = {
        "sockets": sockets,
        "material_slots": [m.name if m else "" for m in first.data.materials],
        "triangles": lod_triangles[0] if lod_triangles else 0,
        "lod_triangles": lod_triangles,
    }
    return staged


# ---------------------------------------------------------------- skeletal


def _has_shape_keys(ob) -> bool:
    keys = ob.data.shape_keys
    return keys is not None and len(keys.key_blocks) > 1


def staged_armature(session, source_arm, matrix, normalize_inheritance=False):
    data = source_arm.data.copy()
    session.track("armatures", data)
    data.transform(matrix)
    data.pose_position = "REST"
    if normalize_inheritance:
        for bone in data.bones:
            bone.inherit_scale = "FULL"
            bone.use_inherit_rotation = True
            bone.use_local_location = True
    return session.new_object(C.STAGED_ARMATURE_NAME, data)


def stage_skeletal(session, asset, settings) -> StagedAsset:
    staged = StagedAsset(session, asset)
    G = staging_matrix(session, asset)
    objects = resolve_sources([asset.armature] + list(asset.mesh_objects) + [lod.object_name for lod in asset.lods])
    source_arm = objects[asset.armature]
    arm = staged_armature(session, source_arm, G @ source_arm.matrix_world)

    used = {C.STAGED_ARMATURE_NAME.lower()}
    morphs = []
    slots = []
    triangles = 0
    group = None
    chain = list(asset.mesh_objects)
    if asset.lods:
        group = session.new_object(asset.asset_name, None, parent=arm)
        group["fbx_type"] = "LodGroup"
        used.add(asset.asset_name.lower())
        chain = [asset.mesh_objects[0]] + [lod.object_name for lod in sorted(asset.lods, key=lambda e: e.index)]

    keyed = {name for name in chain if settings.export_morph_targets and _has_shape_keys(objects[name])}
    # Rest-pose geometry: evaluate without armature deformation.
    evaluator = _Evaluator(session, {name: objects[name] for name in chain if name not in keyed},
                           strip_armature=True)
    for level, source_name in enumerate(chain):
        source = objects[source_name]
        if group is not None:
            node_name = naming.lod_object_name(asset.asset_name, level)
            used.add(node_name.lower())
        else:
            node_name = _unique(naming.sanitize_name(source_name).value or "Mesh", used)
        if source_name in keyed:
            # Morph targets need the raw mesh with shape keys (modifiers are not applied).
            mesh = evaluated_mesh(session, source, None, G @ source.matrix_world, node_name, keep_shape_keys=True)
            if level == 0 or group is None:
                morphs.extend(kb.name for kb in source.data.shape_keys.key_blocks[1:])
        else:
            mesh = evaluator.mesh(source_name, G @ source.matrix_world, node_name)
        node = session.new_object(node_name, mesh, parent=group if group is not None else arm)
        modifier = node.modifiers.new("Armature", "ARMATURE")
        modifier.object = arm
        if level == 0 or group is None:
            triangles += _triangles(mesh)
            for material in mesh.materials:
                name = material.name if material else ""
                if name not in slots:
                    slots.append(name)
    evaluator.close()

    bones = [b.name for b in arm.data.bones]
    staged.extras = {
        "material_slots": slots,
        "morph_targets": sorted(set(morphs)),
        "triangles": triangles,
        "bones": len(bones),
        "root_bones": sorted(b.name for b in arm.data.bones if b.parent is None),
    }
    return staged


# ---------------------------------------------------------------- hashing


def _array(collection, attr, count, width, dtype=np.float64):
    data = np.empty(count * width, dtype=dtype)
    if count:
        collection.foreach_get(attr, data)
    return data


def _hash_mesh(h, mesh):
    co = _array(mesh.vertices, "co", len(mesh.vertices), 3)
    h.update(np.round(co, 5).tobytes())
    loops = _array(mesh.loops, "vertex_index", len(mesh.loops), 1, np.int64)
    h.update(loops.tobytes())
    totals = _array(mesh.polygons, "loop_total", len(mesh.polygons), 1, np.int64)
    h.update(totals.tobytes())
    material_index = _array(mesh.polygons, "material_index", len(mesh.polygons), 1, np.int64)
    h.update(material_index.tobytes())
    for layer in mesh.uv_layers:
        h.update(layer.name.encode())
        uv = _array(layer.data, "uv", len(mesh.loops), 2)
        h.update(np.round(uv, 5).tobytes())
    h.update("|".join(m.name if m else "" for m in mesh.materials).encode())
    if mesh.shape_keys:
        for block in mesh.shape_keys.key_blocks:
            h.update(block.name.encode())
            h.update(np.round(_array(block.data, "co", len(block.data), 3), 5).tobytes())


def content_hash(session, settings_payload: dict) -> str:
    """Deterministic hash of everything that will be written to the FBX."""
    h = hashlib.sha256()
    for ob in session.exported_objects():
        h.update(("%s|%s|%s|" % (ob.name, ob.type, ob.parent.name if ob.parent else "")).encode())
        h.update(np.round(np.array(ob.matrix_basis, dtype=np.float64), 5).tobytes())
        if ob.type == "MESH":
            _hash_mesh(h, ob.data)
            if ob.vertex_groups:
                for group in ob.vertex_groups:
                    h.update(group.name.encode())
                for vertex in ob.data.vertices:
                    for g in vertex.groups:
                        h.update(b"%d:%d:%.5f" % (vertex.index, g.group, g.weight))
        elif ob.type == "ARMATURE":
            for bone in ob.data.bones:
                h.update(("%s<%s" % (bone.name, bone.parent.name if bone.parent else "")).encode())
                h.update(np.round(np.array(bone.matrix_local, dtype=np.float64), 5).tobytes())
            adt = ob.animation_data
            if adt is not None and adt.action is not None:
                from .scene_snapshot import action_fcurves

                for fcurve in sorted(action_fcurves(adt.action), key=lambda f: (f.data_path, f.array_index)):
                    h.update(("%s[%d]" % (fcurve.data_path, fcurve.array_index)).encode())
                    co = _array(fcurve.keyframe_points, "co", len(fcurve.keyframe_points), 2)
                    h.update(np.round(co, 5).tobytes())
        elif ob.type == "EMPTY":
            h.update(str(ob.get("fbx_type", "")).encode())
    h.update(json.dumps(settings_payload, sort_keys=True, default=str).encode())
    return h.hexdigest()
