#!/usr/bin/env python3
"""Copy the importer core into the Unreal plugin (single source of truth).

    python scripts/sync_unreal_plugin.py [--check]

``--check`` exits 1 when the plugin copy is out of date instead of writing it.
"""

import argparse
import filecmp
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "addon", "unreal_exporter", "unreal_templates", "importer_core.py")
TARGET = os.path.join(ROOT, "unreal", "BlenderBridge", "Content", "Python", "blender_bridge", "importer.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    in_sync = os.path.isfile(TARGET) and filecmp.cmp(SOURCE, TARGET, shallow=False)
    if args.check:
        print("plugin importer %s" % ("in sync" if in_sync else "OUT OF DATE"))
        return 0 if in_sync else 1
    if not in_sync:
        shutil.copyfile(SOURCE, TARGET)
        print("updated %s" % os.path.relpath(TARGET, ROOT))
    else:
        print("plugin importer already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
