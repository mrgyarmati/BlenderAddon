# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender Bridge for Unreal Editor (Python, editor only).

Usage in the Unreal Python console::

    import blender_bridge
    receipt = blender_bridge.import_manifest(r"D:/Exports/unreal_export_manifest.json")

``importer.py`` is a verbatim copy of the Blender add-on's
``unreal_templates/importer_core.py`` (scripts/sync_unreal_plugin.py keeps it in
sync). This plugin registers no startup scripts, timers or network listeners.
"""

from .importer import IMPORTER_VERSION, BridgeImportError, run as import_manifest  # noqa: F401
