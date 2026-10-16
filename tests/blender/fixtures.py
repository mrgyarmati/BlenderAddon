"""Programmatic fixture scenes for Blender integration tests."""

import math

import bmesh
import bpy
from mathutils import Matrix


def cube_mesh(name, size=1.0, offset=(0.0, 0.0, 0.0), material=None, uv=True):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    if uv:
        bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_cube(bm, size=size, matrix=Matrix.Translation(offset), calc_uvs=uv)
    bm.to_mesh(mesh)
    bm.free()
    if material is not None:
        mesh.materials.append(material)
    return mesh


def link(ob, collection=None):
    (collection or bpy.context.scene.collection).objects.link(ob)
    return ob


def material(name):
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def crate(name="SM_Crate", location=(2.0, 3.0, 0.0), collection=None, size=1.0, bevel=False):
    ob = bpy.data.objects.new(name, cube_mesh(name + "_mesh", size, material=material("M_Wood")))
    link(ob, collection)
    ob.location = location
    if bevel:
        mod = ob.modifiers.new("Bevel", "BEVEL")
        mod.width = 0.05
        mod.segments = 2
    bpy.context.view_layer.update()
    return ob


def collection(name, parent=None):
    coll = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(coll)
    return coll


def rig(name="Hero", location=(0.0, 0.0, 0.0), with_mesh=True, shape_key=False):
    """Two-bone armature with a skinned 1 m cube and a 'Wave' action (frames 1-10)."""
    scene = bpy.context.scene
    data = bpy.data.armatures.new(name + "_data")
    arm = link(bpy.data.objects.new(name, data))
    arm.location = location
    view_layer = bpy.context.view_layer
    for ob in view_layer.objects:
        ob.select_set(False)
    arm.select_set(True)
    view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    root = data.edit_bones.new("root")
    root.head, root.tail = (0.0, 0.0, 0.0), (0.0, 0.3, 0.0)
    spine = data.edit_bones.new("spine")
    spine.head, spine.tail = (0.0, 0.0, 0.5), (0.0, 0.0, 1.5)
    spine.parent = root
    bpy.ops.object.mode_set(mode="OBJECT")
    meshes = []
    if with_mesh:
        mesh = cube_mesh(name + "_body_mesh", 1.0, (0.0, 0.0, 1.0), material=material("M_Skin"))
        body = link(bpy.data.objects.new(name + "_Body", mesh))
        body.parent = arm
        body.matrix_parent_inverse = arm.matrix_world.inverted()
        mod = body.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
        groups = {bone: body.vertex_groups.new(name=bone) for bone in ("root", "spine")}
        for v in mesh.vertices:
            (groups["spine"] if v.co.z > 1.0 else groups["root"]).add([v.index], 1.0, "REPLACE")
        if shape_key:
            body.shape_key_add(name="Basis")
            key = body.shape_key_add(name="Bulge")
            for point in key.data:
                point.co.x *= 1.2
        meshes.append(body)
    action = bpy.data.actions.new(name + "_Wave")
    arm.animation_data_create()
    arm.animation_data.action = action
    spine_bone = arm.pose.bones["spine"]
    spine_bone.rotation_mode = "XYZ"
    root_bone = arm.pose.bones["root"]
    for frame, angle, x in ((1, 0.0, 0.0), (10, 45.0, 2.0)):
        spine_bone.rotation_euler = (math.radians(angle), 0.0, 0.0)
        spine_bone.keyframe_insert("rotation_euler", frame=frame)
        root_bone.location = (x, 0.0, 0.0)
        root_bone.keyframe_insert("location", frame=frame)
    spine_bone.rotation_euler = (0.0, 0.0, 0.0)
    root_bone.location = (0.0, 0.0, 0.0)
    scene.frame_set(1)
    return arm, meshes, action
