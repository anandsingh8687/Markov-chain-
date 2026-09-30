"""Shared helpers: find the repository, run commands, keep output short, keep a clock and a state line."""

import os
import subprocess
import sys
import time

BUDGET_S = int(os.environ.get("SWE_BUDGET_S", "300"))  # the harness's max_time_minutes (5) in seconds
OUTPUT_CAP = 4500  # run_command keeps only the first 5000 characters of a command's output
SCRIPT_TIMEOUT = 15  # default timeout for scripts and repro runs


def workspace():
    for cand in (os.environ.get("SWE_WS"), os.environ.get("PWD"), os.getcwd(), "/workspace"):
        if cand and os.path.exists(os.path.join(cand, ".git")):
            return cand
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if os.path.exists(os.path.join(parent, ".git")):
        return parent
    sys.exit("error: repository not found")


def _git_env(env=None):
    env = dict(os.environ if env is None else env)
    env["GIT_OPTIONAL_LOCKS"] = "0"  # read-only git commands never take .git/index.lock (a kill must not leave one)
    return env


def sh(cmd, cwd, timeout=120, env=None):
    try:
        r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True,
                           timeout=timeout, env=_git_env(env), errors="replace")
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        return 124, out or "", "TIMEOUT after %ss" % timeout


# ---------------------------------------------------------------- import path

def src_root(root):
    """<root>/src when the repository uses a src/ layout (src/<pkg>/__init__.py exists), else None."""
    src = os.path.join(root, "src")
    try:
        for d in os.listdir(src):
            if os.path.isfile(os.path.join(src, d, "__init__.py")):
                return src
    except OSError:
        pass
    return None


def top_packages(root):
    """Top-level package names of the repository itself (not tests/docs)."""
    out = []
    for base in filter(None, (src_root(root), root)):
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for d in names:
            if d.startswith(".") or d in ("tests", "test", "docs", "docs_src", "scripts", "examples", "benchmarks",
                                          "tools", "src", "build", "dist"):
                continue
            if os.path.isfile(os.path.join(base, d, "__init__.py")) and d.isidentifier() and d not in out:
                out.append(d)
    return out


def py_env(root, extra=None):
    """Environment whose PYTHONPATH puts <root>/src (src layout) and <root> first, so the repository's own
    code is imported, never an installed copy in site-packages."""
    env = dict(os.environ)
    first = [p for p in (src_root(root), root) if p]
    inherited = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p not in first]
    env["PYTHONPATH"] = os.pathsep.join(first + inherited)
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------- clock

def _mark(ws=None):
    import hashlib
    return hashlib.sha256(os.path.realpath(ws or workspace()).encode("utf-8")).hexdigest()[:16]


def swe_dir(ws=None):
    """Private scratch directory of the tools for this workspace (outside the repository)."""
    import tempfile
    d = os.path.join(tempfile.gettempdir(), ".swe", _mark(ws))
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


_T0 = []


def t0(ws=None):
    """Start of the session: the harness commits _swegemma_baseline seconds before the agent starts. Fall back
    to HEAD's commit time, then to the time install.py ran. None when no anchor is plausible."""
    if _T0:
        return _T0[0]
    now = time.time()
    cands = []
    if os.environ.get("SWE_T0"):
        try:
            cands.append(float(os.environ["SWE_T0"]))
        except ValueError:
            pass
    ws = ws or workspace()
    code, out, _ = sh(["git", "log", "-1", "--format=%ct", "_swegemma_baseline"], ws, timeout=10)
    if code or not out.strip():
        code, out, _ = sh(["git", "log", "-1", "--format=%ct", "HEAD"], ws, timeout=10)
    if not code and out.strip().isdigit():
        cands.append(float(out.strip()))
    try:
        with open(os.path.join(swe_dir(ws), "t0")) as fh:
            cands.append(float(fh.read().strip()))
    except (OSError, ValueError):
        pass
    val = None
    for c in cands:
        if -5 <= now - c <= 1200:  # an older anchor is not this session (a reused checkout)
            val = c
            break
    _T0.append(val)
    return val


def elapsed():
    s = t0()
    return None if s is None else max(0.0, time.time() - s)


def remaining():
    e = elapsed()
    return None if e is None else BUDGET_S - e


def cap(want):
    """A subprocess timeout no longer than the session time left (at least 3 s)."""
    r = remaining()
    if r is None:
        return want
    return max(3, int(min(want, r)))


def timeout_hint(seconds):
    return ("TIMED OUT after %d s. If the issue is about a hang, an infinite loop or slowness, this timeout IS the "
            "reproduction (check.py counts a timeout as FAILS). To see where it hangs, put "
            "`import faulthandler; faulthandler.dump_traceback_later(5)` at the top of the script. "
            "For a slow but valid script: run.py SCRIPT --timeout 40" % seconds)


def clean_stale_lock(ws):
    """A killed git command can leave .git/index.lock behind, which breaks the harness's own `git add -N .`."""
    lock = os.path.join(ws, ".git", "index.lock")
    try:
        if time.time() - os.path.getmtime(lock) < 30:
            return
    except OSError:
        return
    try:
        for pid in os.listdir("/proc"):
            if pid.isdigit():
                try:
                    with open("/proc/%s/comm" % pid) as fh:
                        if fh.read().strip() == "git":
                            return
                except OSError:
                    pass
        os.remove(lock)
    except OSError:
        pass


