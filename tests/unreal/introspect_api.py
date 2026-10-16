"""Dump the Unreal Python API surface the generated importer relies on.

Run inside Unreal Editor (commandlet or editor). Writes JSON to the path given as
the first script argument so the 5.6 and 5.8 surfaces can be diffed offline.
"""
import json
import sys

import unreal

CLASSES = [
    "AssetImportTask",
    "AssetToolsHelpers",
    "EditorAssetLibrary",
    "StaticMeshEditorSubsystem",
    "InterchangeManager",
    "InterchangePipelineStackOverride",
    "InterchangeGenericAssetsPipeline",
    "InterchangeGenericCommonMeshesProperties",
    "InterchangeGenericCommonSkeletalMeshesAndAnimationsProperties",
    "InterchangeGenericMeshPipeline",
    "InterchangeGenericAnimationPipeline",
    "InterchangeGenericMaterialPipeline",
    "InterchangeGenericTexturePipeline",
    "InterchangeMeshCollision",
    "InterchangeCombineStaticMeshesBehavior",
    "InterchangeCombineSkeletalMeshesBehavior",
    "InterchangeSkeletalMeshContentType",
    "InterchangeForceMeshType",
    "InterchangeAnimationRange",
    "ReimportStrategyFlags",
    "InterchangeMaterialImportOption",
    "StaticMesh",
    "StaticMeshSocket",
    "SkeletalMesh",
    "Skeleton",
    "AnimSequence",
    "BodySetup",
    "KAggregateGeom",
    "SystemLibrary",
    "FbxImportUI",
]


def describe(name):
    cls = getattr(unreal, name, None)
    if cls is None:
        return None
    members = sorted(m for m in dir(cls) if not m.startswith("_"))
    return members


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else None
    data = {
        "engine_version": unreal.SystemLibrary.get_engine_version(),
        "classes": {name: describe(name) for name in CLASSES},
    }
    text = json.dumps(data, indent=1, sort_keys=True)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text)
    unreal.log("INTROSPECTION_DONE " + data["engine_version"])


main()
