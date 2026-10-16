"""Generate, update, assign, remove and audit LODs.

Generated LODs are copies of the owner object that share its mesh data, carry
its modifier stack and add a Decimate modifier ("UEX Decimate") at the end. The
owner's mesh is never modified. Authored LODs (``lod_generated`` False) are
never replaced or removed unless the caller passes an explicit override.
"""

import bpy
from mathutils import Matrix

from .. import constants as C
from ..domain import naming
from . import ids, mesh_stats
from .collisions import helpers_of

DECIMATE_NAME = "UEX Decimate"
AUDIT_COLLECTION = "UEX LOD Audit"

PRESETS = {
    "HALVES_3": (0.5, 0.25, 0.125),
    "HALVES_4": (0.5, 0.25, 0.125, 0.0625),
    "GENTLE_3": (0.7, 0.4, 0.2),
}


class LodError(RuntimeError):
    pass


def parse_custom(text: str) -> list:
    values = []
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip().rstrip("%")
        if not part:
            continue
        try:
            values.append(float(part))
        except ValueError:
            raise LodError("'%s' is not a number." % part)
    if not values:
        raise LodError("Enter at least one LOD value.")
    return values


def ratios_for(preset: str, mode: str, custom: str, base_triangles: int) -> list:
    """Decimate ratios (0..1] per LOD level from a preset or custom values."""
    if preset != "CUSTOM":
        return list(PRESETS[preset])
    values = parse_custom(custom)
    if mode == "TRIANGLES":
        if base_triangles <= 0:
            raise LodError("LOD0 has no triangles.")
        ratios = [v / base_triangles for v in values]
    else:
        ratios = [v / 100.0 for v in values]
    for ratio in ratios:
        if not 0.0 < ratio <= 1.0:
            raise LodError("Each LOD must keep between 0%% and 100%% of LOD0 (got %.1f%%)." % (ratio * 100))
    return ratios


def lods_of(owner) -> dict:
    """LOD index -> object for ``owner``."""
    out = {}
    for ob in helpers_of(owner, C.ROLE_LOD):
        p = ids.props(ob)
        index = p.lod_index if p.role == C.ROLE_LOD else naming.parse_lod_name(ob.name)[1]
        out.setdefault(index, ob)
    return out


def _sync_modifiers(lod, owner, ratio):
    for mod in list(lod.modifiers):
        lod.modifiers.remove(mod)
    for source in owner.modifiers:
        target = lod.modifiers.new(source.name, source.type)
        for prop in source.bl_rna.properties:
            if prop.is_readonly or prop.identifier in ("name", "type"):
                continue
            try:
                setattr(target, prop.identifier, getattr(source, prop.identifier))
            except (AttributeError, TypeError, ValueError):
                pass
    decimate = lod.modifiers.new(DECIMATE_NAME, "DECIMATE")
    decimate.decimate_type = "COLLAPSE"
    decimate.ratio = ratio


def _new_lod(context, owner, index, ratio):
    base = naming.asset_base_name(owner.name)
    name = naming.lod_object_name(base, index)
    existing = bpy.data.objects.get(name)
    if existing is not None:
        raise LodError("An object named '%s' already exists; rename it or assign it as an authored LOD." % name)
    lod = bpy.data.objects.new(name, owner.data)
    for coll in owner.users_collection:
        coll.objects.link(lod)
    for index_slot, slot in enumerate(owner.material_slots):
        if slot.link == "OBJECT":
            lod.material_slots[index_slot].link = "OBJECT"
            lod.material_slots[index_slot].material = slot.material
    lod.parent = owner
    lod.matrix_parent_inverse = Matrix.Identity(4)
    lod.matrix_basis = Matrix.Identity(4)
    lod.hide_render = True
    p = ids.props(lod)
    p.role = C.ROLE_LOD
    p.owner_uuid = ids.ensure_uuid(owner)
    p.lod_index = index
    p.lod_generated = True
    p.lod_ratio = ratio
    ids.ensure_uuid(lod)
    _sync_modifiers(lod, owner, ratio)
    try:
        lod.hide_set(True)
    except RuntimeError:
        pass
    return lod


