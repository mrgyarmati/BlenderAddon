"""Locate Blender / Unreal and run them. Shared by the scripts in this folder.

Override discovery with environment variables:
  BLENDER_EXE        path to blender(.exe), Blender 5.2
  UE_5_6_EDITOR      path to UnrealEditor-Cmd(.exe) for 5.6 (same pattern for 5_7, 5_8, ...)
"""

import glob
import os
import platform
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_DIR = os.path.join(REPO_ROOT, "addon", "unreal_exporter")
BUILD_DIR = os.path.join(REPO_ROOT, "build")
DIST_DIR = os.path.join(REPO_ROOT, "dist")


def find_blender():
    env = os.environ.get("BLENDER_EXE")
    if env and os.path.isfile(env):
        return env
    candidates = []
    system = platform.system()
    if system == "Windows":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), r"D:\Program Files"):
            candidates += sorted(glob.glob(os.path.join(root, "Blender Foundation", "Blender 5.*", "blender.exe")),
                                 reverse=True)
    elif system == "Darwin":
        candidates.append("/Applications/Blender.app/Contents/MacOS/Blender")
    found = shutil.which("blender")
    if found:
        candidates.append(found)
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def find_unreal(version):
    """UnrealEditor-Cmd for ``version`` ('5.6', '5.8'), or None."""
    env = os.environ.get("UE_%s_EDITOR" % version.replace(".", "_"))
    if env and os.path.isfile(env):
        return env
    if platform.system() == "Windows":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), r"D:\Program Files", r"D:\Epic Games",
                     r"E:\Epic Games"):
            for base in (os.path.join(root, "Epic Games", "UE_" + version), os.path.join(root, "UE_" + version)):
                exe = os.path.join(base, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")
                if os.path.isfile(exe):
                    return exe
    elif platform.system() == "Linux":
        for base in glob.glob(os.path.expanduser("~/UnrealEngine*%s*" % version)):
            exe = os.path.join(base, "Engine", "Binaries", "Linux", "UnrealEditor-Cmd")
            if os.path.isfile(exe):
                return exe
    return None


def blender_command(blender, *args, factory=True):
    cmd = [blender, "--background"]
    if factory:
        cmd.append("--factory-startup")
    return cmd + list(args)


def run(cmd, timeout=3600, log_path=None, env=None):
    """Run ``cmd``; stream to a log file when given. Returns (exit code, output text)."""
    print("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    sys.stdout.flush()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env,
                          cwd=REPO_ROOT)
    text = proc.stdout.decode("utf-8", errors="replace")
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return proc.returncode, text


UPROJECT_TEMPLATE = """{
\t"FileVersion": 3,
\t"EngineAssociation": "%s",
\t"Category": "",
\t"Description": "Blender Unreal Bridge acceptance-test project (generated, disposable)",
\t"Plugins": [
\t\t{ "Name": "PythonScriptPlugin", "Enabled": true },
\t\t{ "Name": "EditorScriptingUtilities", "Enabled": true }
\t]
}
"""


def ensure_project(version, projects_dir=None):
    """Create (once) a minimal content-only project for ``version``; return the .uproject path."""
    projects_dir = projects_dir or os.path.join(BUILD_DIR, "ue_projects")
    name = "BridgeTest" + version.replace(".", "")
    folder = os.path.join(projects_dir, name)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + ".uproject")
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(UPROJECT_TEMPLATE % version)
    return path


def require_no_spaces(path, what):
    if " " in path:
        raise SystemExit("%s path must not contain spaces for Unreal's -Script argument: %s" % (what, path))
