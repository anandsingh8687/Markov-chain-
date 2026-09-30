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
        return True
    else:
        try:
            with open(path, "a") as fh:
                fh.write(key + "\n")
        except OSError:
            pass
    return False


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


# The model has a 32k-token context and every command and its output stay in it. Count the text our
# tools add and warn before the context overflows (which ends the task with whatever is in the tree).
CONTEXT_WARN, CONTEXT_STOP = 10**9, 10**9  # disabled: the real harness compacts history at ~14k tokens, so a cumulative count misleads


def add_context(n):
    pass


def track_context(extra=0):
    import atexit

    real = sys.stdout

    class _Counter:
        n = extra

        def write(self, s):
            _Counter.n += len(s)
            return real.write(s)

        def flush(self):
            real.flush()

        def __getattr__(self, name):
            return getattr(real, name)

    sys.stdout = _Counter()
    global add_context

    def add_context(n):  # text the model sent (e.g. a heredoc) also stays in its context
        _Counter.n += n

    def _done():
        state = load_state()
        total = state.get("context_chars", 0) + _Counter.n + 400  # plus the model's own reply
        state["context_chars"] = total
        save_state(state)
        if total >= CONTEXT_STOP:
            real.write("\nCONTEXT ALMOST FULL: the session ends soon. If your patch is empty, make your best edit "
                       "now (never revert to an empty patch). Then run check.py once and call submit_patch.\n")
        elif total >= CONTEXT_WARN:
            real.write("\nCONTEXT 75% USED: stop exploring. Make your change now if you have not, verify it with "
                       "check.py, and fix what its VERDICT lists before you submit.\n")
        real.flush()

    atexit.register(_done)
