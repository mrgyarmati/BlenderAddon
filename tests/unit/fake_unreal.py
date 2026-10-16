"""A small fake of the ``unreal`` module for importer unit tests.

It enforces the property names that differ between Unreal 5.6 and 5.8 (taken
from introspection of both engines, tests/unreal/introspect_api.py) so adapter
mistakes fail here the same way they would in the editor.
"""

import types

VERSION = {"text": "5.8.3-58210709+++UE5+Release-5.8"}
SAVED_DIR = {"path": None}
LOGS = []
ASSETS = {}  # package path -> object
METADATA = {}  # (package path, tag) -> value
SCENARIOS = {}  # fbx basename -> dict(lods=, collisions=, sockets=[...], kind=)
IMPORT_CALLS = []

_ONLY_56 = {"combine_static_meshes", "combine_skeletal_meshes", "snap_to_closest_frame_boundary",
            # Present but deprecated in 5.8: setting it raises (seen in UE 5.8.3).
            "auto_detect_mesh_type"}
_ONLY_58 = {"combine_static_meshes_behavior", "combine_skeletal_meshes_behavior", "frame_alignment"}


def reset(version="5.8"):
    VERSION["text"] = {"5.6": "5.6.1-44394996+++UE5+Release-5.6",
                       "5.8": "5.8.3-58210709+++UE5+Release-5.8",
                       "5.5": "5.5.4-1+++UE5+Release-5.5"}[version]
    LOGS.clear()
    ASSETS.clear()
    METADATA.clear()
    SCENARIOS.clear()
    IMPORT_CALLS.clear()


def _is58():
    return VERSION["text"].startswith("5.8")


class _Enum:
    def __init__(self, name, *values):
        self._name = name
        for value in values:
            setattr(self, value, "%s.%s" % (name, value))


InterchangeCombineStaticMeshesBehavior = _Enum("CombineStatic", "ALL", "DO_NOT_COMBINE", "VISIBLE_ONLY")
InterchangeCombineSkeletalMeshesBehavior = _Enum("CombineSkeletal", "BY_SKELETON", "BY_SKELETON_VISIBLE_ONLY",
                                                 "DO_NOT_COMBINE")
InterchangeFrameAlignment = _Enum("FrameAlignment", "NONE", "SNAP_TO_FLOOR", "SNAP_TO_CLOSEST", "SNAP_TO_CEILING")
InterchangeMeshCollision = _Enum("MeshCollision", "NONE", "BOX", "SPHERE", "CAPSULE", "CONVEX18DOP")
InterchangeForceMeshType = _Enum("ForceMeshType", "IFMT_NONE", "IFMT_STATIC_MESH", "IFMT_SKELETAL_MESH")
InterchangeVertexColorImportOption = _Enum("VertexColor", "IVCIO_REPLACE", "IVCIO_IGNORE", "IVCIO_OVERRIDE")
InterchangeAnimationRange = _Enum("AnimationRange", "TIMELINE", "ANIMATED", "SET_RANGE")
ReimportStrategyFlags = _Enum("Reimport", "APPLY_NO_PROPERTIES", "APPLY_PIPELINE_PROPERTIES",
                              "APPLY_EDITOR_CHANGED_PROPERTIES")
RootMotionRootLock = _Enum("RootLock", "REF_POSE", "ANIM_FIRST_FRAME", "ZERO")


class _Props:
    _allowed = None

    def __init__(self, **props):
        self.__dict__["_props"] = dict(props)

    def set_editor_property(self, name, value):
        if self._allowed is not None and name not in self._allowed:
            raise Exception("%s: Failed to find property '%s'" % (type(self).__name__, name))
        if name in _ONLY_56 and _is58():
            raise Exception("%s: Failed to find property '%s' (5.8)" % (type(self).__name__, name))
        if name in _ONLY_58 and not _is58():
            raise Exception("%s: Failed to find property '%s' (5.6)" % (type(self).__name__, name))
        self._props[name] = value

    def get_editor_property(self, name):
        return self._props.get(name)


class Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


class Rotator:
    def __init__(self, roll=0.0, pitch=0.0, yaw=0.0):
        self.roll, self.pitch, self.yaw = roll, pitch, yaw


class InterchangeGenericTexturePipeline(_Props):
    pass


class InterchangeGenericMaterialPipeline(_Props):
    def __init__(self):
        super().__init__(texture_pipeline=InterchangeGenericTexturePipeline())


class InterchangeGenericCommonMeshesProperties(_Props):
    pass


class InterchangeGenericMeshPipeline(_Props):
    pass


class InterchangeGenericCommonSkeletalMeshesAndAnimationsProperties(_Props):
    pass


class InterchangeGenericAnimationPipeline(_Props):
    pass


class InterchangeGenericAssetsPipeline(_Props):
    def __init__(self):
        super().__init__(
            common_meshes_properties=InterchangeGenericCommonMeshesProperties(),
            mesh_pipeline=InterchangeGenericMeshPipeline(),
            common_skeletal_meshes_and_animations_properties=InterchangeGenericCommonSkeletalMeshesAndAnimationsProperties(),
            animation_pipeline=InterchangeGenericAnimationPipeline(),
            material_pipeline=InterchangeGenericMaterialPipeline(),
        )


class InterchangePipelineStackOverride(_Props):
    def __init__(self):
        super().__init__()
        self.pipelines = []

    def add_pipeline(self, pipeline):
        self.pipelines.append(pipeline)


