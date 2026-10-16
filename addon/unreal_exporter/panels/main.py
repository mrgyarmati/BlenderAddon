"""Main "Unreal Export" panel and its sub-panels."""

import bpy

from .. import constants as C
from ..domain import naming
from ..services import ids, lods, sockets
from ..services.collisions import helpers_of
from ..services.rename import asset_root
from . import common
from .common import CATEGORY


class _Base:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY


class UEX_PT_main(_Base, bpy.types.Panel):
    bl_idname = "UEX_PT_main"
    bl_label = "Unreal Export"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        s = common.scene_settings(context)
        st = common.state(context)
        col = layout.column(align=True)
        col.prop(s, "profile", text="")
        row = col.row(align=True)
        row.prop(s, "scope", text="")
        if s.profile in (C.PROFILE_STATIC_MESH, C.PROFILE_COLLECTION_SCENE):
            row.prop(s, "grouping", text="")
        if s.scope == C.SCOPE_CHOSEN_COLLECTIONS:
            row = layout.row()
            row.template_list("UEX_UL_collections", "", s, "chosen_collections", s, "chosen_collections_index", rows=3)
            sub = row.column(align=True)
            sub.operator("uex.collection_add", icon="ADD", text="")
            sub.operator("uex.collection_remove", icon="REMOVE", text="")
        if s.profile == C.PROFILE_SKELETAL_MESH:
            layout.prop(s, "skeletal_include_animations")

        col = layout.column(align=True)
        col.prop(s, "export_dir", text="", icon="FILE_FOLDER")
        col.prop(s, "unreal_root", text="", icon="FILE_FOLDER")

        layout.operator("uex.validate", icon="CHECKMARK")
        row = layout.row(align=True)
        row.scale_y = 1.3
        op = row.operator("uex.export", text="Export to Disk", icon="EXPORT")
        op.destination = C.DEST_DISK
        op = row.operator("uex.export", text="Export + Script", icon="SCRIPT")
        op.destination = C.DEST_SCRIPT

        if st.validated:
            row = layout.row(align=True)
            icon = "CANCEL" if st.issue_errors else ("ERROR" if st.issue_warnings else "CHECKMARK")
            row.label(text="%d asset(s), %d error(s), %d warning(s)" % (st.validated_assets, st.issue_errors,
                                                                      st.issue_warnings), icon=icon)


class UEX_PT_asset(_Base, bpy.types.Panel):
    bl_parent_id = "UEX_PT_main"
    bl_label = "Active Object"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        p = ids.props(ob)
        s = common.scene_settings(context)
        if p.role != C.ROLE_NONE:
            owner = next((o for o in bpy.data.objects if p.owner_uuid and ids.props(o).uuid == p.owner_uuid), None)
            layout.label(text="%s helper of %s" % (p.role.title(), owner.name if owner else "(missing owner)"),
                         icon="LINKED")
            if p.role == C.ROLE_COLLISION:
                layout.prop(p, "collision_shape")
            elif p.role == C.ROLE_SOCKET:
                layout.prop(p, "socket_name")
                if owner is not None:
                    world = s.origin_mode == C.ORIGIN_WORLD
                    preview = sockets.unreal_preview(owner, ob, context.scene.unit_settings.scale_length,
                                                     world_origin=world)
                    box = layout.box()
                    box.label(text="Unreal (relative to %s)" % ("the world origin" if world else owner.name),
                              icon="EMPTY_ARROWS")
                    box.label(text="Location cm: %.2f, %.2f, %.2f" % preview["location"])
                    box.label(text="Rotation (R, P, Y): %.1f, %.1f, %.1f" % preview["rotation"])
            elif p.role == C.ROLE_LOD:
                row = layout.row()
                row.label(text="LOD%d (%s)" % (p.lod_index, "generated" if p.lod_generated else "authored"))
            return
        layout.prop(p, "export_enabled")
        col = layout.column()
        col.active = p.export_enabled
        col.prop(p, "asset_name_override", placeholder=naming.asset_base_name(ob.name))
        col.prop(p, "folder_override", placeholder="(Unreal root)")
        if ob.type == "ARMATURE":
            col.prop(p, "skeleton_path_override", placeholder="(derived from the skeletal mesh)")
        if ob.type in ("MESH", "ARMATURE"):
            raw = p.asset_name_override or naming.asset_base_name(ob.name)
            clean = naming.sanitize_name(raw).value
            prefix = s.prefix_skeletal if ob.type == "ARMATURE" else s.prefix_static
            if clean and s.auto_prefix:
                clean = naming.apply_prefix(clean, prefix)
            folder = naming.sanitize_folder(p.folder_override)
            path = naming.build_unreal_path(s.unreal_root, folder, clean) if clean else "(invalid name)"
            layout.label(text=path, icon="UV_SYNC_SELECT")


