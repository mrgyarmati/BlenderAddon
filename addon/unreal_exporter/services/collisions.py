"""Create and manage collision helpers (UBX_/USP_/UCP_/UCX_).

Helpers are built in the owner's local space, parented to the owner with an
identity parent-inverse, displayed as wire and hidden from renders. Unreal fits
capsules from the farthest vertex pair, so capsules keep pole vertices and a
small vertex count (the fit is quadratic in vertices).
"""

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from .. import constants as C
from ..domain import naming
from . import ids


class CollisionError(RuntimeError):
    pass


def helpers_of(owner, role):
    """Objects acting as ``role`` helpers of ``owner`` (metadata first, then names)."""
    owner_id = ids.props(owner).uuid
    out = []
    for ob in bpy.data.objects:
        if ob == owner:
            continue
        p = ids.props(ob)
        if p.role == role and owner_id and p.owner_uuid == owner_id:
            out.append(ob)
        elif p.role == C.ROLE_NONE:
            if role == C.ROLE_COLLISION and ob.type == "MESH" and naming.collision_matches_owner(ob.name, owner.name):
                out.append(ob)
            elif role == C.ROLE_SOCKET and ob.type == "EMPTY":
                parsed = naming.parse_socket_name(ob.name, [owner.name])
                if parsed and parsed[0] == owner.name:
                    out.append(ob)
            elif role == C.ROLE_LOD and ob.type == "MESH":
                parsed = naming.parse_lod_name(ob.name)
                if parsed and parsed[1] >= 1 and parsed[0] == naming.asset_base_name(owner.name):
                    out.append(ob)
    return sorted(out, key=lambda o: o.name)


def next_collision_index(owner) -> int:
    used = set()
    for ob in helpers_of(owner, C.ROLE_COLLISION):
        parsed = naming.parse_collision_name(ob.name)
        if parsed and parsed[2] is not None:
            used.add(parsed[2])
    index = 0
    while index in used:
        index += 1
    return index