class _Asset(_Props):
    def __init__(self, path):
        super().__init__()
        self._path = path

    def get_path_name(self):
        name = self._path.rsplit("/", 1)[-1]
        return "%s.%s" % (self._path, name)


class StaticMeshSocket(_Props):
    def __init__(self, outer=None):
        super().__init__(socket_name="", relative_location=Vector(), relative_rotation=Rotator(),
                         relative_scale=Vector(1, 1, 1))


class _AggGeom(_Props):
    pass


class _BodySetup(_Props):
    pass


class _StaticMaterial(_Props):
    pass


class StaticMesh(_Asset):
    def __init__(self, path, lods=1, collisions=None, sockets=(), materials=("Material_0",)):
        super().__init__(path)
        counts = {"box_elems": [], "sphere_elems": [], "sphyl_elems": [], "convex_elems": []}
        for key, value in (collisions or {}).items():
            counts[key] = [object()] * value
        self._props["body_setup"] = _BodySetup(agg_geom=_AggGeom(**counts))
        self._props["static_materials"] = [_StaticMaterial(material_slot_name=m) for m in materials]
        self._lods = lods
        self._sockets = []
        for spec in sockets:
            sock = StaticMeshSocket()
            sock.set_editor_property("socket_name", spec["name"])
            sock.set_editor_property("relative_location", Vector(*spec["loc"]))
            sock.set_editor_property("relative_rotation", Rotator(*spec["rot"]))
            self._sockets.append(sock)

    def get_num_lods(self):
        return self._lods

    def find_socket(self, name):
        for sock in self._sockets:
            if sock.get_editor_property("socket_name") == name:
                return sock
        return None

    def add_socket(self, socket):
        self._sockets.append(socket)


class Skeleton(_Asset):
    pass


class SkeletalMesh(_Asset):
    pass


class AnimSequence(_Asset):
    def __init__(self, path, length=1.0):
        super().__init__(path)
        self._length = length

    def get_play_length(self):
        return self._length


class AssetImportTask(_Props):
    _allowed = {"filename", "destination_path", "destination_name", "automated", "replace_existing",
                "replace_existing_settings", "save", "async_", "options"}

    def __init__(self):
        super().__init__()
        self._objects = []

    def get_objects(self):
        return self._objects


class _AssetTools:
    def import_asset_tasks(self, tasks):
        import os

        for task in tasks:
            IMPORT_CALLS.append(task)
            base = os.path.basename(task.get_editor_property("filename"))
            scenario = SCENARIOS.get(base, {})
            path = task.get_editor_property("destination_path") + "/" + task.get_editor_property("destination_name")
            pipeline = task.get_editor_property("options").pipelines[0]
            force = pipeline.get_editor_property("common_meshes_properties").get_editor_property("force_all_mesh_as_type")
            skel_props = pipeline.get_editor_property("common_skeletal_meshes_and_animations_properties")
            objs = []
            if scenario.get("fail"):
                task._objects = []
                continue
            if skel_props.get_editor_property("import_only_animations"):
                obj = AnimSequence(path, length=scenario.get("length", 1.0))
                objs.append(obj)
            elif force == InterchangeForceMeshType.IFMT_SKELETAL_MESH:
                skel = Skeleton(path + "_Skeleton")
                obj = SkeletalMesh(path)
                obj.set_editor_property("skeleton", skel_props.get_editor_property("skeleton") or skel)
                objs.extend([skel, obj])
                ASSETS[skel._path.lower()] = skel
            else:
                existing = ASSETS.get(path.lower())
                obj = StaticMesh(path, lods=scenario.get("lods", 1), collisions=scenario.get("collisions"),
                                 sockets=scenario.get("sockets", ()))
                if existing is not None and isinstance(existing, StaticMesh):
                    obj._sockets = existing._sockets + [s for s in obj._sockets
                                                        if existing.find_socket(s.get_editor_property("socket_name")) is None]
                objs.append(obj)
            for o in objs:
                ASSETS[o._path.lower()] = o
            task._objects = objs


class AssetToolsHelpers:
    @staticmethod
    def get_asset_tools():
        return _AssetTools()


class EditorAssetLibrary:
    @staticmethod
    def does_asset_exist(path):
        return path.split(".")[0].lower() in ASSETS

    @staticmethod
    def load_asset(path):
        return ASSETS.get(path.split(".")[0].lower())

    @staticmethod
    def set_metadata_tag(obj, tag, value):
        METADATA[(obj._path.lower(), tag)] = value

    @staticmethod
    def get_metadata_tag(obj, tag):
        return METADATA.get((obj._path.lower(), tag), "")

    @staticmethod
    def save_loaded_asset(obj, only_if_dirty=True):
        return True

    @staticmethod
    def rename_asset(src, dst):
        obj = ASSETS.pop(src.lower(), None)
        if obj is None:
            return False
        for (path, tag), value in list(METADATA.items()):
            if path == src.lower():
                METADATA[(dst.lower(), tag)] = METADATA.pop((path, tag))
        obj._path = dst
        ASSETS[dst.lower()] = obj
        return True


class SystemLibrary:
    @staticmethod
    def get_engine_version():
        return VERSION["text"]


class Paths:
    @staticmethod
    def project_saved_dir():
        return SAVED_DIR["path"]


def log(msg):
    LOGS.append(("info", msg))


def log_warning(msg):
    LOGS.append(("warning", msg))


def log_error(msg):
    LOGS.append(("error", msg))


def install():
    """Register this module as ``unreal`` and return it."""
    import sys

    module = sys.modules[__name__]
    sys.modules["unreal"] = module
    return module


_ = types  # keep import for type hints readers
