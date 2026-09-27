"""Shared helpers: find the repository, run commands, keep output short."""

import os
import subprocess
import sys


def workspace():
    for cand in (os.environ.get("SWE_WS"), os.environ.get("PWD"), os.getcwd(), "/workspace"):
        if cand and os.path.isdir(os.path.join(cand, ".git")):
            return cand
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if os.path.isdir(os.path.join(parent, ".git")):
        return parent
    sys.exit("error: repository not found")


def sh(cmd, cwd, timeout=120):
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") if isinstance(e.stdout, str) else "", "TIMEOUT after %ss" % timeout


def tracked_py(ws):
    _, out, _ = sh(["git", "ls-files", "*.py"], ws)
    return [f for f in out.splitlines() if f]


def is_test_path(path):
    parts = path.split("/")
    name = parts[-1]
    return ("tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")
            or name == "conftest.py")


def changed_files(ws):
    """Modified tracked files plus new untracked files (what submit_patch would include)."""
    _, mod, _ = sh(["git", "diff", "--name-only", "HEAD"], ws)
    _, new, _ = sh(["git", "ls-files", "--others", "--exclude-standard"], ws)
    return [f for f in mod.splitlines() if f], [f for f in new.splitlines() if f]
