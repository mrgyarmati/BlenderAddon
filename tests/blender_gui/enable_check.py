"""Enable/disable the *installed* extension (run with BLENDER_USER_RESOURCES isolated).

    blender --background --factory-startup --python tests/blender_gui/enable_check.py -- <result.json>
"""

import json
import sys

import addon_utils
import bpy

result_path = sys.argv[sys.argv.index("--") + 1]
module = "bl_ext.user_default.unreal_exporter"
checks = []
try:
    bpy.ops.extensions.repo_refresh_all()
    for cycle in range(2):
        mod = addon_utils.enable(module, default_set=True, handle_error=None)
        checks.append({"name": "enable %d" % cycle, "ok": mod is not None and hasattr(bpy.types, "UEX_PT_main")})
        addon_utils.disable(module, default_set=True, handle_error=None)
        checks.append({"name": "disable %d" % cycle,
                       "ok": not hasattr(bpy.types, "UEX_PT_main") and not hasattr(bpy.types.Object, "uex")})
except Exception as exc:  # report, never crash silently
    checks.append({"name": "enable/disable", "ok": False, "detail": repr(exc)})
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump({"checks": checks}, handle)
