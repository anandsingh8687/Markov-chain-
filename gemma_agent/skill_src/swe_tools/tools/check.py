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
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import changed_files, is_test_path, sh, tracked_py, workspace  # noqa: E402

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


def failed_ids(out):
    return sorted(set(re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.M)))


def run_repro(ws, repro):
    """Run the repro with the change stashed (before) and applied (after)."""
    if not os.path.isfile(repro):
        return ["repro script %s not found: write it first (in /tmp)" % repro]
    cmd = "timeout 90 python3 -B %s 2>&1 | tail -6" % repro
    _, st, _ = sh("git stash push -q -u -- . && echo ok", ws, timeout=60)
    try:
        code0, out0, _ = sh(["bash", "-c", "set -o pipefail; " + cmd], ws, timeout=120)
    finally:
        if "ok" in st:
            sh("git stash pop -q", ws, timeout=60)
    code1, out1, _ = sh(["bash", "-c", "set -o pipefail; " + cmd], ws, timeout=120)
    print("REPRO %s" % repro)
    print("  without your change: %s" % ("FAILS (exit %d)" % code0 if code0 else "passes"))
    for line in out0.strip().splitlines()[-3:]:
        print("      " + line[:200])
    print("  with your change:    %s" % ("FAILS (exit %d)" % code1 if code1 else "passes"))
    for line in out1.strip().splitlines()[-4:]:
        print("      " + line[:200])
    problems = []
    if not code0:
        problems.append("the repro passes WITHOUT your change, so it does not reproduce the issue: make it use the "
                        "public API exactly as the issue describes and assert the expected result; if it truly "
                        "passes, the bug is elsewhere - try other input shapes and entry points")
    if code1:
        problems.append("the repro still fails WITH your change: the fix does not work yet")
    return problems


def main():
    ws = workspace()
    args = sys.argv[1:]
    repro = None
    if "--repro" in args:
        i = args.index("--repro")
        repro = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    modified, new = changed_files(ws)
    problems = []
    print("PATCH CONTENTS")
    for f in modified:
        print("  M " + f)
    for f in new:
        print("  A " + f)
    if not modified and not new:
        print("  (empty) - you have not changed anything yet")

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
        code, out, err = sh(["python3", "-m", "py_compile", f], ws, timeout=60)
        if code:
            problems.append("SYNTAX ERROR in %s: %s" % (f, (err or out).strip().splitlines()[-1][:200]))
    for f in changed_src:
        mod = module_name(f)
        if mod.startswith(("docs_src", "scripts", "docs.")):
            continue
        code, out, err = sh(["python3", "-c", "import " + mod], ws, timeout=60)
        if code:
            last = (err or out).strip().splitlines()[-1:] or ["?"]
            problems.append("import %s fails: %s" % (mod, last[0][:200]))

    if repro is not None:
        print()
        problems += run_repro(ws, repro)
    given = [t for t in args if t.strip()]
    tests = [t for t in given if is_test_path(t)]
    extra_src = [t for t in given if not is_test_path(t) and t.endswith(".py")]
    if not tests:
        tests = related_tests(ws, changed_src + [f for f in extra_src if f not in changed_src])
    print("\nTESTS: " + (" ".join(tests) if tests else "no related test files found"))
    caused = []
    if tests:
        code, out, err = sh(PYTEST + " " + " ".join(tests) + " 2>&1 | tail -40", ws, timeout=200)
        summary = [l for l in out.splitlines() if re.search(r"\b(passed|failed|error)", l)]
        print("  " + (summary[-1] if summary else out.strip().splitlines()[-1:] and out.strip().splitlines()[-1] or "no output"))
        if "no tests ran" in out or not summary:
            problems.append("no tests ran from %s: pass the test file(s) for the code you changed" % " ".join(tests))
        fails = failed_ids(out)
        if fails:
            _, st, _ = sh("git stash push -q --keep-index -- . && echo ok", ws, timeout=60)
            try:
                code0, out0, _ = sh(PYTEST + " " + " ".join(sorted(set(f.split('::')[0] for f in fails))) +
                                    " 2>&1 | tail -40", ws, timeout=200)
            finally:
                if "ok" in st:
                    sh("git stash pop -q", ws, timeout=60)
            before = set(failed_ids(out0))
            for fid in fails:
                tag = "ALSO FAILS WITHOUT YOUR CHANGE (ignore)" if fid in before else "CAUSED BY YOUR CHANGE"
                print("  %s  <- %s" % (fid, tag))
                if fid not in before:
                    caused.append(fid)
            detail = [l for l in out.splitlines() if l.startswith("E ")][:8]
            if caused and detail:
                print("  first errors:\n    " + "\n    ".join(d[:160] for d in detail))
    problems += ["fix failing test %s" % c for c in caused]

    print()
    if repro is None and not problems:
        problems.append("NOT VERIFIED: write /tmp/repro.py that uses the public API the way the issue describes and "
                        "asserts the expected result, then run check.py --repro /tmp/repro.py")
    if problems:
        print("VERDICT: FIX BEFORE SUBMITTING")
        for p in problems:
            print("  - " + p)
    else:
        print("VERDICT: OK - repro fails before and passes after, tests pass; make sure every requirement of the issue is implemented, then submit_patch()")


if __name__ == "__main__":
    main()