class UEX_PT_collision(_Base, bpy.types.Panel):
    bl_parent_id = "UEX_PT_main"
    bl_label = "Collision"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        s = common.scene_settings(context)
        layout.prop(s, "collision_shape", expand=True)
        row = layout.row(align=True)
        row.prop(s, "collision_padding")
        if s.collision_shape in (C.SHAPE_SPHERE, C.SHAPE_CAPSULE, "CYLINDER"):
            row.prop(s, "collision_segments")
        text = "Fit to Selected Vertices" if context.mode == "EDIT_MESH" else "Add Collision"
        layout.operator("uex.add_collision", text=text, icon="ADD")
        _helper_list(layout, context, C.ROLE_COLLISION)
        row = layout.row(align=True)
        op = row.operator("uex.helpers_visibility", text="Show", icon="HIDE_OFF")
        op.kind, op.action = C.ROLE_COLLISION, "SHOW"
        op = row.operator("uex.helpers_visibility", text="Hide", icon="HIDE_ON")
        op.kind, op.action = C.ROLE_COLLISION, "HIDE"
        layout.prop(s, "one_convex_hull_per_ucx")
        layout.prop(s, "auto_generate_collision")


def _helper_list(layout, context, role):
    ob = context.active_object
    if ob is None:
        return
    owner = asset_root(ob)
    helpers = helpers_of(owner, role) if owner.type == "MESH" else []
    if not helpers:
        return
    box = layout.box()
    col = box.column(align=True)
    for helper in helpers[:12]:
        row = col.row(align=True)
        op = row.operator("uex.select_object", text=helper.name, emboss=False,
                          icon="RESTRICT_SELECT_OFF" if helper.select_get() else "RESTRICT_SELECT_ON")
        op.name = helper.name
    if len(helpers) > 12:
        col.label(text="... %d more" % (len(helpers) - 12))


class UEX_PT_sockets(_Base, bpy.types.Panel):
    bl_parent_id = "UEX_PT_main"
    bl_label = "Sockets"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        s = common.scene_settings(context)
        col = layout.column(align=True)
        col.prop(s, "socket_mode", text="")
        if s.socket_mode != "EMPTY":
            col.prop(s, "socket_name", text="")
        layout.operator("uex.add_socket", icon="EMPTY_ARROWS")
        _helper_list(layout, context, C.ROLE_SOCKET)


class UEX_PT_lods(_Base, bpy.types.Panel):
    bl_parent_id = "UEX_PT_main"
    bl_label = "LODs"
    bl_order = 4
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        s = common.scene_settings(context)
        st = common.state(context)
        layout.prop(s, "lod_preset", text="")
        if s.lod_preset == "CUSTOM":
            row = layout.row(align=True)
            row.prop(s, "lod_mode", text="")
            row.prop(s, "lod_custom", text="")
        layout.label(text="Automatic reduction (Decimate), non-destructive", icon="MOD_DECIM")
        row = layout.row(align=True)
        row.operator("uex.lod_generate", text="Generate", icon="ADD")
        row.operator("uex.lod_update", text="Update", icon="FILE_REFRESH")
        row.operator("uex.lod_remove", text="", icon="TRASH")
        layout.operator("uex.lod_assign", text="Assign Selected as Authored LOD", icon="LINKED")
        row = layout.row(align=True)
        row.label(text="LOD triangles%s" % ((" - " + st.lod_stats_owner) if st.lod_stats_owner else ""))
        row.operator("uex.lod_refresh", text="", icon="FILE_REFRESH")
        if len(st.lod_stats):
            layout.template_list("UEX_UL_lod_stats", "", st, "lod_stats", st, "lod_stats_index",
                                 rows=min(len(st.lod_stats), 5))
        row = layout.row(align=True)
        if lods.audit_active():
            op = row.operator("uex.lod_audit", text="End Side-by-Side Audit", icon="CANCEL")
            op.action = "END"
        else:
            op = row.operator("uex.lod_audit", text="Side-by-Side Audit", icon="VIEW_ORTHO")
            op.action = "BEGIN"
        _helper_list(layout, context, C.ROLE_LOD)


