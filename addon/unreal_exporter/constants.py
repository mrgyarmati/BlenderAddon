"""Shared constants. Pure Python: importable without Blender."""

ADDON_ID = "unreal_exporter"
ADDON_VERSION = (0, 1, 0)
ADDON_VERSION_STRING = ".".join(str(part) for part in ADDON_VERSION)

# Manifest / receipt schema identifiers.
MANIFEST_SCHEMA = "blender-unreal-bridge/manifest"
MANIFEST_SCHEMA_VERSION = 1
RECEIPT_SCHEMA = "blender-unreal-bridge/receipt"
RECEIPT_SCHEMA_VERSION = 1

# Output file names written beside the exported FBX files.
MANIFEST_FILENAME = "unreal_export_manifest.json"
IMPORT_SCRIPT_FILENAME = "import_to_unreal.py"
LOG_TEXT_FILENAME = "unreal_export_log.txt"
LOG_JSON_FILENAME = "unreal_export_log.jsonl"
RECEIPT_FILENAME = "unreal_import_receipt.json"

# Unreal version policy.
UNREAL_MIN_VERSION = "5.6"
UNREAL_GATE_VERSION = "5.8"

# Asset kinds.
KIND_STATIC_MESH = "STATIC_MESH"
KIND_SKELETAL_MESH = "SKELETAL_MESH"
KIND_ANIMATION = "ANIMATION"
ASSET_KINDS = (KIND_STATIC_MESH, KIND_SKELETAL_MESH, KIND_ANIMATION)

# Export profiles (user-facing choice in the panel).
PROFILE_STATIC_MESH = "STATIC_MESH"
PROFILE_SKELETAL_MESH = "SKELETAL_MESH"
PROFILE_ANIMATION = "ANIMATION"
PROFILE_COLLECTION_SCENE = "COLLECTION_SCENE"

# Scope of what gets exported.
SCOPE_SELECTED = "SELECTED"
SCOPE_ACTIVE_COLLECTION = "ACTIVE_COLLECTION"
SCOPE_CHOSEN_COLLECTIONS = "CHOSEN_COLLECTIONS"

# Grouping of static meshes into assets.
GROUP_PER_OBJECT = "PER_OBJECT"
GROUP_PER_COLLECTION = "PER_COLLECTION"

# Helper roles stored on objects.
ROLE_NONE = "NONE"
ROLE_COLLISION = "COLLISION"
ROLE_SOCKET = "SOCKET"
ROLE_LOD = "LOD"

# Collision shapes and the Unreal prefix that identifies each one.
SHAPE_BOX = "BOX"
SHAPE_SPHERE = "SPHERE"
SHAPE_CAPSULE = "CAPSULE"
SHAPE_CONVEX = "CONVEX"
COLLISION_PREFIXES = {
    SHAPE_BOX: "UBX_",
    SHAPE_SPHERE: "USP_",
    SHAPE_CAPSULE: "UCP_",
    SHAPE_CONVEX: "UCX_",
}
PREFIX_TO_SHAPE = {prefix: shape for shape, prefix in COLLISION_PREFIXES.items()}
SOCKET_PREFIX = "SOCKET_"
LOD_TOKEN = "_LOD"

# Name used for the staged armature object. Unreal drops an FBX root node with
# exactly this name instead of turning it into an extra root bone (verified in
# UE 5.6.1 and 5.8.3, see docs/compatibility.md).
STAGED_ARMATURE_NAME = "Armature"

# Origin (pivot) policy.
ORIGIN_OBJECT = "OBJECT"
ORIGIN_WORLD = "WORLD"

# Animation policies.
NLA_ACTION_ONLY = "ACTION_ONLY"
NLA_SCENE = "SCENE"
ROOT_MOTION_NONE = "NONE"
ROOT_MOTION_ROOT_BONE = "ROOT_BONE"
ROOT_MOTION_IN_PLACE = "IN_PLACE"
ROOT_MOTION_OBJECT_TO_ROOT = "OBJECT_TO_ROOT"
FRAME_RANGE_ACTION = "ACTION"
FRAME_RANGE_SCENE = "SCENE"
FRAME_RANGE_CUSTOM = "CUSTOM"

# LOD collision layout. Unreal 5.8 matches LOD-group collision against the LOD
# group node name (hull at the root); Unreal 5.6 against the LOD0 node name and
# only cleanly when the hull is a child of LOD0. No single FBX satisfies both
# (an unmatched hull becomes render geometry), so PER_ENGINE writes the 5.8
# layout as the main file plus a ``.ue56.fbx`` variant the importer picks on 5.6.
LOD_COLLISION_PER_ENGINE = "PER_ENGINE"
LOD_COLLISION_GROUP = "GROUP"
LOD_COLLISION_LOD0 = "LOD0"
UE56_VARIANT_SUFFIX = ".ue56"

# Reimport policy for assets whose Blender source was renamed.
REIMPORT_UPDATE_EXISTING = "UPDATE_EXISTING"
REIMPORT_FOLLOW_RENAME = "FOLLOW_RENAME"

# Destinations.
DEST_DISK = "DISK"
DEST_SCRIPT = "SCRIPT"

# Severities.
SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

# Unreal coordinate conversion. Blender (x, y, z) in metres maps to Unreal
# (x, -y, z) in centimetres for the default FBX axis settings.
UNREAL_CM_PER_METRE = 100.0

# Default naming prefixes for Unreal asset names.
DEFAULT_PREFIX_STATIC = "SM_"
DEFAULT_PREFIX_SKELETAL = "SK_"
DEFAULT_PREFIX_ANIMATION = "A_"

# Unreal mount points that must never be written to.
FORBIDDEN_MOUNT_POINTS = frozenset({"Engine", "Script", "Temp", "Memory", "Config"})

# Default maximum length for sanitized asset names.
DEFAULT_MAX_NAME_LENGTH = 64

# Property group attribute name used on Blender IDs.
PROP_ATTR = "uex"

# Snapshot name of a scene's master ("Scene Collection"), which is not an ID.
MASTER_COLLECTION = "<Scene Collection>"
