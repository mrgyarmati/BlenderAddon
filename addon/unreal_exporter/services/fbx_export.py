"""Write one staged asset with Blender's bundled FBX exporter.

The exporter runs with the staging scene as context and an explicit
``collection`` so exactly the staged export collection is written.
"""

import os

import bpy

from ..domain import planning


class FbxExportError(RuntimeError):
    pass


def write_fbx(session, filepath: str, kind: str, settings) -> None:
    """Export ``session.collection`` to ``filepath`` atomically."""
    options = planning.fbx_export_options(kind, settings)
    directory = os.path.dirname(filepath)
    os.makedirs(directory, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(filepath))
    temp_path = os.path.join(directory, "%s.__uex_tmp__%s" % (stem, ext or ".fbx"))
    options["filepath"] = temp_path
    options["collection"] = session.collection.name
    session.view_layer.update()
    try:
        with bpy.context.temp_override(scene=session.scene, view_layer=session.view_layer):
            result = bpy.ops.export_scene.fbx(**options)
        if "FINISHED" not in result:
            raise FbxExportError("Blender's FBX exporter returned %s." % sorted(result))
        if not os.path.isfile(temp_path) or os.path.getsize(temp_path) == 0:
            raise FbxExportError("The FBX exporter produced no file.")
        os.replace(temp_path, filepath)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
