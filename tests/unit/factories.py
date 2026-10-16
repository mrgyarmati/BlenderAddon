"""Builders for domain records used across unit tests."""

from dataclasses import replace

from unreal_exporter import constants as C
from unreal_exporter.domain.models import (
    ActionRecord,
    BoneRecord,
    CollectionRecord,
    ExportSettings,
    MeshStats,
    ModifierRecord,
    ObjectRecord,
    SceneSnapshot,
)


def stats(**kw):
    base = dict(
        vertex_count=8,
        polygon_count=6,
        triangle_count=12,
        uv_layers=("UVMap",),
        material_slots=("M_Default",),
        bounds_min=(-0.5, -0.5, -0.5),
        bounds_max=(0.5, 0.5, 0.5),
    )
    base.update(kw)
    return MeshStats(**base)


def mesh(name, **kw):
    kw.setdefault("mesh", stats())
    kw.setdefault("collections", ("Props",))
    kw.setdefault("uuid", "uuid-" + name)
    return ObjectRecord(name=name, type="MESH", **kw)


def empty(name, **kw):
    kw.setdefault("collections", ("Props",))
    kw.setdefault("uuid", "uuid-" + name)
    return ObjectRecord(name=name, type="EMPTY", **kw)


def armature(name, bones=("root", "spine", "head"), **kw):
    kw.setdefault("collections", ("Characters",))
    kw.setdefault("uuid", "uuid-" + name)
    recs = []
    parent = ""
    for bone in bones:
        recs.append(BoneRecord(name=bone, parent=parent, use_deform=True))
        parent = bone
    kw.setdefault("bones", tuple(recs))
    return ObjectRecord(name=name, type="ARMATURE", **kw)


def skinned(name, arm, **kw):
    kw.setdefault("modifiers", (ModifierRecord(name="Armature", type="ARMATURE", target=arm),))
    kw.setdefault("mesh", stats(vertex_groups=("root", "spine", "head"), max_bone_influences=2))
    kw.setdefault("collections", ("Characters",))
    return mesh(name, **kw)


def action(name, bones=("root", "spine"), start=1.0, end=24.0, **kw):
    kw.setdefault("uuid", "act-" + name)
    return ActionRecord(name=name, frame_start=start, frame_end=end, bone_names=tuple(bones), **kw)


def snapshot(*objects, collections=None, actions=(), **kw):
    if collections is None:
        names = {}
        for ob in objects:
            for coll in ob.collections:
                names.setdefault(coll, []).append(ob.name)
        collections = tuple(
            CollectionRecord(name=coll, uuid="coll-" + coll, objects=tuple(sorted(members)))
            for coll, members in sorted(names.items())
        )
        master = CollectionRecord(name=C.MASTER_COLLECTION, children=tuple(c.name for c in collections))
        collections = (master,) + collections
    kw.setdefault("blender_version", "5.2.0")
    return SceneSnapshot(objects=tuple(sorted(objects, key=lambda o: o.name)), collections=tuple(collections),
                         actions=tuple(actions), **kw)


def settings(**kw):
    kw.setdefault("export_root", "/tmp/uex_export")
    return ExportSettings(**kw)


def selected(record):
    return replace(record, selected=True)
