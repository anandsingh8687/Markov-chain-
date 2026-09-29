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


def warn_if_repeated(argv):
    """Tell the model when it re-runs an identical tool command (Gemma tends to loop)."""
    import hashlib
    import tempfile
    key = hashlib.sha1("\0".join(argv).encode()).hexdigest()[:16]
    path = _workspace_state_path(".swetools_seen")
    try:
        with open(path) as fh:
            seen = set(fh.read().split())
    except OSError:
        seen = set()
    if key in seen:
        print("NOTE: you already ran this exact command. Repeating it gives the same answer: use what you "
              "learned and take the next step (edit, check.py, or submit_patch).\n")
    else:
        try:
            with open(path, "a") as fh:
                fh.write(key + "\n")
        except OSError:
            pass


def _workspace_state_path(name):
    """Keep guard state separate when several sandbox workspaces share TMPDIR."""
    import hashlib
    import tempfile
    marker = hashlib.sha256(os.path.realpath(workspace()).encode("utf-8")).hexdigest()[:16]
    return os.path.join(tempfile.gettempdir(), "%s-%s" % (name, marker))


def _state_path():
    return _workspace_state_path(".swetools_state.json")


def load_state():
    import json
    try:
        with open(_state_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    import json
    try:
        with open(_state_path(), "w") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def digest(*parts):
    import hashlib
    return hashlib.sha1("\0".join(parts).encode("utf-8", "replace")).hexdigest()[:16]
