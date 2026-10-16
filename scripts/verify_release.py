#!/usr/bin/env python3
"""Release quality gate: run every check and print a pass/fail checklist with evidence.

    python scripts/verify_release.py [--skip-unreal] [--allow-missing-unreal]

Gates (all must pass):
  1. Unit tests with this Python and with Blender's bundled Python 3.13
  2. Unreal plugin importer in sync with the add-on template
  3. Blender integration tests from source
  4. Extension source validation, zip build, zip validation and content audit
  5. Blender integration tests against the built zip
  6. Install, enable/disable twice and uninstall the zip in an isolated Blender profile
  7. GUI session: undo/redo of every data-changing tool, the modal export, dialogs (--skip-gui)
  8. Unreal acceptance on UE 5.8 (release gate) and UE 5.6, with fixtures exported by the built zip
Skipped steps are reported as SKIPPED, never as passed.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_extension  # noqa: E402
import tooling  # noqa: E402

RESULTS = []


def record(name, status, evidence=""):
    RESULTS.append((name, status, evidence))
    print("[%s] %s %s" % (status, name, evidence))
    sys.stdout.flush()


def last_line(text, needle):
    lines = [line for line in text.splitlines() if needle in line]
    return lines[-1].strip() if lines else ""


def blender_python(blender):
    root = os.path.dirname(blender)
    for pattern in ("5.*/python/bin/python.exe", "5.*/python/bin/python3*"):
        found = sorted(glob.glob(os.path.join(root, pattern)))
        if found:
            return found[-1]
    return None


def install_cycle(blender, zip_path):
    """Install, enable/disable twice and uninstall the zip in an isolated Blender user profile."""
    profile = tempfile.mkdtemp(prefix="uex_profile_")
    env = dict(os.environ, BLENDER_USER_RESOURCES=profile)
    try:
        code, text = tooling.run([blender, "--factory-startup", "--command", "extension", "install-file", "-r",
                                  "user_default", zip_path], env=env)
        installed = os.path.isfile(os.path.join(profile, "extensions", "user_default", "unreal_exporter",
                                                "blender_manifest.toml"))
        result_path = os.path.join(profile, "enable.json")
        tooling.run(tooling.blender_command(blender, "--python", os.path.join(
            tooling.REPO_ROOT, "tests", "blender_gui", "enable_check.py"), "--", result_path), env=env)
        checks = []
        if os.path.isfile(result_path):
            with open(result_path, encoding="utf-8") as handle:
                checks = json.load(handle)["checks"]
        tooling.run([blender, "--factory-startup", "--command", "extension", "remove", "user_default.unreal_exporter"],
                    env=env)
        removed = not os.path.exists(os.path.join(profile, "extensions", "user_default", "unreal_exporter"))
        ok = code == 0 and installed and checks and all(c["ok"] for c in checks) and removed
        return ok, "installed=%s enable/disable=%s removed=%s" % (
            installed, "%d/%d" % (sum(c["ok"] for c in checks), len(checks)), removed)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def gui_checks(blender, addon_dir):
    """Undo/redo, the modal export and its dialogs; needs a real window, so this briefly opens Blender."""
    result_path = os.path.join(tooling.BUILD_DIR, "gui_result.json")
    if os.path.exists(result_path):
        os.remove(result_path)
    tooling.run([blender, "--factory-startup", "--window-geometry", "0", "0", "640", "480", "--python",
                 os.path.join(tooling.REPO_ROOT, "tests", "blender_gui", "gui_checks.py"), "--", result_path,
                 "--addon-dir", addon_dir], timeout=600)
    if not os.path.isfile(result_path):
        return False, "no result written"
    with open(result_path, encoding="utf-8") as handle:
        checks = json.load(handle)["checks"]
    failed = [c["name"] for c in checks if not c["ok"]]
    return not failed and bool(checks), "%d/%d GUI checks%s" % (
        len(checks) - len(failed), len(checks), (" failed: " + ", ".join(failed)) if failed else "")


def unit_tests(python, label):
    proc = subprocess.run([python, "-m", "unittest", "discover", "-s", "tests/unit", "-t", "."], cwd=tooling.REPO_ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = proc.stdout.decode("utf-8", errors="replace")
    record("unit tests (%s)" % label, "PASS" if proc.returncode == 0 else "FAIL",
           "%s %s" % (last_line(text, "Ran "), last_line(text, "OK") or last_line(text, "FAILED")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-unreal", action="store_true")
    parser.add_argument("--skip-gui", action="store_true", help="skip the GUI checks (they open a Blender window)")
    parser.add_argument("--allow-missing-unreal", action="store_true",
                        help="report missing engines as SKIPPED instead of failing")
    args = parser.parse_args()

    unit_tests(sys.executable, "Python %d.%d" % sys.version_info[:2])
    blender = tooling.find_blender()
    if blender is None:
        record("Blender 5.2 available", "FAIL", "set BLENDER_EXE")
    else:
        bundled = blender_python(blender)
        if bundled:
            unit_tests(bundled, "Blender bundled Python")
        else:
            record("unit tests (Blender bundled Python)", "SKIPPED", "bundled python not found")

    code = subprocess.run([sys.executable, os.path.join(tooling.REPO_ROOT, "scripts", "sync_unreal_plugin.py"),
                           "--check"]).returncode
    record("Unreal plugin importer in sync", "PASS" if code == 0 else "FAIL")

    if blender is not None:
        code, text = tooling.run(tooling.blender_command(
            blender, "--python-exit-code", "1", "--python",
            os.path.join(tooling.REPO_ROOT, "tests", "blender", "run_all.py")), timeout=3600)
        record("Blender integration tests (source)", "PASS" if code == 0 else "FAIL",
               "%s %s" % (last_line(text, "Ran "), last_line(text, "OK") or last_line(text, "FAILED")))
        zip_path = None
        try:
            zip_path = build_extension.build(tooling.DIST_DIR)
            record("extension validate + build + zip validate + audit", "PASS", os.path.basename(zip_path))
        except SystemExit as exc:
            record("extension validate + build + zip validate + audit", "FAIL", str(exc))
        if zip_path:
            temp = tempfile.mkdtemp(prefix="uex_release_")
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    archive.extractall(os.path.join(temp, "unreal_exporter"))
                code, text = tooling.run(tooling.blender_command(
                    blender, "--python-exit-code", "1", "--python",
                    os.path.join(tooling.REPO_ROOT, "tests", "blender", "run_all.py"), "--", "--addon-dir", temp),
                    timeout=3600)
                record("Blender integration tests (built zip)", "PASS" if code == 0 else "FAIL",
                       "%s %s" % (last_line(text, "Ran "), last_line(text, "OK") or last_line(text, "FAILED")))
                ok, evidence = install_cycle(blender, zip_path)
                record("install / enable / disable / uninstall (isolated profile)", "PASS" if ok else "FAIL",
                       evidence)
                if args.skip_gui:
                    record("GUI: undo/redo, modal export, dialogs", "SKIPPED", "--skip-gui")
                else:
                    ok, evidence = gui_checks(blender, temp)
                    record("GUI: undo/redo, modal export, dialogs", "PASS" if ok else "FAIL", evidence)
                if args.skip_unreal:
                    record("Unreal acceptance", "SKIPPED", "--skip-unreal")
                else:
                    cmd = [sys.executable, os.path.join(tooling.REPO_ROOT, "scripts", "run_unreal_tests.py"),
                           "--addon-dir", temp]
                    if args.allow_missing_unreal:
                        cmd.append("--allow-missing")
                    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=tooling.REPO_ROOT)
                    text = proc.stdout.decode("utf-8", errors="replace")
                    for version in ("5.8", "5.6"):
                        line = last_line(text, "UE %s" % version)
                        if "NOT INSTALLED" in line:
                            record("Unreal %s acceptance" % version, "SKIPPED" if args.allow_missing_unreal
                                   else "FAIL", "not installed")
                        elif " 0 failed" in line:
                            record("Unreal %s acceptance" % version, "PASS", line)
                        else:
                            record("Unreal %s acceptance" % version, "FAIL", line or text[-1500:])
            finally:
                shutil.rmtree(temp, ignore_errors=True)

    print("\nRELEASE CHECKLIST")
    for name, status, evidence in RESULTS:
        print("  %-8s %s%s" % (status, name, ("  -- " + evidence) if evidence else ""))
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    print("\n%s: %d passed, %d failed, %d skipped" % ("RELEASE GATE FAILED" if failed else "RELEASE GATE PASSED",
                                                     sum(1 for r in RESULTS if r[1] == "PASS"), len(failed),
                                                     sum(1 for r in RESULTS if r[1] == "SKIPPED")))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
