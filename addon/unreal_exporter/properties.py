"""PropertyGroups: object/collection/action metadata, scene settings, runtime UI state.

Scene, Object, Collection and Action groups are saved in the .blend file.
The WindowManager group holds runtime-only state (issues, results, previews).
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from . import constants as C

ROLE_ITEMS = (
    (C.ROLE_NONE, "None", "Regular object"),
    (C.ROLE_COLLISION, "Collision", "Custom collision helper of a render mesh"),
    (C.ROLE_SOCKET, "Socket", "Static-mesh socket helper"),
    (C.ROLE_LOD, "LOD", "Level-of-detail mesh of a render mesh"),
)

SHAPE_ITEMS = (
    (C.SHAPE_BOX, "Box", "UBX_ box primitive (undeformed rectangular box)", "MESH_CUBE", 0),
    (C.SHAPE_SPHERE, "Sphere", "USP_ sphere primitive", "MESH_UVSPHERE", 1),
    (C.SHAPE_CAPSULE, "Capsule", "UCP_ capsule primitive", "MESH_CAPSULE", 2),
    (C.SHAPE_CONVEX, "Convex", "UCX_ closed convex hull", "MESH_ICOSPHERE", 3),
)

CREATE_SHAPE_ITEMS = SHAPE_ITEMS + (
    ("CYLINDER", "Cylinder", "Convex cylinder written as a UCX_ hull", "MESH_CYLINDER", 4),
)

PROFILE_ITEMS = (
    (C.PROFILE_STATIC_MESH, "Static Mesh", "Every mesh in scope becomes a static mesh"),
    (C.PROFILE_SKELETAL_MESH, "Skeletal Mesh", "Every armature in scope and the meshes it deforms"),
    (C.PROFILE_ANIMATION, "Animation", "One file per chosen action of each armature in scope"),
    (C.PROFILE_COLLECTION_SCENE, "Collection Scene", "Static and skeletal meshes found in scope"),
)

SCOPE_ITEMS = (
    (C.SCOPE_SELECTED, "Selected", "Selected objects (helpers resolve to their owners)"),
    (C.SCOPE_ACTIVE_COLLECTION, "Active Collection", "All objects in the active collection and its children"),
    (C.SCOPE_CHOSEN_COLLECTIONS, "Chosen Collections", "All objects in the collections listed below"),
)

GROUPING_ITEMS = (
    (C.GROUP_PER_OBJECT, "Per Object", "One asset per mesh object"),
    (C.GROUP_PER_COLLECTION, "Per Collection", "Combine the meshes of each collection into one asset"),
)

ORIGIN_ITEMS = (
    (C.ORIGIN_OBJECT, "Object Origin", "The asset pivot is the object origin (or collection instance offset)"),
    (C.ORIGIN_WORLD, "World Origin", "Keep world placement; the pivot is the world origin"),
)

SMOOTHING_ITEMS = (
    ("FACE", "Face", "Write face smoothing (recommended for Unreal)"),
    ("EDGE", "Edge", "Write edge smoothing"),
    ("OFF", "Normals Only", "Write normals only"),
)

BONE_AXIS_ITEMS = tuple((a, a, "") for a in ("X", "Y", "Z", "-X", "-Y", "-Z"))

LOD_COLLISION_ITEMS = (
    (C.LOD_COLLISION_PER_ENGINE, "Per Engine (5.6 and 5.8)",
     "Main FBX for Unreal 5.8 plus a .ue56.fbx variant the import script uses on Unreal 5.6"),
    (C.LOD_COLLISION_GROUP, "Unreal 5.8 Only", "UCX_<Asset>_NN next to the LOD group"),
    (C.LOD_COLLISION_LOD0, "Unreal 5.6 Only", "UCX_<Asset>_LOD0_NN under the LOD0 mesh"),
)

FRAME_RANGE_ITEMS = (
    (C.FRAME_RANGE_ACTION, "Action", "Use each action's frame range"),
    (C.FRAME_RANGE_SCENE, "Scene", "Use the scene frame range"),
    (C.FRAME_RANGE_CUSTOM, "Custom", "Use the custom range below"),
)

ROOT_MOTION_ITEMS = (
    (C.ROOT_MOTION_NONE, "Keep, Disabled", "Export root bone motion as authored; Unreal root motion off"),
    (C.ROOT_MOTION_ROOT_BONE, "Root Bone", "Export root bone motion; enable root motion in Unreal"),
    (C.ROOT_MOTION_IN_PLACE, "In Place", "Remove horizontal root bone translation"),
    (C.ROOT_MOTION_OBJECT_TO_ROOT, "Object to Root", "Bake armature object motion into the root bone; enable root motion"),
)

NLA_ITEMS = (
    (C.NLA_ACTION_ONLY, "Action Only", "Evaluate only the exported action (NLA muted)"),
    (C.NLA_SCENE, "Scene Result", "Bake whatever the armature evaluates to (NLA included)"),
)

REIMPORT_ITEMS = (
    (C.REIMPORT_UPDATE_EXISTING, "Update Existing", "Reimport into the asset created earlier, even if renamed in Blender"),
    (C.REIMPORT_FOLLOW_RENAME, "Follow Rename", "Rename the existing Unreal asset to match the new Blender name"),
)

DESTINATION_ITEMS = (
    (C.DEST_DISK, "Disk", "Write FBX files and the manifest"),
    (C.DEST_SCRIPT, "Disk + Import Script", "Also write import_to_unreal.py"),
)

SOCKET_MODE_ITEMS = (
    ("CURSOR", "3D Cursor", "At the 3D cursor location and rotation"),
    ("ORIGIN", "Object Origin", "At the owner's origin"),
    ("SELECTION", "Selection Median", "At the median of the selection"),
    ("ACTIVE", "Active Element", "At the active vertex (Edit Mode) or bone (Pose Mode)"),
    ("EMPTY", "Selected Empties", "Convert the selected empties into sockets"),
)

LOD_PRESET_ITEMS = (
    ("HALVES_3", "3 LODs: 50/25/12.5%", ""),
    ("HALVES_4", "4 LODs: 50/25/12.5/6%", ""),
    ("GENTLE_3", "3 LODs: 70/40/20%", ""),
    ("CUSTOM", "Custom", "Use the custom values below"),
)

LOD_MODE_ITEMS = (
    ("RATIO", "Percent", "Custom values are percentages of LOD0 triangles"),
    ("TRIANGLES", "Triangles", "Custom values are target triangle counts"),
)

RENAME_MODE_ITEMS = (
    ("REPLACE", "Find & Replace", ""),
    ("AFFIX", "Prefix & Suffix", ""),
    ("SET", "Set Name", "Rename the single active asset"),
)

SEVERITY_ITEMS = (
    (C.SEVERITY_ERROR, "Error", ""),
    (C.SEVERITY_WARNING, "Warning", ""),
    (C.SEVERITY_INFO, "Info", ""),
)


class UEX_ObjectSettings(bpy.types.PropertyGroup):
    uuid: StringProperty(name="Export ID", options={"HIDDEN"})
    uuid_name_hint: StringProperty(options={"HIDDEN"})
    role: EnumProperty(name="Role", items=ROLE_ITEMS, default=C.ROLE_NONE)
    owner_uuid: StringProperty(name="Owner", options={"HIDDEN"})
    collision_shape: EnumProperty(name="Collision Shape", items=SHAPE_ITEMS, default=C.SHAPE_CONVEX)
    lod_index: IntProperty(name="LOD Index", min=0, max=7, default=0)
    lod_generated: BoolProperty(name="Generated LOD", default=False)
    lod_ratio: FloatProperty(name="LOD Ratio", min=0.0, max=1.0, default=1.0)
    socket_name: StringProperty(name="Socket Name")
    is_preview: BoolProperty(options={"HIDDEN"}, default=False)
    export_enabled: BoolProperty(name="Export", description="Include this object when exporting", default=True)
    asset_name_override: StringProperty(name="Asset Name", description="Unreal asset name (default: object name)")
    folder_override: StringProperty(name="Folder", description="Sub-folder below the Unreal root, e.g. Props/Kitchen")
    skeleton_path_override: StringProperty(
        name="Unreal Skeleton",
        description="Existing Unreal skeleton object path for animation-only imports (default: derived)",
    )


class UEX_IdSettings(bpy.types.PropertyGroup):
    """Collections and actions only need a stable id and overrides."""

    uuid: StringProperty(options={"HIDDEN"})
    uuid_name_hint: StringProperty(options={"HIDDEN"})
    asset_name_override: StringProperty(name="Asset Name")
    folder_override: StringProperty(name="Folder")


class UEX_CollectionRef(bpy.types.PropertyGroup):
    collection: PointerProperty(type=bpy.types.Collection, name="Collection")


class UEX_ActionRef(bpy.types.PropertyGroup):
    action: PointerProperty(type=bpy.types.Action, name="Action")
    export: BoolProperty(name="Export", default=True)


class UEX_SceneSettings(bpy.types.PropertyGroup):
    # What and where.
    profile: EnumProperty(name="Profile", items=PROFILE_ITEMS, default=C.PROFILE_STATIC_MESH)
    scope: EnumProperty(name="Scope", items=SCOPE_ITEMS, default=C.SCOPE_SELECTED)
    grouping: EnumProperty(name="Grouping", items=GROUPING_ITEMS, default=C.GROUP_PER_OBJECT)
    chosen_collections: CollectionProperty(type=UEX_CollectionRef)
    chosen_collections_index: IntProperty()
    export_dir: StringProperty(name="Export Folder", subtype="DIR_PATH", default="//unreal_export/")
    unreal_root: StringProperty(name="Unreal Folder", default="/Game/BlenderExports")
    mirror_collections_as_folders: BoolProperty(name="Collections as Folders", default=False,
                                                description="Mirror the collection hierarchy as Unreal folders")
    destination: EnumProperty(name="Destination", items=DESTINATION_ITEMS, default=C.DEST_SCRIPT)
    # Naming.
    auto_prefix: BoolProperty(name="Auto Prefix", default=True,
                              description="Prefix Unreal asset names (SM_, SK_, A_) when missing")
    prefix_static: StringProperty(name="Static", default=C.DEFAULT_PREFIX_STATIC)
    prefix_skeletal: StringProperty(name="Skeletal", default=C.DEFAULT_PREFIX_SKELETAL)
    prefix_animation: StringProperty(name="Animation", default=C.DEFAULT_PREFIX_ANIMATION)
    # Transform & geometry.
    origin_mode: EnumProperty(name="Pivot", items=ORIGIN_ITEMS, default=C.ORIGIN_OBJECT)
    triangulate: BoolProperty(name="Triangulate", default=False)
    export_tangents: BoolProperty(name="Export Tangents", default=False,
                                  description="Write tangents (needs triangles/quads); otherwise Unreal computes MikkTSpace")
    smoothing: EnumProperty(name="Smoothing", items=SMOOTHING_ITEMS, default="FACE")
    export_vertex_colors: BoolProperty(name="Vertex Colors", default=True)
    export_morph_targets: BoolProperty(name="Morph Targets", default=True,
                                       description="Export shape keys of skeletal meshes as morph targets")
    deform_bones_only: BoolProperty(name="Deform Bones Only", default=True)
    primary_bone_axis: EnumProperty(name="Primary Bone Axis", items=BONE_AXIS_ITEMS, default="Y")
    secondary_bone_axis: EnumProperty(name="Secondary Bone Axis", items=BONE_AXIS_ITEMS, default="X")
    # Collision / LOD / limits.
    one_convex_hull_per_ucx: BoolProperty(name="One Hull per UCX", default=True)
    auto_generate_collision: BoolProperty(
        name="Collision When Missing", default=True,
        description="Let Unreal generate a simple convex collision for static meshes that have no collision "
                    "helpers (meshes with helpers always use exactly their helpers)")
    lod_collision_naming: EnumProperty(name="LOD Collision Names", items=LOD_COLLISION_ITEMS,
                                       default=C.LOD_COLLISION_PER_ENGINE)
    max_material_slots: IntProperty(name="Max Material Slots", default=8, min=1)
    max_bone_influences: IntProperty(name="Max Bone Influences", default=8, min=1)
    socket_distance_tolerance: FloatProperty(name="Socket Distance", default=1.0, min=0.0, subtype="DISTANCE",
                                             description="Warn when a socket is this far outside the asset bounds")
    # Animation.
    actions: CollectionProperty(type=UEX_ActionRef)
    actions_index: IntProperty()
    animation_name_includes_armature: BoolProperty(name="Prefix With Armature", default=False)
    skeletal_include_animations: BoolProperty(name="Include Animations", default=False,
                                              description="Skeletal profile: also export the checked actions")
    frame_range_mode: EnumProperty(name="Frame Range", items=FRAME_RANGE_ITEMS, default=C.FRAME_RANGE_ACTION)
    custom_frame_start: IntProperty(name="Start", default=1)
    custom_frame_end: IntProperty(name="End", default=24)
    sample_step: FloatProperty(name="Sample Step", default=1.0, min=0.01, max=10.0,
                               description="Frames between baked samples")
    simplify: FloatProperty(name="Simplify", default=0.0, min=0.0, max=10.0,
                            description="FBX key simplification (0 keeps every sample)")
    root_motion: EnumProperty(name="Root Motion", items=ROOT_MOTION_ITEMS, default=C.ROOT_MOTION_NONE)
    nla_policy: EnumProperty(name="NLA", items=NLA_ITEMS, default=C.NLA_ACTION_ONLY)
    # Unreal import.
    import_materials: BoolProperty(name="Import Materials", default=False)
    import_textures: BoolProperty(name="Import Textures", default=False)
    build_nanite: BoolProperty(name="Build Nanite", default=False)
    generate_lightmap_uvs: BoolProperty(name="Generate Lightmap UVs", default=False)
    create_physics_asset: BoolProperty(name="Create Physics Asset", default=True)
    reimport_policy: EnumProperty(name="Renamed Sources", items=REIMPORT_ITEMS, default=C.REIMPORT_UPDATE_EXISTING)
    # Tool settings.
    collision_shape: EnumProperty(name="Shape", items=CREATE_SHAPE_ITEMS, default=C.SHAPE_CONVEX)
    collision_padding: FloatProperty(name="Padding", default=0.0, min=0.0, subtype="DISTANCE")
    collision_segments: IntProperty(name="Segments", default=12, min=3, max=64)
    socket_mode: EnumProperty(name="Place At", items=SOCKET_MODE_ITEMS, default="CURSOR")
    socket_name: StringProperty(name="Name", default="Socket")
    lod_preset: EnumProperty(name="Preset", items=LOD_PRESET_ITEMS, default="HALVES_3")
    lod_mode: EnumProperty(name="Values", items=LOD_MODE_ITEMS, default="RATIO")
    lod_custom: StringProperty(name="Custom", default="50, 25, 12.5",
                               description="Comma-separated percentages or triangle counts, one per LOD")
    rename_mode: EnumProperty(name="Mode", items=RENAME_MODE_ITEMS, default="REPLACE")
    rename_find: StringProperty(name="Find")
    rename_replace: StringProperty(name="Replace")
    rename_prefix: StringProperty(name="Prefix")
    rename_suffix: StringProperty(name="Suffix")
    rename_name: StringProperty(name="New Name")
    rename_case_sensitive: BoolProperty(name="Case Sensitive", default=True)


class UEX_IssueItem(bpy.types.PropertyGroup):
    code: StringProperty()
    severity: EnumProperty(items=SEVERITY_ITEMS)
    message: StringProperty()
    object_name: StringProperty()
    fix_id: StringProperty()
    asset_id: StringProperty()


class UEX_ResultItem(bpy.types.PropertyGroup):
    asset_name: StringProperty()
    kind: StringProperty()
    relpath: StringProperty()
    unreal_path: StringProperty()
    status: StringProperty()
    seconds: FloatProperty()
    message: StringProperty()


class UEX_RenameItem(bpy.types.PropertyGroup):
    old_name: StringProperty()
    new_name: StringProperty()
    kind: StringProperty()
    conflict: StringProperty()


class UEX_LodStat(bpy.types.PropertyGroup):
    object_name: StringProperty()
    index: IntProperty()
    triangles: IntProperty()
    generated: BoolProperty()


class UEX_WindowState(bpy.types.PropertyGroup):
    issues: CollectionProperty(type=UEX_IssueItem)
    issues_index: IntProperty()
    issue_errors: IntProperty()
    issue_warnings: IntProperty()
    issue_infos: IntProperty()
    validated: BoolProperty(default=False)
    validated_assets: IntProperty()
    show_info: BoolProperty(name="Show Info", default=False)
    results: CollectionProperty(type=UEX_ResultItem)
    results_index: IntProperty()
    result_summary: StringProperty()
    result_ok: BoolProperty(default=True)
    result_dir: StringProperty()
    last_plan_id: StringProperty()
    manifest_path: StringProperty()
    script_path: StringProperty()
    log_path: StringProperty()
    receipt_summary: StringProperty()
    rename_preview: CollectionProperty(type=UEX_RenameItem)
    rename_preview_index: IntProperty()
    lod_stats: CollectionProperty(type=UEX_LodStat)
    lod_stats_index: IntProperty()
    lod_stats_owner: StringProperty()


CLASSES = (
    UEX_ObjectSettings,
    UEX_IdSettings,
    UEX_CollectionRef,
    UEX_ActionRef,
    UEX_SceneSettings,
    UEX_IssueItem,
    UEX_ResultItem,
    UEX_RenameItem,
    UEX_LodStat,
    UEX_WindowState,
)

# (ID type, attribute, PropertyGroup) attached at registration.
POINTERS = (
    (bpy.types.Object, C.PROP_ATTR, UEX_ObjectSettings),
    (bpy.types.Collection, C.PROP_ATTR, UEX_IdSettings),
    (bpy.types.Action, C.PROP_ATTR, UEX_IdSettings),
    (bpy.types.Scene, C.PROP_ATTR, UEX_SceneSettings),
    (bpy.types.WindowManager, C.PROP_ATTR, UEX_WindowState),
)
