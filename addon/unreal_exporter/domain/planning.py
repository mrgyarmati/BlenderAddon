"""Build the immutable, deterministic :class:`ExportPlan` (pure).

The plan id is a SHA-256 of the canonical plan content. It excludes absolute
paths and timestamps, so exporting an unchanged scene twice yields the same id.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from .. import constants as C
from .models import ExportAsset, ExportPlan, ExportSettings, PlannedFile, SceneSnapshot

PLAN_VERSION = 1


def import_options(settings: ExportSettings) -> tuple:
    """Unreal-side import options shared by every asset in the plan."""
    options = {
        "import_materials": bool(settings.import_materials),
        "import_textures": bool(settings.import_textures),
        "build_nanite": bool(settings.build_nanite),
        "generate_lightmap_uvs": bool(settings.generate_lightmap_uvs),
        "one_convex_hull_per_ucx": bool(settings.one_convex_hull_per_ucx),
        "create_physics_asset": bool(settings.create_physics_asset),
        "import_morph_targets": bool(settings.export_morph_targets),
        "normals": "import_normals_and_tangents" if settings.export_tangents else "import_normals",
        "vertex_colors": "replace" if settings.export_vertex_colors else "ignore",
        "import_lods": True,
        "import_sockets": True,
        "auto_generate_collision": bool(settings.auto_generate_collision),
        "lod_collision_naming": settings.lod_collision_naming,
        "reimport_policy": settings.reimport_policy,
    }
    return tuple(sorted(options.items()))


def fbx_export_options(kind: str, settings: ExportSettings) -> dict:
    """Keyword arguments for ``bpy.ops.export_scene.fbx`` (minus file/collection).

    Staged data is already in centimetres in a scene whose unit scale is 0.01, so
    the exporter applies no node scaling (see docs/compatibility.md).
    """
    options = {
        "use_selection": False,
        "use_visible": False,
        "use_active_collection": False,
        "global_scale": 1.0,
        "apply_unit_scale": True,
        "apply_scale_options": "FBX_SCALE_NONE",
        "use_space_transform": True,
        "bake_space_transform": False,
        "axis_forward": "-Z",
        "axis_up": "Y",
        "use_mesh_modifiers": True,
        "use_mesh_modifiers_render": True,
        "mesh_smooth_type": settings.smoothing,
        "colors_type": "SRGB" if settings.export_vertex_colors else "NONE",
        "prioritize_active_color": False,
        "use_subsurf": False,
        "use_mesh_edges": False,
        "use_tspace": bool(settings.export_tangents),
        "use_triangles": bool(settings.triangulate),
        "use_custom_props": False,
        "add_leaf_bones": False,
        "primary_bone_axis": settings.primary_bone_axis,
        "secondary_bone_axis": settings.secondary_bone_axis,
        "use_armature_deform_only": bool(settings.deform_bones_only),
        "armature_nodetype": "NULL",
        "path_mode": "AUTO",
        "embed_textures": False,
        "batch_mode": "OFF",
        "use_metadata": True,
        "bake_anim": False,
    }
    if kind == C.KIND_STATIC_MESH:
        options["object_types"] = {"MESH", "EMPTY"}
    elif kind == C.KIND_SKELETAL_MESH:
        options["object_types"] = {"MESH", "ARMATURE", "EMPTY"}
    elif kind == C.KIND_ANIMATION:
        options["object_types"] = {"ARMATURE"}
        options.update({
            "bake_anim": True,
            "bake_anim_use_all_bones": True,
            "bake_anim_use_nla_strips": False,
            "bake_anim_use_all_actions": False,
            "bake_anim_force_startend_keying": True,
            "bake_anim_step": float(settings.sample_step),
            "bake_anim_simplify_factor": float(settings.simplify),
        })
    return options


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(v) for v in value)
    return value


def _hashable_settings(settings: ExportSettings) -> dict:
    data = asdict(settings)
    # Absolute machine paths and UI-only switches do not change what is exported.
    for key in ("export_root", "permitted_roots", "destination", "developer_mode", "debug_paths"):
        data.pop(key, None)
    return data


def compute_plan_id(assets, options, settings: ExportSettings, unit_scale: float, fps: float) -> str:
    payload = {
        "plan_version": PLAN_VERSION,
        "assets": [asdict(a) for a in assets],
        "import_options": dict(options),
        "settings": _hashable_settings(settings),
        "unit_scale": unit_scale,
        "fps": fps,
    }
    text = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_plan(snapshot: SceneSnapshot, assets, settings: ExportSettings) -> ExportPlan:
    ordered = tuple(sorted(assets, key=_import_order_key))
    files = tuple(PlannedFile(asset_id=a.id, kind=a.kind, relpath=a.file_relpath) for a in ordered)
    options = import_options(settings)
    plan_id = compute_plan_id(ordered, options, settings, snapshot.unit_scale, snapshot.fps)
    return ExportPlan(
        plan_version=PLAN_VERSION,
        plan_id=plan_id,
        blender_version=snapshot.blender_version,
        unreal_target=(C.UNREAL_MIN_VERSION, C.UNREAL_GATE_VERSION),
        output_root=settings.export_root,
        assets=ordered,
        files=files,
        import_options=options,
        settings=settings,
        unit_scale=snapshot.unit_scale,
    )


_KIND_ORDER = {C.KIND_STATIC_MESH: 0, C.KIND_SKELETAL_MESH: 1, C.KIND_ANIMATION: 2}


def _import_order_key(asset: ExportAsset):
    """Skeletal meshes import before animations that reference their skeletons."""
    return (_KIND_ORDER.get(asset.kind, 9), asset.unreal_path.lower(), asset.id)


def cm_per_unit(unit_scale: float) -> float:
    """Centimetres per Blender unit for a scene unit scale (metres per unit)."""
    return C.UNREAL_CM_PER_METRE * (unit_scale if unit_scale > 0 else 1.0)