def generate(context, owner, ratios, overwrite_authored=False) -> dict:
    """Create or update generated LODs 1..N. Returns a report dict."""
    if owner.type != "MESH":
        raise LodError("LODs can only be generated for mesh objects.")
    if ids.props(owner).role != C.ROLE_NONE:
        raise LodError("'%s' is a helper; select the render mesh." % owner.name)
    report = {"created": [], "updated": [], "skipped_authored": [], "removed": []}
    existing = lods_of(owner)
    for index, ratio in enumerate(ratios, start=1):
        lod = existing.get(index)
        if lod is not None and not ids.props(lod).lod_generated:
            if not overwrite_authored:
                report["skipped_authored"].append(lod.name)
                continue
            bpy.data.objects.remove(lod)
            lod = None
        if lod is None:
            report["created"].append(_new_lod(context, owner, index, ratio).name)
        else:
            if lod.data != owner.data:
                lod.data = owner.data
            ids.props(lod).lod_ratio = ratio
            _sync_modifiers(lod, owner, ratio)
            report["updated"].append(lod.name)
    for index, lod in sorted(existing.items()):
        if index > len(ratios) and ids.props(lod).lod_generated:
            report["removed"].append(lod.name)
            bpy.data.objects.remove(lod)
    return report


def update(context, owner) -> list:
    """Re-sync generated LODs with the owner's current mesh and modifiers."""
    updated = []
    for _index, lod in sorted(lods_of(owner).items()):
        p = ids.props(lod)
        if not p.lod_generated:
            continue
        if lod.data != owner.data:
            lod.data = owner.data
        _sync_modifiers(lod, owner, p.lod_ratio)
        updated.append(lod.name)
    return updated


def remove(owner, include_authored=False) -> list:
    removed = []
    for _index, lod in sorted(lods_of(owner).items()):
        p = ids.props(lod)
        if p.lod_generated:
            removed.append(lod.name)
            bpy.data.objects.remove(lod)
        elif include_authored:
            removed.append(lod.name)
            p.role = C.ROLE_NONE
            p.owner_uuid = ""
            p.lod_index = 0
    return removed


def assign(owner, ob, index, rename=True) -> str:
    """Make ``ob`` the authored LOD ``index`` of ``owner``."""
    if ob.type != "MESH" or ob == owner:
        raise LodError("Pick another mesh object as the LOD.")
    taken = lods_of(owner).get(index)
    if taken is not None and taken != ob:
        raise LodError("LOD%d of '%s' is already '%s'." % (index, owner.name, taken.name))
    p = ids.props(ob)
    p.role = C.ROLE_LOD
    p.owner_uuid = ids.ensure_uuid(owner)
    p.lod_index = index
    p.lod_generated = False
    ids.ensure_uuid(ob)
    if rename:
        wanted = naming.lod_object_name(naming.asset_base_name(owner.name), index)
        holder = bpy.data.objects.get(wanted)
        if holder is not None and holder != ob:
            raise LodError("Cannot rename to '%s': the name is taken." % wanted)
        ob.name = wanted
    return ob.name


def stats(context, owner) -> list:
    """[(index, object name, triangles, generated)] including LOD0 (hidden LODs included)."""
    from .staging import EvaluationScene

    chain = [(0, owner, False)] + [(i, lod, ids.props(lod).lod_generated) for i, lod in sorted(lods_of(owner).items())]
    with EvaluationScene(context, [ob for _i, ob, _g in chain]) as evaluation:
        return [(index, ob.name, mesh_stats.triangle_count(evaluation.copy_of(ob), evaluation.depsgraph), generated)
                for index, ob, generated in chain]


# ---------------------------------------------------------------- audit


def audit_collection():
    return bpy.data.collections.get(AUDIT_COLLECTION)


def audit_active() -> bool:
    return audit_collection() is not None


def audit_begin(context, owner) -> list:
    """Show LOD0..N side by side as temporary preview objects (never exported)."""
    audit_end()
    rows = stats(context, owner)
    coll = bpy.data.collections.new(AUDIT_COLLECTION)
    context.scene.collection.children.link(coll)
    width = max(owner.dimensions.x, 0.1) * 1.25
    base_tris = rows[0][2] or 1
    created = []
    objects = [owner] + [lods_of(owner)[i] for i, *_ in rows[1:]]
    for offset, ((index, _name, tris, _gen), source) in enumerate(zip(rows, objects)):
        label = "LOD%d %d tris (%d%%)" % (index, tris, round(100.0 * tris / base_tris))
        preview = source.copy()
        preview.name = label
        preview.parent = None
        preview.animation_data_clear()
        coll.objects.link(preview)
        preview.matrix_world = Matrix.Translation((width * offset, 0.0, 0.0)) @ owner.matrix_world
        preview.show_name = True
        preview.hide_render = True
        p = ids.props(preview)
        p.is_preview = True
        p.export_enabled = False
        p.role = C.ROLE_NONE
        p.uuid = ""
        p.owner_uuid = ""
        try:
            preview.hide_set(False)
        except RuntimeError:
            pass
        created.append(preview.name)
    return created


def audit_end() -> int:
    coll = audit_collection()
    if coll is None:
        return 0
    count = 0
    for ob in list(coll.objects):
        bpy.data.objects.remove(ob)
        count += 1
    bpy.data.collections.remove(coll)
    return count
