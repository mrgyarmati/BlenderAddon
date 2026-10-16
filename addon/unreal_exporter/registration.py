"""Centralized, idempotent registration.

Classes register in dependency order and unregister in reverse. Pointer
properties are attached after their PropertyGroups exist. A failure part-way
through registration rolls back whatever was registered.
"""

import bpy
from bpy.props import PointerProperty

from . import preferences, properties
from .operators import collision as op_collision
from .operators import export as op_export
from .operators import lod as op_lod
from .operators import rename as op_rename
from .operators import results as op_results
from .operators import socket as op_socket
from .operators import validate as op_validate
from .panels import common as pn_common
from .panels import main as pn_main
from .panels import results as pn_results
from .panels import validation as pn_validation

_MODULES = (
    properties,
    preferences,
    op_validate,
    op_export,
    op_collision,
    op_socket,
    op_lod,
    op_rename,
    op_results,
    pn_common,
    pn_main,
    pn_validation,
    pn_results,
)

_TRANSLATIONS = {"en_US": {}}

_registered_classes = []
_registered_pointers = []
_translations_registered = False


def _all_classes():
    for module in _MODULES:
        yield from module.CLASSES


def register():
    global _translations_registered
    if _registered_classes or _registered_pointers:
        unregister()
    try:
        for cls in _all_classes():
            bpy.utils.register_class(cls)
            _registered_classes.append(cls)
        for id_type, attr, group in properties.POINTERS:
            setattr(id_type, attr, PointerProperty(type=group))
            _registered_pointers.append((id_type, attr))
        bpy.app.translations.register(__package__, _TRANSLATIONS)
        _translations_registered = True
    except Exception:
        unregister()
        raise


def unregister():
    global _translations_registered
    if _translations_registered:
        try:
            bpy.app.translations.unregister(__package__)
        finally:
            _translations_registered = False
    while _registered_pointers:
        id_type, attr = _registered_pointers.pop()
        if hasattr(id_type, attr):
            delattr(id_type, attr)
    while _registered_classes:
        cls = _registered_classes.pop()
        if getattr(cls, "is_registered", False):
            bpy.utils.unregister_class(cls)


def all_classes():
    """Every class this add-on registers, in registration order (used by tests)."""
    return list(_all_classes())