def owner_points(owner, depsgraph, selected_only=False):
    """Vertex positions in the owner's local space (evaluated, or the edit selection)."""
    if selected_only and owner.mode == "EDIT":
        bm = bmesh.from_edit_mesh(owner.data)
        points = [v.co.copy() for v in bm.verts if v.select]
        if not points:
            raise CollisionError("Select some vertices of '%s' first." % owner.name)
        return points
    evaluated = owner.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = [v.co.copy() for v in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    if not points:
        raise CollisionError("'%s' has no vertices to fit a collision to." % owner.name)
    return points


def _bounds(points):
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return lo, hi


def _axis_frame(lo, hi):
    """Rotation taking +Z onto the longest bounds axis, and that axis index."""
    size = hi - lo
    axis = max(range(3), key=lambda i: size[i])
    if axis == 2:
        return Matrix.Identity(4), axis
    if axis == 0:
        return Matrix.Rotation(math.radians(90.0), 4, "Y"), axis
    return Matrix.Rotation(math.radians(-90.0), 4, "X"), axis


def build_box(bm, points, padding):
    lo, hi = _bounds(points)
    lo -= Vector((padding,) * 3)
    hi += Vector((padding,) * 3)
    size = hi - lo
    for i in range(3):
        if size[i] < 1e-6:
            size[i] = 1e-4
    center = (lo + hi) * 0.5
    matrix = Matrix.Translation(center) @ Matrix.Diagonal((size.x, size.y, size.z, 1.0))
    bmesh.ops.create_cube(bm, size=1.0, matrix=matrix)


def build_sphere(bm, points, padding, segments):
    lo, hi = _bounds(points)
    center = (lo + hi) * 0.5
    radius = max((p - center).length for p in points) + padding
    bmesh.ops.create_uvsphere(bm, u_segments=max(segments, 8), v_segments=max(segments // 2, 4),
                              radius=max(radius, 1e-4), matrix=Matrix.Translation(center))


def _lathe(bm, profile, segments, matrix):
    """Revolve ``(radius, z)`` profile points (bottom to top) around Z."""
    rings = []
    for radius, z in profile:
        if radius < 1e-9:
            rings.append([bm.verts.new(matrix @ Vector((0.0, 0.0, z)))])
            continue
        ring = []
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            ring.append(bm.verts.new(matrix @ Vector((radius * math.cos(angle), radius * math.sin(angle), z))))
        rings.append(ring)
    for lower, upper in zip(rings, rings[1:]):
        if len(lower) == 1 and len(upper) > 1:
            for i in range(segments):
                bm.faces.new((lower[0], upper[(i + 1) % segments], upper[i]))
        elif len(upper) == 1 and len(lower) > 1:
            for i in range(segments):
                bm.faces.new((lower[i], lower[(i + 1) % segments], upper[0]))
        elif len(lower) > 1 and len(upper) > 1:
            for i in range(segments):
                j = (i + 1) % segments
                bm.faces.new((lower[i], lower[j], upper[j], upper[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])


def build_capsule(bm, points, padding, segments):
    lo, hi = _bounds(points)
    rotation, axis = _axis_frame(lo, hi)
    center = (lo + hi) * 0.5
    direction = Vector((0.0, 0.0, 0.0))
    direction[axis] = 1.0
    radius = 0.0
    half = 0.0
    for p in points:
        offset = p - center
        along = offset.dot(direction)
        half = max(half, abs(along))
        radius = max(radius, (offset - direction * along).length)
    radius = max(radius + padding, 1e-4)
    half = max(half + padding - radius, 0.0)
    rings = 3
    profile = [(0.0, -half - radius)]
    for i in range(1, rings + 1):
        phi = math.pi / 2.0 * i / (rings + 1)
        profile.append((radius * math.sin(phi), -half - radius * math.cos(phi)))
    profile.append((radius, -half))
    profile.append((radius, half))
    for i in range(rings, 0, -1):
        phi = math.pi / 2.0 * i / (rings + 1)
        profile.append((radius * math.sin(phi), half + radius * math.cos(phi)))
    profile.append((0.0, half + radius))
    _lathe(bm, profile, max(min(segments, 16), 6), Matrix.Translation(center) @ rotation)


def build_cylinder(bm, points, padding, segments):
    lo, hi = _bounds(points)
    rotation, axis = _axis_frame(lo, hi)
    center = (lo + hi) * 0.5
    direction = Vector((0.0, 0.0, 0.0))
    direction[axis] = 1.0
    radius = 0.0
    half = 0.0
    for p in points:
        offset = p - center
        along = offset.dot(direction)
        half = max(half, abs(along))
        radius = max(radius, (offset - direction * along).length)
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=max(segments, 3),
                          radius1=max(radius + padding, 1e-4), radius2=max(radius + padding, 1e-4),
                          depth=max(2.0 * (half + padding), 1e-4),
                          matrix=Matrix.Translation(center) @ rotation)


def build_convex(bm, points, padding):
    verts = [bm.verts.new(p) for p in points]
    result = bmesh.ops.convex_hull(bm, input=verts, use_existing_faces=False)
    doomed = {v for v in result["geom_interior"] if isinstance(v, bmesh.types.BMVert)}
    doomed.update(v for v in result["geom_unused"] if isinstance(v, bmesh.types.BMVert))
    if doomed:
        bmesh.ops.delete(bm, geom=list(doomed), context="VERTS")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    if not bm.faces:
        raise CollisionError("The points are flat; a convex hull needs volume.")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if padding > 0.0:
        bm.normal_update()
        for v in bm.verts:
            v.co += v.normal * padding


def _owner_collections(owner, scene):
    return list(owner.users_collection) or [scene.collection]


def create_collision(context, owner, shape, *, points=None, padding=0.0, segments=12):
    """Create a collision helper for ``owner``. ``shape`` may be CYLINDER (written as UCX)."""
    if owner.type != "MESH":
        raise CollisionError("Collisions can only be added to mesh objects.")
    if points is None:
        points = owner_points(owner, context.evaluated_depsgraph_get())
    stored_shape = C.SHAPE_CONVEX if shape == "CYLINDER" else shape
    name = naming.collision_object_name(stored_shape, owner.name, next_collision_index(owner))
    bm = bmesh.new()
    try:
        if shape == C.SHAPE_BOX:
            build_box(bm, points, padding)
        elif shape == C.SHAPE_SPHERE:
            build_sphere(bm, points, padding, segments)
        elif shape == C.SHAPE_CAPSULE:
            build_capsule(bm, points, padding, segments)
        elif shape == "CYLINDER":
            build_cylinder(bm, points, padding, segments)
        elif shape == C.SHAPE_CONVEX:
            build_convex(bm, points, padding)
        else:
            raise CollisionError("Unknown collision shape %r." % shape)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    ob = bpy.data.objects.new(name, mesh)
    for coll in _owner_collections(owner, context.scene):
        coll.objects.link(ob)
    ob.parent = owner
    ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.matrix_basis = Matrix.Identity(4)
    ob.display_type = "WIRE"
    ob.hide_render = True
    ob.visible_shadow = False
    p = ids.props(ob)
    p.role = C.ROLE_COLLISION
    p.owner_uuid = ids.ensure_uuid(owner)
    p.collision_shape = stored_shape
    ids.ensure_uuid(ob)
    return ob
