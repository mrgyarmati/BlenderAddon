"""PreToolUse hook: refuse edits to generated files.

Reads the Claude Code hook payload from stdin. Exit code 2 blocks the tool call
and shows the message to Claude.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERATED = {
    os.path.join(ROOT, "unreal", "BlenderBridge", "Content", "Python", "blender_bridge", "importer.py"):
        "This is a generated copy. Edit addon/unreal_exporter/unreal_templates/importer_core.py, then run "
        "scripts/sync_unreal_plugin.py.",
}


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return 0
    full = os.path.normcase(os.path.abspath(path))
    dist = os.path.normcase(os.path.join(ROOT, "dist")) + os.sep
    if full.startswith(dist):
        print("dist/ is build output; rebuild it with scripts/build_extension.py instead of editing it.",
              file=sys.stderr)
        return 2
    for generated, message in GENERATED.items():
        if full == os.path.normcase(generated):
            print(message, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
