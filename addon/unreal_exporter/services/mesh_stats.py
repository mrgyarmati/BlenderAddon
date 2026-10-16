"""Geometry facts for validation (bpy/bmesh/numpy adapter -> :class:`MeshStats`)."""

import bmesh
import numpy as np

from ..domain.models import MeshStats

_CONVEXITY_VERTEX_LIMIT = 4096
_DEGENERATE_AREA = 1e-12


def _world_coords(mesh, matrix) -> np.ndarray:
    count = len(mesh.vertices)
    coords = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coords)
    coords = coords.reshape((count, 3))
    if count == 0:
        return coords
    m = np.array(matrix, dtype=np.float64)
    return coords @ m[:3, :3].T + m[:3, 3]


def _local_coords(mesh) -> np.ndarray:
    count = len(mesh.vertices)
    coords = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coords)
    return coords.reshape((count, 3))


def _uv1_facts(mesh):
    """Total triangle area of the second UV map and whether it leaves 0..1."""
    if len(mesh.uv_layers) < 2 or not mesh.loop_triangles:
        return 0.0, False
    layer = mesh.uv_layers[1]
    uvs = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    layer.data.foreach_get("uv", uvs)
    uvs = uvs.reshape((-1, 2))
    tri_loops = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", tri_loops)
    tri = uvs[tri_loops].reshape((-1, 3, 2))
    a = tri[:, 1] - tri[:, 0]
    b = tri[:, 2] - tri[:, 0]
    area = float(np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]).sum() * 0.5)
    out_of_bounds = bool((uvs < -1e-4).any() or (uvs > 1.0 + 1e-4).any())
    return area, out_of_bounds


def _topology_facts(mesh):
    """(non-manifold edges, open edges, degenerate faces) via bmesh."""
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        non_manifold = 0
        open_edges = 0
        for edge in bm.edges:
            faces = len(edge.link_faces)
            if faces == 1:
                open_edges += 1
            elif faces != 2:
                non_manifold += 1
        degenerate = sum(1 for face in bm.faces if face.calc_area() <= _DEGENERATE_AREA)
        return non_manifold, open_edges, degenerate
    finally:
        bm.free()


def _is_convex(mesh, coords: np.ndarray) -> bool:
    if len(coords) > _CONVEXITY_VERTEX_LIMIT or not mesh.polygons:
        return True
    size = float(np.ptp(coords, axis=0).max()) if len(coords) else 0.0
    tolerance = max(size * 1e-4, 1e-7)
    count = len(mesh.polygons)
    normals = np.empty(count * 3, dtype=np.float64)
    centers = np.empty(count * 3, dtype=np.float64)
    mesh.polygons.foreach_get("normal", normals)
    mesh.polygons.foreach_get("center", centers)
    normals = normals.reshape((-1, 3))
    offsets = (centers.reshape((-1, 3)) * normals).sum(axis=1)
    # Signed distance of every vertex to every face plane, in bounded chunks of
    # faces; the mesh is convex when no vertex lies in front of any face.
    for start in range(0, count, 256):
        block = coords @ normals[start:start + 256].T - offsets[start:start + 256]
        if (block > tolerance).any():
            return False
    return True


def _box_fit_error(coords: np.ndarray) -> float:
    if len(coords) == 0:
        return 0.0
    lo = coords.min(axis=0)
    hi = coords.max(axis=0)
    diagonal = float(np.linalg.norm(hi - lo)) or 1.0
    distance = np.minimum(np.abs(coords - lo), np.abs(coords - hi)).min(axis=1)
    return float(distance.max() / diagonal)


def _sphere_fit_error(coords: np.ndarray) -> float:
    if len(coords) == 0:
        return 0.0
    center = (coords.min(axis=0) + coords.max(axis=0)) * 0.5
    radii = np.linalg.norm(coords - center, axis=1)
    mean = float(radii.mean()) or 1.0
    return float((radii.max() - radii.min()) / mean)


def _weight_facts(ob, deform_bone_names):
    """(max influences, vertices without deform weights) from the original mesh."""
    mesh = ob.data
    if not deform_bone_names or not ob.vertex_groups:
        return 0, len(mesh.vertices) if deform_bone_names else 0
    index_to_name = {vg.index: vg.name for vg in ob.vertex_groups}
    deform = {i for i, name in index_to_name.items() if name in deform_bone_names}
    max_influences = 0
    unweighted = 0
    for vertex in mesh.vertices:
        influences = 0
        for group in vertex.groups:
            if group.group in deform and group.weight > 0.0:
                influences += 1
        max_influences = max(max_influences, influences)
        if influences == 0:
            unweighted += 1
    return max_influences, unweighted


def compute(ob, depsgraph, *, collision=False, deform_bone_names=None, evaluated=True) -> MeshStats:
    """Measure ``ob`` (a mesh object). ``deform_bone_names`` enables weight checks."""
    source = ob.evaluated_get(depsgraph) if evaluated else ob
    mesh = source.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    try:
        mesh.calc_loop_triangles()
        polygon_count = len(mesh.polygons)
        loop_totals = np.empty(polygon_count, dtype=np.int32)
        mesh.polygons.foreach_get("loop_total", loop_totals)
        world = _world_coords(mesh, ob.matrix_world)
        local = _local_coords(mesh)
        non_manifold, open_edges, degenerate = _topology_facts(mesh)
        uv1_area, uv1_oob = _uv1_facts(mesh)
        bounds_min = tuple(float(v) for v in world.min(axis=0)) if len(world) else (0.0, 0.0, 0.0)
        bounds_max = tuple(float(v) for v in world.max(axis=0)) if len(world) else (0.0, 0.0, 0.0)
        shape_keys = ()
        if ob.data.shape_keys and len(ob.data.shape_keys.key_blocks) > 1:
            shape_keys = tuple(kb.name for kb in ob.data.shape_keys.key_blocks[1:])
        max_influences, unweighted = (0, 0)
        if deform_bone_names is not None:
            max_influences, unweighted = _weight_facts(ob, deform_bone_names)
        return MeshStats(
            vertex_count=len(mesh.vertices),
            polygon_count=polygon_count,
            triangle_count=len(mesh.loop_triangles),
            ngon_count=int((loop_totals > 4).sum()),
            non_manifold_edge_count=non_manifold + (open_edges if collision else 0),
            degenerate_face_count=degenerate,
            uv_layers=tuple(layer.name for layer in mesh.uv_layers),
            uv1_area_sum=uv1_area,
            uv1_out_of_bounds=uv1_oob,
            material_slots=tuple(slot.material.name if slot.material else "" for slot in ob.material_slots),
            shape_keys=shape_keys,
            vertex_groups=tuple(vg.name for vg in ob.vertex_groups),
            max_bone_influences=max_influences,
            unweighted_vertex_count=unweighted,
            color_attributes=tuple(attr.name for attr in mesh.color_attributes),
            is_convex=_is_convex(mesh, local) if collision else True,
            bounds_min=bounds_min,
            bounds_max=bounds_max,
            box_fit_error=_box_fit_error(local) if collision else 0.0,
            sphere_fit_error=_sphere_fit_error(local) if collision else 0.0,
        )
    finally:
        source.to_mesh_clear()


def triangle_count(ob, depsgraph) -> int:
    """Evaluated triangle count (used by the LOD panel)."""
    source = ob.evaluated_get(depsgraph)
    mesh = source.to_mesh()
    try:
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)
    finally:
        source.to_mesh_clear()
