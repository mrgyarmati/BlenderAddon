"""Add-on preferences: machine-specific defaults only (never per-project settings)."""

import bpy
from bpy.props import BoolProperty, StringProperty


class UEX_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    permitted_roots: StringProperty(
        name="Permitted Export Roots",
        description=(
            "Optional ';'-separated list of folders. When set, exports are refused unless the export "
            "directory is inside one of them"
        ),
        default="",
    )
    developer_mode: BoolProperty(
        name="Developer Mode",
        description="Allow exporting even when validation reports blocking errors (for pipeline debugging only)",
        default=False,
    )
    debug_paths: BoolProperty(
        name="Absolute Paths in Logs",
        description="Write absolute file paths into export logs (they are export-root relative by default)",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "permitted_roots")
        col = layout.column(heading="Debugging")
        col.prop(self, "developer_mode")
        col.prop(self, "debug_paths")


class _DefaultPrefs:
    """Stand-in used when the add-on is registered without addon_utils (tests)."""

    permitted_roots = ""
    developer_mode = False
    debug_paths = False


def get_prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    if addon is None or addon.preferences is None:
        return _DefaultPrefs()
    return addon.preferences


CLASSES = (UEX_AddonPreferences,)
