"""Shared helpers: find the repository, run commands, keep output short, keep a clock and a state line."""

import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_CFG = []


def cfg():
    """Mode flag written by the duo installer next to the tools (_cfg.json). Absent = solo mode (v23)."""
    if not _CFG:
        import json
        try:
            with open(os.path.join(_HERE, "_cfg.json")) as fh:
                _CFG.append(json.load(fh))
        except (OSError, ValueError):
            _CFG.append({})
    return _CFG[0]


def duo():
    return cfg().get("mode") == "duo"


def att():
    return cfg().get("att", "")
# <seq>


def seq():
    """Sequential two-attempt mode (bundle_v25, _seq.py). Everything from a '# <seq>' line through the next
    '# </seq>' line is stripped from the solo and duo builds (make_skill.py), so bundle_v23 / bundle_v24 stay
    byte-identical."""
    return cfg().get("mode") == "seq"
# </seq>


BUDGET_S = int(cfg().get("budget_s") or os.environ.get("SWE_BUDGET_S", "300"))  # max_time_minutes in seconds
# Duo: the attempts stop at DEADLINE_S; the tools then pick the patch (solo: the deadline is the budget).
DEADLINE_S = int(os.environ.get("SWE_DEADLINE_S") or cfg().get("deadline_s") or BUDGET_S)
# run_command keeps only the first 5000 characters of a command's output. Duo: both attempts share one session
# whose history is compacted at ~14k prompt tokens, so each output is kept shorter to delay that.
OUTPUT_CAP = 2500 if duo() else 4500
VIEW_LINES = 30 if duo() else 40  # show.py lines per view
SCRIPT_TIMEOUT = 15  # default timeout for scripts and repro runs
CAP_LEFT = []  # pick_patch: a function giving its own seconds left (it runs after the attempt deadline)
CONTROL = []  # lines a tool wants printed FIRST (before the state line), e.g. the FINAL line in duo mode
WARN = []  # duo: warnings printed right after CONTROL (e.g. a plain command changed /workspace)


def workspace():
    c = cfg()
    if c.get("ws") and os.path.exists(os.path.join(c["ws"], ".git")):
        return c["ws"]  # duo: the tools are bound to one attempt's repository
    for cand in (os.environ.get("SWE_WS"), os.environ.get("PWD"), os.getcwd(), "/workspace"):
        if cand and os.path.exists(os.path.join(cand, ".git")):
            return cand
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if os.path.exists(os.path.join(parent, ".git")):
        return parent
    sys.exit("error: repository not found")


def real_workspace():
    """The harness's /workspace (what submit_patch diffs). Equals workspace() except for attempt B."""
    c = cfg()
    if c.get("real_ws") and os.path.exists(os.path.join(c["real_ws"], ".git")):
        return c["real_ws"]
    return workspace()


def rel_arg(arg):
    """Map a file argument to a path relative to this attempt's repository when it names a file in it,
    in the real /workspace (attempt B: mapped to its copy) or under a literal /workspace prefix.
    Anything else is returned unchanged."""
    if not arg or not arg.startswith("/"):
        return arg
    ws, real = workspace(), real_workspace()
    prefixes = []
    for p in (ws, os.path.realpath(ws), real, os.path.realpath(real), "/workspace"):
        if p not in prefixes:
            prefixes.append(p)
    for p in sorted(prefixes, key=len, reverse=True):
        if arg == p:
            return "."
        if arg.startswith(p.rstrip("/") + "/"):
            return arg[len(p.rstrip("/")) + 1:]
    return arg


def scratch_path(path):
    """Duo, attempt B: any /tmp path outside B's scratch dir maps to it (never shares A's scripts)."""
    import tempfile
    c = cfg()
    if not duo() or c.get("att") != "b" or not path or not c.get("scratch"):
        return path
    sc = os.path.realpath(c["scratch"])
    real = os.path.realpath(path)
    if real == sc or real.startswith(sc + os.sep):
        return path
    tmp = os.path.realpath(tempfile.gettempdir())
    if path.startswith("/tmp/") or real.startswith(tmp + os.sep):
        return os.path.join(c["scratch"], os.path.basename(path))
    return path


