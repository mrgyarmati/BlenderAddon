"""PostToolUse hook: byte-compile an edited Python file and report syntax errors.

Exit code 2 feeds the error back to Claude; everything else is silent.
"""

import json
import py_compile
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path.endswith(".py"):
        return 0
    try:
        py_compile.compile(path, doraise=True, cfile=None)
    except py_compile.PyCompileError as exc:
        print("Syntax error after edit: %s" % exc.msg, file=sys.stderr)
        return 2
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