# ---------------------------------------------------------------- repository queries

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


def patch_digest(ws):
    _, diff, _ = sh(["git", "diff", "HEAD"], ws)
    _, new, _ = sh(["git", "ls-files", "--others", "--exclude-standard"], ws)
    return digest(diff, new)


def warn_if_repeated(argv):
    """Tell the model when it re-runs an identical tool command (Gemma tends to loop)."""
    import hashlib
    key = hashlib.sha1("\0".join(argv).encode("utf-8", "replace")).hexdigest()[:16]
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
    import tempfile
    return os.path.join(tempfile.gettempdir(), "%s-%s" % (name, _mark()))


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
    path = _state_path()
    try:
        with open(path + ".tmp", "w") as fh:
            json.dump(state, fh)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def digest(*parts):
    import hashlib
    return hashlib.sha1("\0".join(parts).encode("utf-8", "replace")).hexdigest()[:16]


# ---------------------------------------------------------------- repro bookkeeping

def is_repro(path):
    return os.path.basename(path or "").startswith("repro")


def record_repro(state, script, body, result, patch_empty):
    """Remember the latest result of the repro: 'before' = on the original code, 'now' = on the current code."""
    rs = state.get("rs") or {}
    if rs.get("path") != script or rs.get("body") != body:
        rs = {"path": script, "body": body, "before": "?", "now": "?"}
    if result in ("FAILS", "passes"):
        rs["now"] = result
        if patch_empty:
            rs["before"] = result
    state["rs"] = rs


def result_word(code):
    return "passes" if code == 0 else "FAILS"


def count_rewrite(state, body, patch_empty):
    """Distinct repro contents written while the patch is empty (repro churn)."""
    if not patch_empty:
        return
    bodies = state.setdefault("repro_bodies", [])
    if body not in bodies:
        bodies.append(body)
        del bodies[:-50]
        state["rewrites"] = state.get("rewrites", 0) + (1 if len(bodies) > 1 else 0)


# ---------------------------------------------------------------- state line

def _patch_summary(ws):
    _, num, _ = sh(["git", "diff", "--numstat", "HEAD"], ws, timeout=20)
    _, new, _ = sh(["git", "ls-files", "--others", "--exclude-standard"], ws, timeout=20)
    items = []
    for line in num.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            items.append("%s +%s-%s" % (parts[2], parts[0], parts[1]))
    for f in new.splitlines():
        if f.strip():
            items.append("%s (new)" % f)
    if not items:
        return "EMPTY", True
    text = items[0] if len(items) == 1 else "%s (+%d more files)" % (items[0], len(items) - 1)
    return text, False


def state_line(ws=None):
    try:
        ws = ws or workspace()
        state = load_state()
        e = elapsed()
        clock = "T+%ds/%d" % (e, BUDGET_S) if e is not None else "T+?/%d" % BUDGET_S
        patch, empty = _patch_summary(ws)
        rs = state.get("rs") or {}
        if rs.get("path"):
            if empty:
                rep = "repro %s: %s" % (rs["path"], rs.get("now", "?"))
            else:
                rep = "repro %s: %s->%s" % (rs["path"], rs.get("before", "?"), rs.get("now", "?"))
        else:
            rep = "repro: none"
        verdict = state.get("last_verdict") or ""
        if not verdict:
            chk = "not run"
        else:
            chk = "OK" if verdict.startswith("OK") else "FIX"
            if not empty and state.get("verdict_patch") and state.get("verdict_patch") != patch_digest(ws):
                chk += " (patch changed since)"
        parts = [clock, "patch: " + patch, rep, "check: " + chk, "rewrites %d" % state.get("rewrites", 0)]
        r = remaining()
        if empty and e is not None and e >= 180:
            parts.append("EDIT NOW: make the most likely edit")
        elif r is not None and r < 60 and not empty:
            parts.append("LOW TIME: submit_patch now")
        return "[" + " | ".join(parts) + "]"
    except Exception as exc:  # the state line must never break a tool
        return "[state unavailable: %s]" % str(exc)[:80]


# ---------------------------------------------------------------- output wrapper

def add_context(n):
    pass  # the context counter stays disabled: the real harness compacts history at ~14k tokens


def _cap_text(text, limit):
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.62), int(limit * 0.33)
    cut = len(text) - head - tail
    return text[:head] + "\n... [%d characters cut] ...\n" % cut + text[-tail:]


def run_tool(main):
    """Run a tool's main(): buffer its output, then print the state line FIRST and at most OUTPUT_CAP chars.
    (run_command keeps only the head of the output, and after a history summary the latest tool output is
    what the model still sees.)"""
    import io
    real = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    code = 0
    try:
        ws = None
        try:
            ws = workspace()
            clean_stale_lock(ws)
        except SystemExit:
            raise
        except Exception:
            pass
        main()
    except SystemExit as exc:
        if isinstance(exc.code, str):
            buf.write(exc.code + "\n")
            code = 1
        else:
            code = exc.code or 0
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:  # never leave the model with a bare traceback
        import traceback
        buf.write("tool error: %s\n%s" % (exc, "".join(traceback.format_exc().splitlines(True)[-4:])))
        code = 1
    finally:
        sys.stdout = real
    line = state_line()
    out = line + "\n" + buf.getvalue().rstrip("\n") + "\n"
    real.write(_cap_text(out, OUTPUT_CAP))
    real.flush()
    sys.exit(code)
