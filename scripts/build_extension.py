#!/usr/bin/env python3
"""Validate, build and audit the Blender extension zip.

    python scripts/build_extension.py [--output-dir dist]

Runs ``blender --command extension validate`` on the source, ``extension build``
into ``--output-dir``, validates the produced zip and audits its contents (no
tests, caches, blend files or credential-looking files). Prints the zip path.
"""

import argparse
import fnmatch
import os
import sys
import tomllib
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tooling  # noqa: E402

FORBIDDEN = ("*__pycache__*", "*.pyc", "*.pyo", "tests/*", "*.blend", "*.blend1", ".git*", "*.env", "*.pem",
             "*.key", "*credentials*", "*.log")
REQUIRED = ("blender_manifest.toml", "__init__.py", "registration.py", "unreal_templates/importer_core.py")


def manifest_version():
    with open(os.path.join(tooling.ADDON_DIR, "blender_manifest.toml"), "rb") as handle:
        data = tomllib.load(handle)
    return data["id"], data["version"]


def audit(zip_path):
    problems = []
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    for name in names:
        for pattern in FORBIDDEN:
            if fnmatch.fnmatch(name, pattern):
                problems.append("forbidden file in zip: %s" % name)
    for required in REQUIRED:
        if required not in names:
            problems.append("missing from zip: %s" % required)
    return names, problems


def build(output_dir):
    blender = tooling.find_blender()
    if blender is None:
        raise SystemExit("Blender 5.2 not found; set BLENDER_EXE.")
    code, text = tooling.run([blender, "--factory-startup", "--command", "extension", "validate",
                              tooling.ADDON_DIR])
    if code != 0:
        print(text[-3000:])
        raise SystemExit("Source validation failed.")
    os.makedirs(output_dir, exist_ok=True)
    ext_id, version = manifest_version()
    zip_path = os.path.join(output_dir, "%s-%s.zip" % (ext_id, version))
    if os.path.exists(zip_path):
        os.remove(zip_path)
    code, text = tooling.run([blender, "--factory-startup", "--command", "extension", "build",
                              "--source-dir", tooling.ADDON_DIR, "--output-dir", output_dir])
    if code != 0 or not os.path.isfile(zip_path):
        print(text[-3000:])
        raise SystemExit("Build failed.")
    code, text = tooling.run([blender, "--factory-startup", "--command", "extension", "validate", zip_path])
    if code != 0:
        print(text[-3000:])
        raise SystemExit("Zip validation failed.")
    names, problems = audit(zip_path)
    for problem in problems:
        print("AUDIT: " + problem)
    if problems:
        raise SystemExit("Zip audit failed.")
    print("built %s (%d files, %d bytes)" % (zip_path, len(names), os.path.getsize(zip_path)))
    return zip_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=tooling.DIST_DIR)
    args = parser.parse_args()
    build(os.path.abspath(args.output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
