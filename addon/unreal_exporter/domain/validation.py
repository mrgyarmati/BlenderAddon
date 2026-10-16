"""Validation rules (pure). See docs/architecture.md, "Validation catalogue".

Each rule reads the snapshot, the discovered assets and the settings and returns
:class:`ValidationIssue` records. Blocking errors stop the export unless the
developer-mode override is enabled; warnings never block.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .. import constants as C
from . import naming
from .discovery import DiscoveryResult
from .models import ExportAsset, ExportSettings, ObjectRecord, SceneSnapshot, ValidationIssue

# Fix identifiers understood by services/fixes.py.
FIX_RENAME_HELPERS = "RENAME_HELPERS"
FIX_REPAIR_UUIDS = "REPAIR_UUIDS"
FIX_REMOVE_EMPTY_SLOTS = "REMOVE_EMPTY_SLOTS"

_ROT_EPS = 1e-4
_SCALE_EPS = 1e-4
_BOX_FIT_TOLERANCE = 1e-3
_SPHERE_FIT_TOLERANCE = 2e-2
_UV1_AREA_TOLERANCE = 1.01
_MAX_UNREAL_PATH = 200
_MAX_FILE_PATH = 240

_SEVERITY_ORDER = {C.SEVERITY_ERROR: 0, C.SEVERITY_WARNING: 1, C.SEVERITY_INFO: 2}


@dataclass(frozen=True)
class ValidationEnv:
    """Facts only the Blender side can know (filesystem, environment)."""

    export_root_writable: bool = True
    export_root_reason: str = ""


def _issue(code, severity, message, obj="", fix="", asset="", **details):
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        object_id=obj,
        fix_id=fix,
        details=tuple(sorted((k, v) for k, v in details.items())),
        asset_id=asset,
    )


def sort_issues(issues) -> tuple:
    unique = []
    seen = set()
    for issue in issues:
        key = (issue.code, issue.severity, issue.object_id, issue.asset_id, issue.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    unique.sort(key=lambda i: (_SEVERITY_ORDER.get(i.severity, 9), i.asset_id, i.object_id, i.code, i.message))
    return tuple(unique)


def has_blocking(issues) -> bool:
    return any(i.is_blocking for i in issues)


def can_export(issues, settings: ExportSettings) -> bool:
    return settings.developer_mode or not has_blocking(issues)


def summarize(issues) -> dict:
    counts = {C.SEVERITY_ERROR: 0, C.SEVERITY_WARNING: 0, C.SEVERITY_INFO: 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts


# ---------------------------------------------------------------- entry point


def validate(snapshot: SceneSnapshot, discovery: DiscoveryResult, settings: ExportSettings,
             env: ValidationEnv = ValidationEnv()) -> tuple:
    issues = list(discovery.issues)
    issues.extend(_global_rules(snapshot, discovery, settings, env))
    for asset in discovery.assets:
        if asset.kind == C.KIND_STATIC_MESH:
            issues.extend(_static_rules(snapshot, discovery, settings, asset))
        elif asset.kind == C.KIND_SKELETAL_MESH:
            issues.extend(_skeletal_rules(snapshot, discovery, settings, asset))
        elif asset.kind == C.KIND_ANIMATION:
            issues.extend(_animation_rules(snapshot, settings, asset))
    return sort_issues(issues)


# ---------------------------------------------------------------- global


def _global_rules(snapshot, discovery, settings, env):
    out = []
    for problem in naming.validate_unreal_root(settings.unreal_root):
        out.append(_issue("E_UNREAL_ROOT", C.SEVERITY_ERROR, problem))

    root = settings.export_root
    if not root:
        out.append(_issue("E_EXPORT_ROOT_MISSING", C.SEVERITY_ERROR,
                          env.export_root_reason or "No export directory is set."))
    else:
        if settings.permitted_roots and not any(naming.is_within(p, root) for p in settings.permitted_roots):
            out.append(_issue("E_OUTPUT_OUTSIDE_ROOT", C.SEVERITY_ERROR,
                              "The export directory is outside the permitted export roots set in the preferences."))
        if not env.export_root_writable:
            out.append(_issue("E_PATH_UNWRITABLE", C.SEVERITY_ERROR,
                              "The export directory is not writable%s." % (
                                  (": " + env.export_root_reason) if env.export_root_reason else "")))

    by_path = defaultdict(list)
    for asset in discovery.assets:
        by_path[asset.unreal_path.lower()].append(asset)
        if root:
            try:
                full = naming.safe_join(root, asset.file_relpath)
            except naming.PathEscapeError as exc:
                out.append(_issue("E_OUTPUT_OUTSIDE_ROOT", C.SEVERITY_ERROR, str(exc), asset=asset.id,
                                  obj=asset.source_name))
            else:
                if len(full) > _MAX_FILE_PATH:
                    out.append(_issue("W_LONG_PATH", C.SEVERITY_WARNING,
                                      "File path for '%s' is %d characters long and may fail on Windows."
                                      % (asset.asset_name, len(full)), asset=asset.id, obj=asset.source_name))
        if len(asset.unreal_path) > _MAX_UNREAL_PATH:
            out.append(_issue("W_LONG_PATH", C.SEVERITY_WARNING,
                              "Unreal path '%s' is longer than %d characters." % (asset.unreal_path, _MAX_UNREAL_PATH),
                              asset=asset.id, obj=asset.source_name))
    for path, assets in sorted(by_path.items()):
        if len(assets) > 1:
            sources = ", ".join(sorted(a.source_name for a in assets))
            for asset in assets:
                out.append(_issue("E_DUPLICATE_UNREAL_PATH", C.SEVERITY_ERROR,
                                  "Several assets would be written to %s (%s). Rename one source or set a "
                                  "folder override." % (asset.unreal_path, sources), asset=asset.id,
                                  obj=asset.source_name))

    if settings.import_materials or settings.import_textures:
        out.append(_issue("W_MATERIALS_REQUESTED", C.SEVERITY_WARNING,
                          "FBX carries only basic material data; Unreal will create simple materials. "
                          "Material slots are always preserved."))

    uuids = defaultdict(list)
    for ob in snapshot.objects:
        if ob.uuid:
            uuids[ob.uuid].append(ob.name)
    for uuid, names in sorted(uuids.items()):
        if len(names) > 1:
            out.append(_issue("W_DUPLICATE_UUID", C.SEVERITY_WARNING,
                              "Objects %s share one export id (usually from duplicating); ids are repaired "
                              "automatically on export." % ", ".join(sorted(names)), obj=sorted(names)[0],
                              fix=FIX_REPAIR_UUIDS))
    if settings.sample_step <= 0:
        out.append(_issue("E_SAMPLE_STEP", C.SEVERITY_ERROR, "Animation sample step must be greater than zero."))
    return out


# ---------------------------------------------------------------- transforms


def _is_identity_rotation(q) -> bool:
    w, x, y, z = q
    return abs(abs(w) - 1.0) < _ROT_EPS and abs(x) < _ROT_EPS and abs(y) < _ROT_EPS and abs(z) < _ROT_EPS


def _transform_rules(ob: ObjectRecord, asset: ExportAsset, baked: bool):
    out = []
    scale = ob.scale
    rot_applied = _is_identity_rotation(ob.rotation_quaternion)
    scale_applied = all(abs(s - 1.0) < _SCALE_EPS for s in scale)
    if not rot_applied or not scale_applied:
        what = " and ".join(w for w, ok in (("rotation", rot_applied), ("scale", scale_applied)) if not ok)
        hint = ("it is baked into the exported data, so the Unreal asset's local axes follow the world axes"
                if baked else "Unreal imports it into the skeleton's reference pose")
        out.append(_issue("W_UNAPPLIED_TRANSFORM", C.SEVERITY_WARNING,
                          "'%s' has unapplied %s; %s. Apply transforms in Blender for predictable pivots."
                          % (ob.name, what, hint), obj=ob.name, asset=asset.id))
    if any(s < 0 for s in scale):
        out.append(_issue("W_NEGATIVE_SCALE", C.SEVERITY_WARNING,
                          "'%s' has negative scale; faces are flipped back on export but mirrored pivots are "
                          "easy to get wrong." % ob.name, obj=ob.name, asset=asset.id))
    abs_scale = [abs(s) for s in scale]
    if max(abs_scale) - min(abs_scale) > _SCALE_EPS * max(1.0, max(abs_scale)):
        out.append(_issue("W_NON_UNIFORM_SCALE", C.SEVERITY_WARNING,
                          "'%s' has non-uniform scale %s." % (ob.name, _fmt_vec(scale)), obj=ob.name,
                          asset=asset.id))
    return out


def _fmt_vec(values) -> str:
    return "(" + ", ".join("%.3g" % v for v in values) + ")"


# ---------------------------------------------------------------- geometry


def _mesh_rules(ob: ObjectRecord, asset: ExportAsset, settings: ExportSettings, role: str = "render"):
    out = []
    stats = ob.mesh
    if stats is None or stats.polygon_count == 0:
        out.append(_issue("E_MISSING_DATA", C.SEVERITY_ERROR,
                          "'%s' has no polygons to export." % ob.name, obj=ob.name, asset=asset.id))
        return out
    if role != "render":
        return out
    if stats.non_manifold_edge_count:
        out.append(_issue("W_NON_MANIFOLD", C.SEVERITY_WARNING,
                          "'%s' has %d non-manifold edges." % (ob.name, stats.non_manifold_edge_count),
                          obj=ob.name, asset=asset.id))
    if stats.degenerate_face_count:
        out.append(_issue("W_DEGENERATE_FACES", C.SEVERITY_WARNING,
                          "'%s' has %d degenerate (zero-area) faces; Unreal may remove them."
                          % (ob.name, stats.degenerate_face_count), obj=ob.name, asset=asset.id))
    if not stats.uv_layers:
        out.append(_issue("W_MISSING_UV0", C.SEVERITY_WARNING,
                          "'%s' has no UV map; texturing and lightmaps will not work." % ob.name,
                          obj=ob.name, asset=asset.id))
    elif len(stats.uv_layers) > 1 and (stats.uv1_area_sum > _UV1_AREA_TOLERANCE or stats.uv1_out_of_bounds):
        out.append(_issue("W_LIGHTMAP_UV_OVERLAP", C.SEVERITY_WARNING,
                          "'%s' second UV map '%s' overlaps or leaves the 0-1 range; Unreal uses UV1 for "
                          "lightmaps." % (ob.name, stats.uv_layers[1]), obj=ob.name, asset=asset.id))
    if len(stats.material_slots) > settings.max_material_slots:
        out.append(_issue("W_MATERIAL_SLOTS", C.SEVERITY_WARNING,
                          "'%s' uses %d material slots (more than %d); each slot is a draw call in Unreal."
                          % (ob.name, len(stats.material_slots), settings.max_material_slots),
                          obj=ob.name, asset=asset.id))
    if any(not m for m in stats.material_slots):
        out.append(_issue("W_EMPTY_MATERIAL_SLOT", C.SEVERITY_WARNING,
                          "'%s' has empty material slots; Unreal will name them generically." % ob.name,
                          obj=ob.name, asset=asset.id, fix=FIX_REMOVE_EMPTY_SLOTS))
    if stats.ngon_count and not settings.triangulate:
        severity = C.SEVERITY_WARNING
        msg = "'%s' has %d n-gons that Unreal will triangulate unpredictably." % (ob.name, stats.ngon_count)
        if settings.export_tangents:
            msg += " Tangent export needs triangles or quads; enable Triangulate."
        out.append(_issue("W_NGONS", severity, msg, obj=ob.name, asset=asset.id))
    return out


def _bounds_of(snapshot, names):
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for name in names:
        rec = snapshot.object(name)
        if rec is None or rec.mesh is None or rec.mesh.polygon_count == 0:
            continue
        for i in range(3):
            lo[i] = min(lo[i], rec.mesh.bounds_min[i])
            hi[i] = max(hi[i], rec.mesh.bounds_max[i])
    if lo[0] == math.inf:
        return None
    return tuple(lo), tuple(hi)


def _distance_to_box(point, box) -> float:
    lo, hi = box
    d2 = 0.0
    for i in range(3):
        if point[i] < lo[i]:
            d2 += (lo[i] - point[i]) ** 2
        elif point[i] > hi[i]:
            d2 += (point[i] - hi[i]) ** 2
    return math.sqrt(d2)


# ---------------------------------------------------------------- static


def _static_rules(snapshot, discovery, settings, asset):
    out = []
    helpers = discovery.helpers
    for name in asset.mesh_objects:
        ob = snapshot.object(name)
        if ob is None:
            continue
        out.extend(_mesh_rules(ob, asset, settings))
        if ob.mesh is not None and ob.mesh.shape_keys:
            out.append(_issue("I_STATIC_SHAPE_KEYS", C.SEVERITY_INFO,
                              "'%s' has shape keys; static meshes do not carry morph targets, the current "
                              "shape is exported." % name, obj=name, asset=asset.id))
    origin = snapshot.object(asset.origin_object) if asset.origin_object else None
    if origin is not None:
        out.extend(_transform_rules(origin, asset, baked=True))

    out.extend(_collision_rules(snapshot, helpers, asset))
    out.extend(_socket_rules(snapshot, helpers, settings, asset))
    out.extend(_lod_rules(snapshot, helpers, settings, asset))
    return out


def _collision_rules(snapshot, helpers, asset):
    out = []
    for entry in asset.collisions:
        ob = snapshot.object(entry.object_name)
        if ob is None:
            continue
        mismatch = helpers.mismatched.get(entry.object_name)
        if mismatch:
            owner, _kind = mismatch
            out.append(_issue("E_COLLISION_NAME_MISMATCH", C.SEVERITY_ERROR,
                              "Collision '%s' belongs to '%s' but its name does not contain that exact mesh name "
                              "(expected %s...)." % (entry.object_name, owner,
                                                     naming.collision_object_name(entry.shape, owner, 0)[:-2]),
                              obj=entry.object_name, asset=asset.id, fix=FIX_RENAME_HELPERS))
        stats = ob.mesh
        if stats is None or stats.polygon_count == 0:
            out.append(_issue("E_MISSING_DATA", C.SEVERITY_ERROR,
                              "Collision '%s' has no polygons." % entry.object_name, obj=entry.object_name,
                              asset=asset.id))
            continue
        scale = [abs(s) for s in ob.scale]
        non_uniform = max(scale) - min(scale) > _SCALE_EPS * max(1.0, max(scale))
        if entry.shape in (C.SHAPE_BOX, C.SHAPE_SPHERE, C.SHAPE_CAPSULE) and non_uniform:
            out.append(_issue("W_PRIMITIVE_SCALE", C.SEVERITY_WARNING,
                              "Primitive collision '%s' has non-uniform scale; Unreal primitives are unreliable "
                              "under non-uniform scaling, prefer a UCX hull." % entry.object_name,
                              obj=entry.object_name, asset=asset.id))
        if entry.shape == C.SHAPE_BOX and stats.box_fit_error > _BOX_FIT_TOLERANCE:
            out.append(_issue("W_PRIMITIVE_DEFORMED", C.SEVERITY_WARNING,
                              "Box collision '%s' is not an undeformed rectangular box (fit error %.1f%%)."
                              % (entry.object_name, stats.box_fit_error * 100), obj=entry.object_name,
                              asset=asset.id))
        if entry.shape == C.SHAPE_SPHERE and stats.sphere_fit_error > _SPHERE_FIT_TOLERANCE:
            out.append(_issue("W_PRIMITIVE_DEFORMED", C.SEVERITY_WARNING,
                              "Sphere collision '%s' is not spherical (fit error %.1f%%)."
                              % (entry.object_name, stats.sphere_fit_error * 100), obj=entry.object_name,
                              asset=asset.id))
        if entry.shape == C.SHAPE_CONVEX and not stats.is_convex:
            out.append(_issue("W_UCX_NOT_CONVEX", C.SEVERITY_WARNING,
                              "Convex collision '%s' is not convex; Unreal will wrap it in a hull. Split it into "
                              "several UCX objects to keep openings." % entry.object_name,
                              obj=entry.object_name, asset=asset.id))
        if stats.non_manifold_edge_count:
            out.append(_issue("W_UCX_OPEN", C.SEVERITY_WARNING,
                              "Collision '%s' is not closed (%d open edges)." % (entry.object_name,
                                                                              stats.non_manifold_edge_count),
                              obj=entry.object_name, asset=asset.id))
    return out


def _socket_rules(snapshot, helpers, settings, asset):
    out = []
    seen = {}
    bounds = _bounds_of(snapshot, asset.mesh_objects)
    for entry in asset.sockets:
        ob = snapshot.object(entry.object_name)
        if ob is None:
            continue
        mismatch = helpers.mismatched.get(entry.object_name)
        if mismatch:
            out.append(_issue("W_SOCKET_NAME_MISMATCH", C.SEVERITY_WARNING,
                              "Socket '%s' belongs to '%s' but is not named SOCKET_%s_<Name>."
                              % (entry.object_name, mismatch[0], mismatch[0]), obj=entry.object_name,
                              asset=asset.id, fix=FIX_RENAME_HELPERS))
        clean = naming.sanitize_name(entry.socket_name, 0).value
        key = clean.lower()
        if not clean:
            out.append(_issue("E_INVALID_NAME", C.SEVERITY_ERROR,
                              "Socket '%s' has no usable name." % entry.object_name, obj=entry.object_name,
                              asset=asset.id))
        elif key in seen:
            out.append(_issue("E_DUPLICATE_SOCKET", C.SEVERITY_ERROR,
                              "Sockets '%s' and '%s' both export as '%s'." % (seen[key], entry.object_name, clean),
                              obj=entry.object_name, asset=asset.id))
        else:
            seen[key] = entry.object_name
        if bounds is not None:
            tolerance = settings.socket_distance_tolerance / max(snapshot.unit_scale, 1e-9)
            distance = _distance_to_box(ob.location, bounds)
            if distance > tolerance:
                out.append(_issue("W_SOCKET_FAR", C.SEVERITY_WARNING,
                                  "Socket '%s' is %.2f units outside the bounds of '%s'."
                                  % (entry.object_name, distance, asset.source_name), obj=entry.object_name,
                                  asset=asset.id))
    return out


def _lod_rules(snapshot, helpers, settings, asset):
    out = []
    if not asset.lods:
        return out
    indices = defaultdict(list)
    for lod in asset.lods:
        indices[lod.index].append(lod.object_name)
    for index, names in sorted(indices.items()):
        if index < 1:
            out.append(_issue("E_LOD_DUPLICATE_INDEX", C.SEVERITY_ERROR,
                              "'%s' claims LOD%d, but LOD0 is the asset root '%s'." % (names[0], index,
                                                                                     asset.source_name),
                              obj=names[0], asset=asset.id))
        if len(names) > 1:
            out.append(_issue("E_LOD_DUPLICATE_INDEX", C.SEVERITY_ERROR,
                              "LOD%d is assigned to several objects: %s." % (index, ", ".join(sorted(names))),
                              obj=sorted(names)[0], asset=asset.id))
    positive = sorted(i for i in indices if i >= 1)
    if positive != list(range(1, len(positive) + 1)):
        out.append(_issue("W_LOD_GAP", C.SEVERITY_WARNING,
                          "LOD indices of '%s' have gaps (%s); Unreal renumbers them in order."
                          % (asset.source_name, ", ".join(str(i) for i in sorted(indices))), asset=asset.id,
                          obj=asset.source_name))
    root = snapshot.object(asset.mesh_objects[0]) if asset.mesh_objects else None
    previous_tris = root.mesh.triangle_count if (root is not None and root.mesh is not None) else None
    root_slots = len(root.mesh.material_slots) if (root is not None and root.mesh is not None) else None
    for lod in sorted(asset.lods, key=lambda e: e.index):
        ob = snapshot.object(lod.object_name)
        if ob is None:
            continue
        mismatch = helpers.mismatched.get(lod.object_name)
        if mismatch:
            out.append(_issue("W_LOD_NAME_MISMATCH", C.SEVERITY_WARNING,
                              "LOD object '%s' is not named %s." % (lod.object_name,
                                                                    naming.lod_object_name(
                                                                        naming.asset_base_name(mismatch[0]),
                                                                        lod.index)),
                              obj=lod.object_name, asset=asset.id, fix=FIX_RENAME_HELPERS))
        stats = ob.mesh
        if stats is None or stats.polygon_count == 0:
            out.append(_issue("E_MISSING_DATA", C.SEVERITY_ERROR, "LOD '%s' has no polygons." % lod.object_name,
                              obj=lod.object_name, asset=asset.id))
            continue
        if previous_tris is not None and stats.triangle_count >= previous_tris:
            out.append(_issue("W_LOD_TRIS_NOT_DECREASING", C.SEVERITY_WARNING,
                              "LOD%d '%s' has %d triangles, not fewer than the previous LOD (%d)."
                              % (lod.index, lod.object_name, stats.triangle_count, previous_tris),
                              obj=lod.object_name, asset=asset.id))
        previous_tris = stats.triangle_count
        if root_slots is not None and len(stats.material_slots) > root_slots:
            out.append(_issue("W_LOD_MATERIALS", C.SEVERITY_WARNING,
                              "LOD '%s' uses more material slots than LOD0." % lod.object_name,
                              obj=lod.object_name, asset=asset.id))
        if root is not None and _distance(ob.location, root.location) > 1e-4:
            out.append(_issue("W_LOD_OFFSET", C.SEVERITY_WARNING,
                              "LOD '%s' origin is not at the LOD0 origin; the offset is kept in Unreal."
                              % lod.object_name, obj=lod.object_name, asset=asset.id))
        if asset.kind == C.KIND_SKELETAL_MESH and asset.armature not in ob.armature_targets:
            out.append(_issue("E_LOD_SKELETON_MISMATCH", C.SEVERITY_ERROR,
                              "LOD '%s' is not deformed by '%s'; all LODs must share the skeleton root."
                              % (lod.object_name, asset.armature), obj=lod.object_name, asset=asset.id))
    return out


def _distance(a, b) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


# ---------------------------------------------------------------- skeletal


def exported_bones(arm: ObjectRecord, deform_only: bool) -> tuple:
    """Bones the FBX exporter writes: deform bones plus their ancestors (or all bones)."""
    if not deform_only:
        return tuple(b.name for b in arm.bones)
    parent_of = {b.name: b.parent for b in arm.bones}
    keep = set()
    for bone in arm.bones:
        if bone.use_deform:
            name = bone.name
            while name and name not in keep:
                keep.add(name)
                name = parent_of.get(name, "")
    return tuple(b.name for b in arm.bones if b.name in keep)


def _bone_rules(arm: ObjectRecord, asset: ExportAsset, settings: ExportSettings):
    out = []
    if not arm.bones:
        out.append(_issue("E_MISSING_DATA", C.SEVERITY_ERROR, "Armature '%s' has no bones." % arm.name,
                          obj=arm.name, asset=asset.id))
        return out
    lowered = defaultdict(list)
    for bone in arm.bones:
        lowered[bone.name.lower()].append(bone.name)
    for names in lowered.values():
        if len(names) > 1:
            out.append(_issue("E_DUPLICATE_BONES", C.SEVERITY_ERROR,
                              "Bones %s differ only by case; Unreal bone names are case-insensitive."
                              % ", ".join(sorted(names)), obj=arm.name, asset=asset.id))
    if any(b.name == C.STAGED_ARMATURE_NAME for b in arm.bones):
        out.append(_issue("E_DUPLICATE_BONES", C.SEVERITY_ERROR,
                          "A bone named '%s' clashes with the armature root node Unreal strips on import."
                          % C.STAGED_ARMATURE_NAME, obj=arm.name, asset=asset.id))
    exported = set(exported_bones(arm, settings.deform_bones_only))
    if not exported:
        out.append(_issue("E_MISSING_DATA", C.SEVERITY_ERROR,
                          "Armature '%s' has no deform bones to export." % arm.name, obj=arm.name, asset=asset.id))
        return out
    parent_of = {b.name: b.parent for b in arm.bones}
    roots = sorted(b for b in exported if not parent_of.get(b) or parent_of.get(b) not in exported)
    if len(roots) > 1:
        out.append(_issue("E_MULTIPLE_ROOT_BONES", C.SEVERITY_ERROR,
                          "Armature '%s' exports %d root bones (%s); Unreal needs a single root bone."
                          % (arm.name, len(roots), ", ".join(roots[:5])), obj=arm.name, asset=asset.id))
    return out


def _skeletal_rules(snapshot, discovery, settings, asset):
    out = []
    arm = snapshot.object(asset.armature)
    if arm is None or arm.type != "ARMATURE":
        out.append(_issue("E_MISSING_ARMATURE", C.SEVERITY_ERROR,
                          "Skeletal asset '%s' has no armature." % asset.asset_name, asset=asset.id))
        return out
    out.extend(_bone_rules(arm, asset, settings))
    out.extend(_transform_rules(arm, asset, baked=False))
    bone_names = {b.name for b in arm.bones}
    deform_names = {b.name for b in arm.bones if b.use_deform} if settings.deform_bones_only else bone_names
    for name in asset.mesh_objects:
        ob = snapshot.object(name)
        if ob is None:
            continue
        out.extend(_mesh_rules(ob, asset, settings))
        stats = ob.mesh
        if stats is None:
            continue
        if stats.unweighted_vertex_count:
            out.append(_issue("E_UNWEIGHTED_VERTICES", C.SEVERITY_ERROR,
                              "'%s' has %d vertices without weights to deform bones of '%s'."
                              % (name, stats.unweighted_vertex_count, arm.name), obj=name, asset=asset.id))
        if stats.max_bone_influences > settings.max_bone_influences:
            out.append(_issue("W_BONE_INFLUENCES", C.SEVERITY_WARNING,
                              "'%s' has vertices with %d bone influences (limit %d); Unreal will drop the "
                              "smallest weights." % (name, stats.max_bone_influences, settings.max_bone_influences),
                              obj=name, asset=asset.id))
        stray = sorted(g for g in stats.vertex_groups if g in bone_names and g not in deform_names)
        if stray:
            out.append(_issue("I_NON_DEFORM_GROUPS", C.SEVERITY_INFO,
                              "'%s' has weights on non-deform bones (%s) that are not exported."
                              % (name, ", ".join(stray[:5])), obj=name, asset=asset.id))
        if stats.shape_keys and not settings.export_morph_targets:
            out.append(_issue("W_SHAPE_KEYS_DISABLED", C.SEVERITY_WARNING,
                              "'%s' has shape keys but morph-target export is disabled." % name,
                              obj=name, asset=asset.id))
        if stats.shape_keys and settings.export_morph_targets:
            live = [m for m in ob.modifiers if m.enabled and m.type != "ARMATURE"]
            if live:
                out.append(_issue("W_MORPH_WITH_MODIFIERS", C.SEVERITY_WARNING,
                                  "'%s' exports morph targets, so its %s modifier(s) are not applied."
                                  % (name, ", ".join(m.type.title() for m in live)), obj=name, asset=asset.id))
    out.extend(_lod_rules(snapshot, discovery.helpers, settings, asset))
    return out


# ---------------------------------------------------------------- animation


def _animation_rules(snapshot, settings, asset):
    out = []
    if not asset.skeleton_path:
        out.append(_issue("E_ANIM_NO_SKELETON", C.SEVERITY_ERROR,
                          "Animation '%s' has no skeleton reference; set the armature's Unreal skeleton path."
                          % asset.asset_name, obj=asset.armature, asset=asset.id))
    else:
        head, _ = naming.split_unreal_path(asset.skeleton_path)
        problems = naming.validate_unreal_root(head)
        if problems or not asset.skeleton_path.startswith("/"):
            out.append(_issue("E_ANIM_NO_SKELETON", C.SEVERITY_ERROR,
                              "Skeleton reference '%s' is not a valid Unreal object path." % asset.skeleton_path,
                              obj=asset.armature, asset=asset.id))
    if asset.frame_end < asset.frame_start:
        out.append(_issue("E_FRAME_RANGE", C.SEVERITY_ERROR,
                          "Animation '%s' ends (%g) before it starts (%g)." % (asset.asset_name, asset.frame_end,
                                                                                 asset.frame_start),
                          obj=asset.armature, asset=asset.id))
    elif asset.frame_end == asset.frame_start:
        out.append(_issue("W_FRAME_RANGE_SINGLE", C.SEVERITY_WARNING,
                          "Animation '%s' is a single frame." % asset.asset_name, obj=asset.armature,
                          asset=asset.id))
    arm = snapshot.object(asset.armature)
    if arm is None:
        out.append(_issue("E_MISSING_ARMATURE", C.SEVERITY_ERROR,
                          "Animation '%s' has no armature." % asset.asset_name, asset=asset.id))
        return out
    out.extend(_bone_rules(arm, asset, settings))
    if arm.is_animated and settings.root_motion != C.ROOT_MOTION_OBJECT_TO_ROOT:
        out.append(_issue("W_ARMATURE_OBJECT_ANIMATED", C.SEVERITY_WARNING,
                          "Armature object '%s' itself is animated; object motion is ignored unless the root "
                          "motion policy is 'Object to Root'." % arm.name, obj=arm.name, asset=asset.id))
    return out
