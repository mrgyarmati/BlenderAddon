# SPDX-License-Identifier: GPL-3.0-or-later
"""Unreal Export Bridge: validated FBX export from Blender 5.2 to Unreal Engine 5.6+.

The package root deliberately avoids importing ``bpy`` at module level so the
pure domain layer (``domain/``, ``services/manifest.py`` ...) can be imported by
unit tests outside Blender. Blender only needs ``register``/``unregister``.
"""

if "_loaded" in globals():
    # "Reload Scripts" re-executes this module: reload submodules in dependency order.
    import importlib
    import sys

    _ORDER = (
        "constants",
        "domain.models",
        "domain.naming",
        "domain.unreal_math",
        "domain.discovery",
        "domain.validation",
        "domain.planning",
        "services.manifest",
        "services.logging",
        "services.unreal_script",
        "services.context_guard",
        "services.ids",
        "services.mesh_stats",
        "services.scene_snapshot",
        "services.staging",
        "services.animation",
        "services.fbx_export",
        "services.collisions",
        "services.sockets",
        "services.lods",
        "services.rename",
        "services.fixes",
        "services.export_service",
        "preferences",
        "properties",
        "operators.common",
        "operators.validate",
        "operators.export",
        "operators.collision",
        "operators.socket",
        "operators.lod",
        "operators.rename",
        "operators.results",
        "panels.common",
        "panels.main",
        "panels.validation",
        "panels.results",
        "registration",
    )
    for _name in _ORDER:
        _module = sys.modules.get(__name__ + "." + _name)
        if _module is not None:
            importlib.reload(_module)

_loaded = True


def register():
    from . import registration

    registration.register()


def unregister():
    from . import registration

    registration.unregister()
