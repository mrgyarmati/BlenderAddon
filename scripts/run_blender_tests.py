#!/usr/bin/env python3
"""Run the headless Blender integration tests.

    python scripts/run_blender_tests.py [--zip dist/unreal_exporter-0.1.0.zip] [-k PATTERN] [-v]

Without ``--zip`` the add-on is loaded from ``addon/``; with it, the built zip is
extracted to a temporary repository first (what users install).
"""

import argparse
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tooling  # noqa: E402


def run_tests(addon_dir, pattern="", verbose=False):
    blender = tooling.find_blender()
    if blender is None:
        raise SystemExit("Blender 5.2 not found; set BLENDER_EXE.")
    args = ["--python-exit-code", "1", "--python", os.path.join(tooling.REPO_ROOT, "tests", "blender", "run_all.py"),
            "--", "--addon-dir", addon_dir]
    if pattern:
        args += ["-k", pattern]
    if verbose:
        args.append("-v")
    code, text = tooling.run(tooling.blender_command(blender, *args), timeout=3600)
    lines = [line for line in text.splitlines() if not line.startswith(("FBX export starting", "export finished"))]
    print("\n".join(lines[-40:]))
    return code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", default="")
    parser.add_argument("-k", dest="pattern", default="")
    parser.add_argument("-v", dest="verbose", action="store_true")
    args = parser.parse_args()
    if not args.zip:
        return run_tests(os.path.join(tooling.REPO_ROOT, "addon"), args.pattern, args.verbose)
    temp = tempfile.mkdtemp(prefix="uex_zip_")
    try:
        target = os.path.join(temp, "unreal_exporter")
        with zipfile.ZipFile(args.zip) as archive:
            archive.extractall(target)
        return run_tests(temp, args.pattern, args.verbose)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
