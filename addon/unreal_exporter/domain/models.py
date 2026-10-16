"""Immutable records shared by discovery, validation, planning and the services.

Scene data enters the domain as a :class:`SceneSnapshot` built by
``services/scene_snapshot.py``. Everything here is plain data so that the
domain logic can be unit-tested without Blender.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import constants as C

Matrix16 = tuple  # 16 floats, row-major 4x4


IDENTITY16 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


@dataclass(frozen=True)
class MeshStats:
    """Geometry facts gathered from the evaluated mesh."""

    vertex_count: int = 0
    polygon_count: int = 0
    triangle_count: int = 0
    ngon_count: int = 0
    non_manifold_edge_count: int = 0
    degenerate_face_count: int = 0
    uv_layers: tuple = ()
    uv1_area_sum: float = 0.0
    uv1_out_of_bounds: bool = False
    material_slots: tuple = ()  # material names, "" for empty slots
    shape_keys: tuple = ()  # names, excluding the basis key
    vertex_groups: tuple = ()
    max_bone_influences: int = 0
    unweighted_vertex_count: int = 0
    color_attributes: tuple = ()
    is_convex: bool = True
    bounds_min: tuple = (0.0, 0.0, 0.0)
    bounds_max: tuple = (0.0, 0.0, 0.0)
    # Shape-fit errors for primitive collision helpers (0.0 means perfect fit).
    box_fit_error: float = 0.0
    sphere_fit_error: float = 0.0


@dataclass(frozen=True)
class BoneRecord:
    name: str
    parent: str = ""
    use_deform: bool = True


@dataclass(frozen=True)
class ModifierRecord:
    name: str
    type: str
    enabled: bool = True
    target: str = ""  # object name referenced by Armature modifiers


@dataclass(frozen=True)
class ObjectRecord:
    """Snapshot of one Blender object, keyed by its (unique) name."""

    name: str
    type: str
    uuid: str = ""
    data_name: str = ""
    parent: str = ""
    parent_type: str = "OBJECT"
    collections: tuple = ()
    matrix_world: Matrix16 = IDENTITY16
    # World-space decomposition used by transform validation.
    location: tuple = (0.0, 0.0, 0.0)
    rotation_quaternion: tuple = (1.0, 0.0, 0.0, 0.0)
    scale: tuple = (1.0, 1.0, 1.0)
    selected: bool = False
    visible: bool = True
    # Add-on metadata.
    role: str = C.ROLE_NONE
    owner_uuid: str = ""
    collision_shape: str = ""
    lod_index: int = -1
    lod_generated: bool = False
    socket_name: str = ""
    export_enabled: bool = True
    asset_name_override: str = ""
    folder_override: str = ""
    skeleton_path_override: str = ""
    # Geometry / rig facts.
    mesh: MeshStats | None = None
    modifiers: tuple = ()  # ModifierRecord
    bones: tuple = ()  # BoneRecord (armatures only)
    is_animated: bool = False
    active_action: str = ""
    empty_display_size: float = 1.0

    @property
    def armature_targets(self) -> tuple:
        """Names of armatures deforming this mesh (modifiers and armature parenting)."""
        names = []
        for mod in self.modifiers:
            if mod.type == "ARMATURE" and mod.enabled and mod.target and mod.target not in names:
                names.append(mod.target)
        if self.parent and self.parent_type == "ARMATURE" and self.parent not in names:
            names.append(self.parent)
        return tuple(names)


@dataclass(frozen=True)
class CollectionRecord:
    name: str
    uuid: str = ""
    objects: tuple = ()  # direct member names
    children: tuple = ()  # child collection names
    instance_offset: tuple = (0.0, 0.0, 0.0)
    asset_name_override: str = ""
    folder_override: str = ""


@dataclass(frozen=True)
class ActionRecord:
    name: str
    uuid: str = ""
    frame_start: float = 1.0
    frame_end: float = 1.0
    bone_names: tuple = ()  # pose bones animated by the action
    has_object_slot: bool = True


@dataclass(frozen=True)
class SceneSnapshot:
    scene_name: str = "Scene"
    blender_version: str = ""
    blend_path: str = ""
    unit_system: str = "METRIC"
    unit_scale: float = 1.0
    fps: float = 24.0
    frame_start: int = 1
    frame_end: int = 250
    objects: tuple = ()  # ObjectRecord
    collections: tuple = ()  # CollectionRecord
    actions: tuple = ()  # ActionRecord
    active_collection: str = ""
    active_object: str = ""

    def object(self, name: str) -> ObjectRecord | None:
        return self._object_index().get(name)

    def collection(self, name: str) -> CollectionRecord | None:
        for coll in self.collections:
            if coll.name == name:
                return coll
        return None

    def action(self, name: str) -> ActionRecord | None:
        for act in self.actions:
            if act.name == name:
                return act
        return None

    def object_by_uuid(self, uuid: str) -> ObjectRecord | None:
        if not uuid:
            return None
        for ob in self.objects:
            if ob.uuid == uuid:
                return ob
        return None

    def collection_all_objects(self, name: str) -> tuple:
        """Recursive object membership of a collection, sorted and de-duplicated."""
        seen = set()
        stack = [name]
        visited = set()
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            coll = self.collection(current)
            if coll is None:
                continue
            seen.update(coll.objects)
            stack.extend(coll.children)
        return tuple(sorted(seen))

    def _object_index(self) -> dict:
        cache = self.__dict__.get("_index_cache")
        if cache is None:
            cache = {ob.name: ob for ob in self.objects}
            object.__setattr__(self, "_index_cache", cache)
        return cache


@dataclass(frozen=True)
class ExportSettings:
    """Resolved export settings (scene settings merged with preferences)."""

    profile: str = C.PROFILE_STATIC_MESH
    scope: str = C.SCOPE_SELECTED
    grouping: str = C.GROUP_PER_OBJECT
    chosen_collections: tuple = ()
    export_root: str = ""  # absolute directory
    permitted_roots: tuple = ()  # absolute directories; empty means unrestricted
    unreal_root: str = "/Game/BlenderExports"
    mirror_collections_as_folders: bool = False
    auto_prefix: bool = True
    prefix_static: str = C.DEFAULT_PREFIX_STATIC
    prefix_skeletal: str = C.DEFAULT_PREFIX_SKELETAL
    prefix_animation: str = C.DEFAULT_PREFIX_ANIMATION
    max_name_length: int = C.DEFAULT_MAX_NAME_LENGTH
    origin_mode: str = C.ORIGIN_OBJECT
    # Geometry.
    apply_modifiers: bool = True
    triangulate: bool = False
    export_tangents: bool = False
    smoothing: str = "FACE"
    export_vertex_colors: bool = True
    export_morph_targets: bool = True
    deform_bones_only: bool = True
    primary_bone_axis: str = "Y"
    secondary_bone_axis: str = "X"
    # Collision / LOD.
    one_convex_hull_per_ucx: bool = True
    auto_generate_collision: bool = True  # Unreal fallback hull for static meshes without collision helpers
    lod_collision_naming: str = C.LOD_COLLISION_PER_ENGINE
    max_material_slots: int = 8
    max_bone_influences: int = 8
    socket_distance_tolerance: float = 1.0  # metres beyond the bounds
    # Animation.
    actions: tuple = ()  # action names chosen for export (empty = active action)
    animation_name_includes_armature: bool = False
    skeletal_include_animations: bool = False
    frame_range_mode: str = C.FRAME_RANGE_ACTION
    custom_frame_start: int = 1
    custom_frame_end: int = 24
    sample_step: float = 1.0
    simplify: float = 0.0
    root_motion: str = C.ROOT_MOTION_NONE
    nla_policy: str = C.NLA_ACTION_ONLY
    # Unreal import options.
    import_materials: bool = False
    import_textures: bool = False
    build_nanite: bool = False
    generate_lightmap_uvs: bool = False
    create_physics_asset: bool = True
    reimport_policy: str = C.REIMPORT_UPDATE_EXISTING
    destination: str = C.DEST_SCRIPT
    developer_mode: bool = False
    debug_paths: bool = False


@dataclass(frozen=True)
class CollisionEntry:
    object_name: str
    shape: str
    index: int


@dataclass(frozen=True)
class SocketEntry:
    object_name: str
    socket_name: str


@dataclass(frozen=True)
class LodEntry:
    index: int
    object_name: str
    generated: bool = False


@dataclass(frozen=True)
class ExportAsset:
    """One Unreal asset (one FBX file)."""

    id: str
    kind: str
    asset_name: str
    source_name: str
    unreal_path: str
    file_relpath: str
    origin_object: str = ""  # object whose origin is the asset pivot ("" = world / collection offset)
    origin_offset: tuple = (0.0, 0.0, 0.0)  # used when origin_object is empty
    mesh_objects: tuple = ()  # render meshes for LOD0
    lods: tuple = ()  # LodEntry for LOD1..N
    collisions: tuple = ()  # CollisionEntry
    sockets: tuple = ()  # SocketEntry
    armature: str = ""
    action: str = ""
    skeleton_path: str = ""
    skeleton_asset_id: str = ""  # id of a skeletal asset in the same plan, if any
    frame_start: float = 0.0
    frame_end: float = 0.0
    source_object_ids: tuple = ()
    collection: str = ""
    sanitized_from: str = ""  # original name when sanitization changed it

    @property
    def all_object_names(self) -> tuple:
        names = list(self.mesh_objects)
        names.extend(lod.object_name for lod in self.lods)
        names.extend(c.object_name for c in self.collisions)
        names.extend(s.object_name for s in self.sockets)
        if self.armature:
            names.append(self.armature)
        if self.origin_object and self.origin_object not in names:
            names.append(self.origin_object)
        return tuple(names)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    object_id: str = ""  # object (or collection) name the issue points at
    fix_id: str = ""
    details: tuple = ()  # tuple of (key, value) pairs; hashable and ordered
    asset_id: str = ""

    @property
    def is_blocking(self) -> bool:
        return self.severity == C.SEVERITY_ERROR

    def detail(self, key: str, default=None):
        for k, v in self.details:
            if k == key:
                return v
        return default


@dataclass(frozen=True)
class PlannedFile:
    asset_id: str
    kind: str
    relpath: str  # posix, relative to export root


@dataclass(frozen=True)
class ExportPlan:
    plan_version: int
    plan_id: str
    blender_version: str
    unreal_target: tuple  # (min, gate)
    output_root: str
    assets: tuple  # ExportAsset
    files: tuple  # PlannedFile
    import_options: tuple  # sorted (key, value) pairs
    settings: ExportSettings
    unit_scale: float = 1.0

    def import_option(self, key: str, default=None):
        for k, v in self.import_options:
            if k == key:
                return v
        return default


@dataclass
class AssetResult:
    asset_id: str
    asset_name: str
    kind: str
    unreal_path: str
    relpath: str
    status: str = "pending"  # written | failed | skipped
    seconds: float = 0.0
    file_sha256: str = ""
    source_hash: str = ""
    warnings: list = field(default_factory=list)
    error: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class ExportResult:
    plan_id: str
    started_at: str
    finished_at: str = ""
    files: list = field(default_factory=list)  # AssetResult
    warnings: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    imported_assets: list = field(default_factory=list)
    manifest_path: str = ""
    script_path: str = ""
    log_path: str = ""
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.failures and not self.cancelled
