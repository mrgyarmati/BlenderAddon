#!/usr/bin/env python3
"""Unreal acceptance gate: build fixtures in Blender, import them in UE 5.6 and 5.8, assert.

    python scripts/run_unreal_tests.py [--versions 5.8 5.6] [--skip-fixtures] [--allow-missing]

Fixtures come from scripts/make_fixture_files.py; checks run inside Unreal via
tests/unreal/acceptance.py using headless ``UnrealEditor-Cmd -run=pythonscript``.
Exit code 0 only when every requested engine ran and every check passed.
"""

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tooling  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--versions", nargs="+", default=["5.8", "5.6"])
    parser.add_argument("--acceptance-dir", default=os.path.join(tooling.BUILD_DIR, "acceptance"))
    parser.add_argument("--addon-dir", default=os.path.join(tooling.REPO_ROOT, "addon"),
                        help="folder containing unreal_exporter/ (use an unzipped build for release checks)")
    parser.add_argument("--skip-fixtures", action="store_true")
    parser.add_argument("--allow-missing", action="store_true", help="skip engines that are not installed")
    args = parser.parse_args()

    acceptance = os.path.abspath(args.acceptance_dir)
    tooling.require_no_spaces(acceptance, "Acceptance")
    if not args.skip_fixtures:
        blender = tooling.find_blender()
        if blender is None:
            raise SystemExit("Blender 5.2 not found; set BLENDER_EXE.")
        code, text = tooling.run(tooling.blender_command(
            blender, "--python-exit-code", "1", "--python", os.path.join(tooling.REPO_ROOT, "scripts",
                                                                        "make_fixture_files.py"),
            "--", "--out", acceptance, "--addon-dir", os.path.abspath(args.addon_dir)),
            log_path=os.path.join(acceptance + "_logs", "fixtures.log"))
        if code != 0:
            print(text[-4000:])
            raise SystemExit("Fixture generation failed (exit %d)." % code)

    summary = {}
    exit_code = 0
    for version in args.versions:
        exe = tooling.find_unreal(version)
        if exe is None:
            print("UE %s: NOT INSTALLED" % version)
            summary[version] = "missing"
            if not args.allow_missing:
                exit_code = 1
            continue
        project = tooling.ensure_project(version)
        tooling.require_no_spaces(project, "Project")
        plugin_dst = os.path.join(os.path.dirname(project), "Plugins", "BlenderBridge")
        if os.path.isdir(plugin_dst):
            shutil.rmtree(plugin_dst)
        shutil.copytree(os.path.join(tooling.REPO_ROOT, "unreal", "BlenderBridge"), plugin_dst,
                        ignore=shutil.ignore_patterns("__pycache__"))
        script_dir = os.path.join(os.path.dirname(project), "Scripts")
        os.makedirs(script_dir, exist_ok=True)
        script = os.path.join(script_dir, "acceptance.py")
        shutil.copyfile(os.path.join(tooling.REPO_ROOT, "tests", "unreal", "acceptance.py"), script)
        result_path = os.path.join(acceptance + "_logs", "ue_%s_result.json" % version)
        if os.path.exists(result_path):
            os.remove(result_path)
        code, text = tooling.run([exe, project, "-run=pythonscript",
                                  '-Script=%s %s %s' % (script.replace("\\", "/"), acceptance.replace("\\", "/"),
                                                        result_path.replace("\\", "/")),
                                  "-unattended", "-nopause", "-nosplash", "-NullRHI", "-stdout", "-FullStdOutLogOutput"],
                                 log_path=os.path.join(acceptance + "_logs", "ue_%s.log" % version))
        if not os.path.isfile(result_path):
            print(text[-4000:])
            print("UE %s: no result file (exit %d)" % (version, code))
            summary[version] = "error"
            exit_code = 1
            continue
        with open(result_path, encoding="utf-8") as handle:
            result = json.load(handle)
        failed = [c for c in result["checks"] if not c["ok"]]
        print("UE %s (%s): %d checks, %d failed" % (version, result["engine"], len(result["checks"]), len(failed)))
        for check in failed:
            print("   FAIL %s :: %s" % (check["name"], check["detail"][:500]))
        summary[version] = "pass" if not failed else "fail"
        if failed:
            exit_code = 1
    print("SUMMARY " + json.dumps(summary))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