def bound_script(script):
    """Attempt B: a copy of the script with every /workspace path pointed at B's copy (the real
    /workspace is attempt A's). Returns the path to run."""
    if not duo() or att() != "b":
        return script
    try:
        with open(script, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError:
        return script
    new = rewrite_ws_paths(body, workspace())
    if new == body:
        return script
    path = os.path.join(os.path.dirname(script), "." + os.path.basename(script) + ".bound.py")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
    except OSError:
        return script
    return path


def rewrite_ws_paths(text, target):
    """Replace the real workspace path(s) and a literal /workspace in text with target."""
    import re
    real = real_workspace()
    new = text
    for p in sorted({real, os.path.realpath(real)}, key=len, reverse=True):
        if p and p != target:
            new = new.replace(p, "\0WS\0")
    new = re.sub(r"(?<![\w.-])/workspace(?![\w.-])", "\0WS\0", new)
    return new.replace("\0WS\0", target)


def shell_hint(cmd):
    """How the model should run a shell command that changes files. Duo: through sh.py (attempt B: in its copy;
    attempt A: a change of /workspace by a plain command is undone at the next tool call)."""
    if duo():
        import shlex
        return "python3 %s/sh.py %s" % (cfg().get("tools_display", "/tmp/b/t" if att() == "b" else ".swetools"),
                                        shlex.quote(cmd))
    return cmd


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
    if duo():
        real = os.path.realpath(real_workspace())
        if os.path.realpath(root) != real:  # attempt B / the baseline copy: never import attempt A's code
            inherited = [p for p in inherited
                         if not (os.path.realpath(p) == real or os.path.realpath(p).startswith(real + os.sep))]
    env["PYTHONPATH"] = os.pathsep.join(first + inherited)
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------- clock

def _mark(ws=None):
    import hashlib
    return hashlib.sha256(os.path.realpath(ws or workspace()).encode("utf-8")).hexdigest()[:16]


def swe_dir(ws=None):
    """Private scratch directory of the tools for this workspace (outside the repository). In duo mode
    both attempts share the directory of the real /workspace (baseline copy, lock, snapshots, FINAL)."""
    import tempfile
    if duo():
        ws = real_workspace()
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
    ws = ws or real_workspace()
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


_VCLOCK = []


def vclock():
    """The lab's virtual clock (lab/labworker.py writes <TMPDIR>/.swe_vclock before every sandbox command):
    {"v": agent seconds on the harness clock, "wall": time.time() when written, "rate": clock seconds per wall
    second while a command runs}. None outside the lab (the real harness never writes it)."""
    if not _VCLOCK:
        import json
        import tempfile
        val = None
        try:
            with open(os.path.join(tempfile.gettempdir(), ".swe_vclock")) as fh:
                d = json.load(fh)
            v, wall, rate = float(d["v"]), float(d["wall"]), float(d.get("rate", 1.0))
            if 0 <= time.time() - wall <= 3600 and rate > 0:
                val = (v, wall, rate)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        _VCLOCK.append(val)
    return _VCLOCK[0]


def clock_rate():
    """Session-clock seconds per real second (1 except under the lab's scaled clock)."""
    vc = vclock()
    return vc[2] if vc else 1.0


def elapsed():
    vc = vclock()
    if vc is not None:  # lab: the harness's (virtual or scaled) clock, advanced by real time since the command began
        return max(0.0, vc[0] + (time.time() - vc[1]) * vc[2])
    s = t0()
    return None if s is None else max(0.0, time.time() - s)


def remaining():
    e = elapsed()
    return None if e is None else BUDGET_S - e


def attempt_left():
    """Seconds until this attempt ends: the duo deadline, or the session budget in solo mode."""
    e = elapsed()
    return None if e is None else DEADLINE_S - e


def cap(want):
    """A subprocess timeout (real seconds) no longer than the time left (duo: until the attempt deadline; at
    least 3 s). The time left is on the session clock; under the lab's scaled clock it is converted to real s."""
    if CAP_LEFT:
        r = CAP_LEFT[0]()  # pick_patch: already real seconds
    else:
        r = attempt_left() if duo() else remaining()
        if r is not None:
            r = r / clock_rate()
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


def _workspace_state_path(name, ws=None):
    """Keep guard state separate when several sandbox workspaces share TMPDIR."""
    import tempfile
    return os.path.join(tempfile.gettempdir(), "%s-%s" % (name, _mark(ws)))


def _state_path(ws=None):
    return _workspace_state_path(".swetools_state.json", ws)


def load_state(ws=None):
    import json
    try:
        with open(_state_path(ws)) as fh:
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
        limit = DEADLINE_S if duo() else BUDGET_S
        clock = "T+%ds/%d" % (e, limit) if e is not None else "T+?/%d" % limit
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
        if duo():
            # the attempt letter and its own repository first: after a history summary that mixes both attempts,
            # every surviving tool output still says whose work it describes
            who = "%s %s" % ((att() or "a").upper(), "/workspace" if att() != "b" else cfg().get("repo_display",
                                                                                                    "/tmp/b/repo"))
            al = attempt_left()
            if os.path.exists(os.path.join(swe_dir(), "final.json")):
                return "[" + " | ".join([who] + parts[:2] + ["attempts over"]) + "]"
            if empty and e is not None and e >= 0.6 * DEADLINE_S:
                parts.append("EDIT NOW: make the most likely edit")
            elif al is not None and al < 45 and not empty:
                parts.append("LOW TIME: finish with check.py; at T+%d the tools pick the patch" % DEADLINE_S)
            parts.append("only tool calls until FINAL; never submit_patch before FINAL")
            return "[" + " | ".join([who] + parts) + "]"
        r = remaining()
        if empty and e is not None and e >= 180:
            parts.append("EDIT NOW: make the most likely edit")
        elif r is not None and r < 60 and not empty:
            # never 'submit now': the end-of-run diff keeps the tree, and late fixes still count
            parts.append("LOW TIME: finish this fix, no new exploration; submit only after check.py OK")
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
    # <seq>
    if seq():
        import _seq
        return _seq.run_tool(main)
    # </seq>
    import io
    real = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    code = 0
    skip = False
    try:
        ws = None
        try:
            ws = workspace()
            clean_stale_lock(ws)
            if duo():
                clean_stale_lock(real_workspace())
        except SystemExit:
            raise
        except Exception:
            pass
        if duo():
            import _duo
            skip = _duo.before_tool(os.path.basename(sys.argv[0]))
        if not skip:
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
    if duo():
        try:
            import _duo
            _duo.after_tool()
        except Exception:
            pass
        out = "".join(l + "\n" for l in CONTROL + WARN) + out
        out = _duo.display(out)
    real.write(_cap_text(out, OUTPUT_CAP))
    real.flush()
    sys.exit(code)
