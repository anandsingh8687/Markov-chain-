"""Check the current patch before submit_patch().

usage: python3 .swetools/check.py --repro /tmp/repro.py [TEST_FILE ...]

0. With --repro, runs the reproduction script WITHOUT your change and WITH it:
   a correct repro exits non-zero (AssertionError) before and 0 after.

1. Lists what the patch contains and flags problems: files under tests/,
   conftest.py / pytest.ini changes, stray new files (scratch scripts).
2. Compiles and imports every changed Python module.
3. Runs the test files for the changed code (or the TEST_FILEs given) and,
   for any failure, reruns it without your change to tell you whether YOUR
   change caused it.
Ends with a one-line VERDICT.
"""

import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
from _ws import changed_files, is_test_path, load_state, save_state, sh, tracked_py, warn_if_repeated, workspace  # noqa: E402

PYTEST = "python3 -m pytest -q -p no:cacheprovider -o addopts='' -p no:anyio --import-mode=importlib"


def module_name(path):
    p = path[:-3] if path.endswith(".py") else path
    for prefix in ("src/",):
        if p.startswith(prefix):
            p = p[len(prefix):]
    p = p.replace("/", ".")
    return p[:-9] if p.endswith(".__init__") else p


def related_tests(ws, changed_src):
    tests = [t for t in tracked_py(ws) if is_test_path(t) and os.path.basename(t) != "conftest.py"]
    scores = {}
    mods = [module_name(f) for f in changed_src]
    stems = [os.path.splitext(os.path.basename(f))[0] for f in changed_src]
    for t in tests:
        base = os.path.basename(t)
        s = 0
        for stem in stems:
            if stem != "__init__" and base in ("test_%s.py" % stem, "%s_test.py" % stem):
                s += 50
        try:
            with open(os.path.join(ws, t), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for mod in mods:
            if mod and ("import " + mod in text or "from " + mod + " " in text or "from " + mod + "." in text):
                s += 10
        if s:
            scores[t] = s
    return [t for t, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:4]]


def removed_lines(ws):
    """Non-trivial lines the patch removed or replaced, with their file."""
    _, diff, _ = sh(["git", "diff", "-U0", "HEAD", "--", "*.py"], ws)
    out, cur = [], None
    skip = ("#", '"' * 3, "'" * 3, "import ", "from ")
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            cur = line[6:]
        elif line.startswith("-") and not line.startswith("---") and cur and not is_test_path(cur):
            text = line[1:].strip()
            if len(text) >= 14 and not text.startswith(skip):
                out.append((cur, text))
    return out


