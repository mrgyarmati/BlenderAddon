"""Results of the last export."""

import os

import bpy

from . import common
from .common import CATEGORY


class UEX_PT_results(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_label = "Results"
    bl_order = 20
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return bool(common.state(context).result_summary)

    def draw(self, context):
        layout = self.layout
        st = common.state(context)
        layout.label(text=st.result_summary, icon="CHECKMARK" if st.result_ok else "ERROR")
        layout.template_list("UEX_UL_results", "", st, "results", st, "results_index", rows=4)
        if 0 <= st.results_index < len(st.results):
            item = st.results[st.results_index]
            box = layout.box()
            box.label(text=item.unreal_path, icon="UV_SYNC_SELECT")
            box.label(text=item.relpath, icon="FILE")
            if item.message:
                common.wrap(box, item.message, width=44, icon="INFO")
        row = layout.row(align=True)
        row.operator("uex.open_folder", icon="FILE_FOLDER", text="Open Folder")
        if st.script_path and os.path.exists(st.script_path):
            row.operator("uex.copy_import_command", icon="COPYDOWN", text="Copy Import Cmd")
        layout.operator("uex.load_receipt", icon="IMPORT")
        if st.receipt_summary:
            layout.label(text=st.receipt_summary, icon="INFO")


CLASSES = (UEX_PT_results,)