class UEX_PT_animation(_Base, bpy.types.Panel):
    bl_parent_id = "UEX_PT_main"
    bl_label = "Animation"
    bl_order = 5
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        s = common.scene_settings(context)
        ob = context.active_object
        return s.profile in (C.PROFILE_ANIMATION, C.PROFILE_SKELETAL_MESH) or (ob is not None and ob.type == "ARMATURE")

    def draw(self, context):
        layout = self.layout
        s = common.scene_settings(context)
        row = layout.row()
        row.template_list("UEX_UL_actions", "", s, "actions", s, "actions_index", rows=4)
        row.operator("uex.actions_refresh", text="", icon="FILE_REFRESH")
        layout.label(text="Unchecked or empty list: the armature's active action", icon="INFO")
        col = layout.column()
        col.use_property_split = True
        col.prop(s, "frame_range_mode")
        if s.frame_range_mode == C.FRAME_RANGE_CUSTOM:
            sub = col.row(align=True)
            sub.prop(s, "custom_frame_start")
            sub.prop(s, "custom_frame_end")
        col.prop(s, "sample_step")
        col.prop(s, "simplify")
        col.prop(s, "root_motion")
        col.prop(s, "nla_policy")
        col.prop(s, "animation_name_includes_armature")


class UEX_PT_rename(_Base, bpy.types.Panel):
    bl_parent_id = "UEX_PT_main"
    bl_label = "Batch Rename"
    bl_order = 6
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        s = common.scene_settings(context)
        st = common.state(context)
        layout.prop(s, "rename_mode", expand=True)
        col = layout.column(align=True)
        if s.rename_mode == "REPLACE":
            col.prop(s, "rename_find")
            col.prop(s, "rename_replace")
            col.prop(s, "rename_case_sensitive")
        elif s.rename_mode == "AFFIX":
            col.prop(s, "rename_prefix")
            col.prop(s, "rename_suffix")
        else:
            col.prop(s, "rename_name")
        row = layout.row(align=True)
        row.operator("uex.rename_preview", icon="VIEWZOOM")
        row.operator("uex.rename_apply", icon="CHECKMARK")
        if len(st.rename_preview):
            layout.template_list("UEX_UL_rename", "", st, "rename_preview", st, "rename_preview_index", rows=4)


class UEX_PT_options(_Base, bpy.types.Panel):
    bl_parent_id = "UEX_PT_main"
    bl_label = "FBX & Import Options"
    bl_order = 7
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        s = common.scene_settings(context)
        col = layout.column(heading="Naming")
        col.prop(s, "auto_prefix")
        sub = col.column(align=True)
        sub.active = s.auto_prefix
        sub.prop(s, "prefix_static")
        sub.prop(s, "prefix_skeletal")
        sub.prop(s, "prefix_animation")
        col.prop(s, "mirror_collections_as_folders")
        col = layout.column(heading="Geometry")
        col.prop(s, "origin_mode")
        col.prop(s, "smoothing")
        col.prop(s, "triangulate")
        col.prop(s, "export_tangents")
        col.prop(s, "export_vertex_colors")
        col = layout.column(heading="Skeletal")
        col.prop(s, "export_morph_targets")
        col.prop(s, "deform_bones_only")
        col.prop(s, "primary_bone_axis")
        col.prop(s, "secondary_bone_axis")
        col = layout.column(heading="Checks")
        col.prop(s, "lod_collision_naming")
        col.prop(s, "max_material_slots")
        col.prop(s, "max_bone_influences")
        col.prop(s, "socket_distance_tolerance")
        col = layout.column(heading="Unreal Import")
        col.prop(s, "import_materials")
        col.prop(s, "import_textures")
        col.prop(s, "build_nanite")
        col.prop(s, "generate_lightmap_uvs")
        col.prop(s, "create_physics_asset")
        col.prop(s, "reimport_policy")


CLASSES = (UEX_PT_main, UEX_PT_asset, UEX_PT_collision, UEX_PT_sockets, UEX_PT_lods, UEX_PT_animation,
           UEX_PT_rename, UEX_PT_options)