def added_lines(ws):
    """{file: set of line numbers} that the patch added (so they are not reported as old copies)."""
    _, diff, _ = sh(["git", "diff", "-U0", "HEAD", "--", "*.py"], ws)
    out, cur = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
        m = re.match(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
        if m and cur:
            start, count = int(m.group(1)), int(m.group(2) or 1)
            out.setdefault(cur, set()).update(range(start, start + count))
    return out


def sibling_sweep(ws):
    """Places that still contain code the patch changed elsewhere (same bug, other copy)."""
    notes, seen = [], set()
    mine = added_lines(ws)
    for f, text in removed_lines(ws)[:12]:
        if text in seen:
            continue
        seen.add(text)
        _, out, _ = sh(["git", "grep", "-n", "-F", "-e", text, "--", "*.py"], ws)
        for hit in out.splitlines()[:6]:
            path, lineno = hit.split(":", 2)[:2]
            if lineno.isdigit() and int(lineno) in mine.get(path, ()):
                continue
            if not is_test_path(path):
                notes.append("%s  still has: %s" % (":".join(hit.split(":", 2)[:2]), text[:90]))
    return notes[:6]


def changed_names(ws):
    """Functions/classes around the changed hunks (from the diff hunk headers)."""
    _, diff, _ = sh(["git", "diff", "HEAD", "--", "*.py"], ws)
    names = set()
    for m in re.finditer(r"^@@[^@]*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)", diff, re.M):
        names.add(m.group(1))
    for m in re.finditer(r"^\+\s*(?:async\s+)?(?:def|class)\s+(\w+)", diff, re.M):
        names.add(m.group(1))
    return [n for n in names if not n.startswith("__") and len(n) > 3]


def tests_mentioning(ws, names, exclude):
    if not names:
        return []
    tests = [t for t in tracked_py(ws) if is_test_path(t) and os.path.basename(t) != "conftest.py"]
    hits = {}
    for t in tests:
        if t in exclude:
            continue
        try:
            with open(os.path.join(ws, t), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        c = sum(text.count(n) for n in names)
        if c:
            hits[t] = c
    return [t for t, _ in sorted(hits.items(), key=lambda kv: -kv[1])[:2]]


def failed_ids(out):
    ids = set(re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.M))
    ids |= set(m.group(1) for m in re.finditer(r"^(\S+::\S+) (?:FAILED|ERROR)\b", out, re.M))
    return sorted(ids)


# ---------------------------------------------------------------- pristine baseline copy
# The 'without your change' runs happen in a private clone of the baseline commit, never by stashing
# /workspace: when the harness kills a command at the deadline, a stash would take the patch with it.

SKIP_DIRS = {".swetools", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", ".venv",
             "venv", "node_modules", ".git", ".hypothesis", "htmlcov", ".eggs", ".cache", ".idea", ".vscode"}


def _baseline_sha(ws):
    for ref in ("_swegemma_baseline", "HEAD"):
        code, out, _ = sh(["git", "rev-parse", "-q", "--verify", ref + "^{commit}"], ws, timeout=10)
        if not code and out.strip():
            return out.strip()
    return None


def _copy_ignored(ws, base):
    """Ignored-but-present files (generated modules, version files, egg-info) that imports may need."""
    import shutil
    code, out, _ = sh(["git", "ls-files", "-oi", "--exclude-standard", "--directory"], ws, timeout=20)
    if code:
        return 0
    n, total = 0, 0
    for rel in out.splitlines():
        rel = rel.rstrip("/")
        parts = rel.split("/")
        if not rel or any(p in SKIP_DIRS for p in parts) or parts[-1].startswith(".adk_exec_"):
            continue
        src = os.path.join(ws, rel)
        items = []
        if os.path.isdir(src) and not os.path.islink(src):
            for root, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in files:
                    items.append(os.path.relpath(os.path.join(root, f), ws))
                if len(items) > 3000:
                    break
        else:
            items.append(rel)
        for r in items:
            if r.endswith((".pyc", ".pyo")):
                continue
            s_, d_ = os.path.join(ws, r), os.path.join(base, r)
            try:
                size = os.path.getsize(s_)
                if size > 5 * 2 ** 20 or total + size > 40 * 2 ** 20 or n >= 3000:
                    continue
                if os.path.exists(d_):
                    continue
                os.makedirs(os.path.dirname(d_), exist_ok=True)
                shutil.copy2(s_, d_, follow_symlinks=False)
                n += 1
                total += size
            except OSError:
                pass
    return n


def ensure_base(ws):
    """Path of a clean clone of the baseline commit (created lazily, reset when dirty), or (None, reason)."""
    import shutil
    sha = _baseline_sha(ws)
    if not sha:
        return None, "no baseline commit"
    d = _ws.swe_dir(ws)
    base = os.path.join(d, "base")
    benv = {"GIT_OPTIONAL_LOCKS": "0"}
    for attempt in range(2):
        if os.path.isdir(os.path.join(base, ".git")):
            try:
                os.remove(os.path.join(base, ".git", "index.lock"))
            except OSError:
                pass
            code, head, _ = sh(["git", "rev-parse", "HEAD"], base, timeout=10)
            if not code and head.strip() != sha:
                code, _, _ = sh(["git", "checkout", "-q", "-f", "--detach", sha], base, timeout=30)
                head = sha if not code else ""
            if not code and head.strip() == sha:
                code, st, _ = sh(["git", "status", "--porcelain"], base, timeout=30, env=dict(os.environ, **benv))
                if not code and st.strip():
                    code, _, _ = sh("git checkout -q -f -- . && git clean -fdq", base, timeout=30)
                    if not code:
                        code, st, _ = sh(["git", "status", "--porcelain"], base, timeout=30)
                if not code and not st.strip():
                    return base, ""
        # (re)create: clone into a temp dir, then rename, so a kill never leaves a half clone at `base`
        shutil.rmtree(base, ignore_errors=True)
        tmp = base + ".new"
        shutil.rmtree(tmp, ignore_errors=True)
        code, _, err = sh(["git", "clone", "-q", "--shared", "--no-checkout", ws, tmp], d, timeout=_ws.cap(60))
        if code:
            return None, "clone failed: %s" % (err.strip().splitlines() or ["?"])[-1][:120]
        code, _, err = sh(["git", "checkout", "-q", "--detach", sha], tmp, timeout=_ws.cap(60))
        if code:
            shutil.rmtree(tmp, ignore_errors=True)
            return None, "checkout failed: %s" % (err.strip().splitlines() or ["?"])[-1][:120]
        try:
            excl = os.path.join(ws, ".git", "info", "exclude")
            if os.path.isfile(excl):
                os.makedirs(os.path.join(tmp, ".git", "info"), exist_ok=True)
                shutil.copy(excl, os.path.join(tmp, ".git", "info", "exclude"))
        except OSError:
            pass
        _copy_ignored(ws, tmp)
        try:
            os.rename(tmp, base)
        except OSError as exc:
            return None, "rename failed: %s" % exc
    return None, "could not reset the baseline copy"


def base_env(base):
    return _ws.py_env(base, {"PYTHONDONTWRITEBYTECODE": "1"})


def base_imports(ws, base, changed_src):
    """None when the repository's package(s) import in the baseline copy, else the error."""
    pkgs = []
    for f in changed_src:
        top = module_name(f).split(".")[0]
        if top and top not in pkgs and top in _ws.top_packages(ws):
            pkgs.append(top)
    pkgs = (pkgs or _ws.top_packages(ws))[:2]
    for p in pkgs:
        t = _ws.cap(20)
        code, out, err = sh(["timeout", "-k", "2", str(t), "python3", "-c", "import " + p], base, timeout=t + 5,
                            env=base_env(base))
        if code:
            return "import %s fails there: %s" % (p, ((err or out).strip().splitlines() or ["?"])[-1][:150])
    return None


def script_for_base(ws, base, repro):
    """A copy of the repro with every /workspace path pointed at the baseline copy."""
    try:
        body = open(repro, encoding="utf-8", errors="replace").read()
    except OSError:
        return repro
    new = body
    for p in sorted({ws, os.path.realpath(ws)}, key=len, reverse=True):
        new = new.replace(p, "\0BASE\0")
    new = re.sub(r"(?<![\w.-])/workspace(?![\w.-])", "\0BASE\0", new)
    new = new.replace("\0BASE\0", base)
    if new == body:
        return repro
    path = os.path.join(_ws.swe_dir(ws), "base_" + os.path.basename(repro))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return path


def _run_script(script, cwd, env, limit):
    t = _ws.cap(limit)
    code, out, _ = sh(["bash", "-c", "set -o pipefail; timeout -k 2 %d python3 -B %s 2>&1 | tail -6"
                       % (t, shlex.quote(script))], cwd, timeout=t + 10, env=env)
    return code, out, t


def _describe(code, t):
    if code in (124, 137):
        return "FAILS (TIMED OUT after %d s: a hang)" % t
    return "FAILS (exit %d)" % code if code else "passes"


def run_repro(ws, repro, empty_patch, changed_src, info):
    """Run the repro on the original code (baseline copy) and on the current code."""
    if not os.path.isfile(repro):
        return ["repro script %s not found: write it first (in /tmp)" % repro]
    code1, out1, t1 = _run_script(repro, ws, _ws.py_env(ws), _ws.SCRIPT_TIMEOUT)
    code0, out0, why, tb = None, "", "", _ws.SCRIPT_TIMEOUT
    if empty_patch:
        code0, out0, tb = code1, out1, t1
    else:
        r = _ws.remaining()
        if r is not None and r < 20:
            why = "LOW TIME, skipped"
        else:
            base, why = ensure_base(ws)
            if base:
                why = base_imports(ws, base, changed_src) or ""
                if not why:
                    code0, out0, tb = _run_script(script_for_base(ws, base, repro), base, base_env(base),
                                                   _ws.SCRIPT_TIMEOUT)
    print("REPRO %s" % repro)
    if code0 is None:
        print("  without your change: UNKNOWN (could not run it on the original code: %s)" % why)
    else:
        print("  without your change: %s" % _describe(code0, tb))
        for line in out0.strip().splitlines()[-3:]:
            print("      " + line[:200])
    print("  with your change:    %s" % _describe(code1, t1))
    for line in out1.strip().splitlines()[-4:]:
        print("      " + line[:200])
    info["before"] = "?" if code0 is None else _ws.result_word(code0)
    info["now"] = _ws.result_word(code1)
    problems = []
    try:
        body = open(repro, encoding="utf-8", errors="replace").read()
    except OSError:
        body = ""
    info["body"] = _ws.digest(body)
    private = sorted(set(re.findall(r"^\s*(?:from|import)\s+([\w.]*\._[\w.]*|[\w.]*_compat[\w.]*)\b",
                                    body, re.M)))
    if private:
        problems.append("your repro imports internals (%s). The hidden tests use the public API only: rewrite the repro "
                        "through the public entry point (app + TestClient, render to a string, a public call) as the "
                        "existing tests do" % ", ".join(private[:3]))
    if code0 == 0:
        problems.append("the repro passes WITHOUT your change, so it does not reproduce the issue: make it use the "
                        "public API exactly as the issue describes and assert the expected result; if it truly "
                        "passes, the bug is elsewhere - try other input shapes and entry points. (If the issue "
                        "asks for no behaviour change, e.g. a refactor or speed-up, run check.py without --repro.)")
    if code1:
        problems.append("the repro still fails WITH your change: the fix does not work yet")
    return problems


def run_pytest(targets, cwd, env, limit, extra=""):
    """pytest -v into a file (so a timeout still yields the per-test results so far)."""
    t = _ws.cap(limit)
    log = os.path.join(_ws.swe_dir(), "pytest_%d.log" % os.getpid())
    cmd = "timeout -k 2 %d %s -v %s %s > %s 2>&1; echo $?" % (
        t, PYTEST, extra, " ".join(shlex.quote(x) for x in targets), shlex.quote(log))
    _, rc, _ = sh(["bash", "-c", cmd], cwd, timeout=t + 15, env=env)
    try:
        out = open(log, encoding="utf-8", errors="replace").read()
        os.remove(log)
    except OSError:
        out = ""
    rc = rc.strip().splitlines()[-1:] or ["1"]
    timed_out = rc[0] in ("124", "137")
    return out, timed_out, t


def pytest_summary(out, timed_out, t):
    summary = [l for l in out.splitlines() if re.search(r"\b\d+ (passed|failed|error)", l)]
    if summary and not timed_out:
        return summary[-1].strip("= ")
    passed = len(re.findall(r"^\S+::\S+.* PASSED\b", out, re.M))
    failed = len(failed_ids(out))
    if timed_out:
        return "TIMED OUT after %d s: %d passed, %d failed so far" % (t, passed, failed)
    last = out.strip().splitlines()[-1:]
    return last[0][:200] if last else "no output"


def main():
    ws = workspace()
    _, diff, _ = sh(["git", "diff", "HEAD"], ws)
    warn_if_repeated(sys.argv + [diff])
    args = sys.argv[1:]
    repro = None
    state = load_state()
    if "--repro" in args:
        i = args.index("--repro")
        repro = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
        if repro:
            state["repro"] = repro
            save_state(state)
    elif state.get("repro") and os.path.isfile(state["repro"]):
        repro = state["repro"]
        print("(using your repro from earlier: %s)" % repro)
    modified, new = changed_files(ws)
    empty_patch = not modified and not new
    problems = []
    print("PATCH CONTENTS")
    for f in modified:
        print("  M " + f)
    for f in new:
        print("  A " + f)
    if empty_patch:
        print("  (empty) - you have not changed anything yet")
        problems.append("the patch is EMPTY: an empty patch always fails. Make the change with edit.py first")

    for f in modified + new:
        base = os.path.basename(f)
        if is_test_path(f) or base in ("pytest.ini", "conftest.py", "setup.cfg", "tox.ini"):
            problems.append("revert %s (test/config files are reset or break grading): git checkout -- %s" % (f, f)
                            if f in modified else "delete %s: rm %s" % (f, f))
    for f in new:
        if not is_test_path(f) and (f.count("/") == 0 or re.search(r"(repro|debug|scratch|tmp|test_fix|reproduce)", f)):
            problems.append("stray new file %s - delete it unless it is real library source: rm %s" % (f, f))

    changed_src = [f for f in modified + new if f.endswith(".py") and not is_test_path(f)]
    for f in changed_src:
        try:
            with open(os.path.join(ws, f), encoding="utf-8", errors="replace") as fh:
                compile(fh.read(), f, "exec")  # in-process: py_compile would write .pyc files into the tree
        except SyntaxError as exc:
            problems.append("SYNTAX ERROR in %s line %s: %s" % (f, exc.lineno, exc.msg))
        except (OSError, ValueError):
            pass
    env = _ws.py_env(ws)
    for f in changed_src:
        mod = module_name(f)
        if mod.startswith(("docs_src", "scripts", "docs.")):
            continue
        t = _ws.cap(_ws.SCRIPT_TIMEOUT)
        code, out, err = sh(["timeout", "-k", "2", str(t), "python3", "-c", "import " + mod], ws, timeout=t + 5,
                            env=env)
        if code:
            last = (err or out).strip().splitlines()[-1:] or ["?"]
            problems.append("import %s fails: %s" % (mod, last[0][:200]))

    info = {}
    if repro is not None:
        print()
        problems += run_repro(ws, repro, empty_patch, changed_src, info)
    given = [t for t in args if t.strip()]
    tests = [t for t in given if is_test_path(t)]
    extra_src = [t for t in given if not is_test_path(t) and t.endswith(".py")]
    if not tests:
        tests = related_tests(ws, changed_src + [f for f in extra_src if f not in changed_src])
    # Also the tests that use the changed functions, even when a test file was given.
    tests = (tests + tests_mentioning(ws, changed_names(ws), tests))[:5]
    print("\nTESTS: " + (" ".join(tests) if tests else "no related test files found"))
    caused, unknown = [], []
    r = _ws.remaining()
    if tests and r is not None and r < 60:
        print("  LOW TIME (%d s left): tests skipped. If your repro passes with your change, call submit_patch now."
              % max(0, r))
        tests = []
    if tests:
        out, timed_out, t = run_pytest(tests, ws, env, 60)
        print("  " + pytest_summary(out, timed_out, t))
        ran = re.search(r"\b\d+ (passed|failed|error)", out) or re.search(r"::\S+.* (PASSED|FAILED|ERROR)", out)
        if "no tests ran" in out or not ran:
            if timed_out:
                problems.append("the tests timed out before any result: run check.py with the single most related "
                                "test file")
            else:
                problems.append("no tests ran from %s: pass the test file(s) for the code you changed" % " ".join(tests))
        fails = failed_ids(out)
        if fails and not empty_patch:
            before, not_reached, why = None, set(), ""
            r = _ws.remaining()
            if r is not None and r < 25:
                why = "LOW TIME"
            else:
                base, why = ensure_base(ws)
                if base:
                    targets = fails[:30] if len(fails) <= 30 else sorted(set(f.split("::")[0] for f in fails))
                    out0, to0, _ = run_pytest(targets, base, base_env(base), 40)
                    seen = set(m.group(1) for m in re.finditer(
                        r"^(\S+::\S+) (?:PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)", out0, re.M))
                    before = set(failed_ids(out0))
                    if to0:  # tests the run on the original code did not reach are unknown
                        not_reached = set(f for f in fails if f not in seen and f not in before)
                        why = "the run on the original code timed out before it"
                    if not seen and not before and not re.search(r"\b\d+ (passed|failed|error)", out0):
                        before, why = None, "the tests did not run on the original code"
            for n, fid in enumerate(fails):
                if before is None or fid in not_reached:
                    tag = "UNKNOWN whether your change caused it (%s)" % (why or "not compared")
                    unknown.append(fid)
                elif fid not in before:
                    tag = "CAUSED BY YOUR CHANGE"
                    caused.append(fid)
                else:
                    tag = "ALSO FAILS WITHOUT YOUR CHANGE (ignore)"
                if n < 10:
                    print("  %s  <- %s" % (fid[:150], tag))
            if len(fails) > 10:
                print("  ... %d failing tests in total, %d caused by your change" % (len(fails), len(caused)))
            r = _ws.remaining()
            if caused and (r is None or r > 40):
                t = _ws.cap(30)
                _, detail, _ = sh("timeout -k 2 %d " % t + PYTEST.replace("-q", "-q --tb=short") + " " +
                                  " ".join(shlex.quote(c) for c in caused[:3]) +
                                  " 2>&1 | grep -E '^(E |>|[^ ].*:[0-9]+: )' | head -24", ws, timeout=t + 10, env=env)
                if detail.strip():
                    print("  why they fail:\n    " + "\n    ".join(l[:170] for l in detail.splitlines()))
            if caused:
                print("  If a failing test's expected value is exactly the buggy behaviour the issue asks to change, "
                      "that test is outdated (the maintainers update it): keep your fix. Otherwise fix your code.")
            if unknown:
                print("  UNKNOWN failures: read them and decide whether your change could cause them.")
        elif fails:
            for fid in fails[:10]:
                print("  %s  <- fails on the original code (your patch is empty)" % fid[:150])
    problems += ["fix failing test %s (or confirm it encodes the old buggy behaviour)" % c for c in caused[:4]]
    if len(caused) > 4:
        problems.append("... and %d more tests your change broke" % (len(caused) - 4))
    siblings = sibling_sweep(ws)
    if siblings:
        print("\nSAME CODE ELSEWHERE (you changed this code in one place; these copies may have the same bug):")
        for n in siblings:
            print("  " + n)
        problems.append("check the SAME CODE ELSEWHERE list: apply the same fix there if it has the same bug")

    print()
    if repro is None and not problems:
        print("note: no --repro given; for a behaviour change, verify with check.py --repro /tmp/repro.py")
    if problems:
        print("VERDICT: FIX BEFORE SUBMITTING")
        for p in problems:
            print("  - " + p)
    else:
        print("VERDICT: OK - make sure every requirement of the issue is implemented, then call submit_patch")
    st = load_state()  # remembered for status.py and the state line
    st["last_verdict"] = ("FIX BEFORE SUBMITTING: " + " | ".join(p[:120] for p in problems[:4])) if problems else "OK"
    st["verdict_patch"] = _ws.patch_digest(ws)
    if repro and info.get("body"):
        st["rs"] = {"path": repro, "body": info["body"], "before": info.get("before", "?"),
                    "now": info.get("now", "?")}
    save_state(st)


if __name__ == "__main__":
    _ws.run_tool(main)
