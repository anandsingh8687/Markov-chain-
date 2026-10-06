"""Run a Python script from /tmp against the repository.

usage: python3 .swetools/run.py /tmp/script.py [--timeout N]
       python3 .swetools/run.py /tmp/script.py <<'EOF'
       ...script lines...
       EOF
With a heredoc, run.py first writes the script to that path, then runs it.

Runs the script with the repository's own code first on the import path (src/ layout
included), timeout 15 s (--timeout N, at most 60), and prints the last 30 lines of its
output with the exit code. If neither the script nor the repository changed since an
earlier run, it does not run again: it repeats the earlier result, because the answer
cannot be different. Change the script or the code first.
"""

import os
import re
import select
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
from _ws import digest, load_state, save_state, sh, workspace  # noqa: E402


def _stdin_text():
    """The heredoc text, or "" when nothing was piped in (never blocks on an open terminal or pipe)."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        return sys.stdin.read() if ready else ""
    except (OSError, ValueError):
        return ""


def _is_tmp(path):
    real = os.path.realpath(path)
    return path.startswith("/tmp/") or any(
        real.startswith(os.path.realpath(d) + os.sep) for d in {tempfile.gettempdir(), "/tmp"})


def _outside_imports(ws, body, env):
    """Repository packages the script imports that resolve outside the repository (a stale installed copy)."""
    pkgs = _ws.top_packages(ws)
    used = [p for p in pkgs if re.search(r"^\s*(?:from|import)\s+%s\b" % re.escape(p), body, re.M)]
    if not used:
        return []
    state = load_state()
    ok = set(state.get("import_inside", []))
    todo = [p for p in used if p not in ok]
    if not todo:
        return []
    code, out, _ = sh(["python3", "-c", "import importlib.util as u\nfor p in %r:\n"
                       "    s = u.find_spec(p)\n    print(p, s.origin if s else None)" % todo],
                      tempfile.gettempdir(), timeout=_ws.cap(10), env=env)
    bad = []
    real_ws = os.path.realpath(ws)
    for line in out.splitlines():
        name, _, origin = line.partition(" ")
        if origin and origin != "None" and not os.path.realpath(origin).startswith(real_ws + os.sep):
            bad.append((name, origin))
        elif origin and origin != "None":
            ok.add(name)
    state = load_state()
    state["import_inside"] = sorted(ok)
    save_state(state)
    return bad


def main():
    args = list(sys.argv[1:])
    limit = _ws.SCRIPT_TIMEOUT
    if "--timeout" in args:
        i = args.index("--timeout")
        val = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
        if val.isdigit():
            limit = max(1, min(60, int(val)))
    if not args:
        print(__doc__)
        return
    ws = workspace()
    script = _ws.scratch_path(args[0])
    if script != args[0]:
        print("note: your scripts live in %s; using %s" % (_ws.cfg().get("display_scratch", "/tmp/b"), script))
    given = _stdin_text()
    if given.strip():
        bad = [l for l in given.split("\n") if re.match(r"\s*EOF\S", l) or l.strip() == "EOF"]
        if bad:
            sys.exit("REFUSED: the heredoc end marker is malformed (%r). The command must end with a line that is "
                     "exactly EOF." % bad[0].strip())
        if not _is_tmp(script):
            sys.exit("error: write scripts only under /tmp (for example /tmp/repro.py)")
        os.makedirs(os.path.dirname(script) or ".", exist_ok=True)
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(given if given.endswith("\n") else given + "\n")
        print("wrote %s (%d lines)" % (script, len(given.rstrip("\n").split("\n"))))
    try:
        with open(script, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError as exc:
        sys.exit("error: %s (write the script first: run.py /tmp/repro.py <<'EOF' ... EOF)" % exc)
    _, diff, _ = sh(["git", "diff", "HEAD"], ws)
    modified, new = _ws.changed_files(ws)
    patch_empty = not modified and not new
    key = digest(body, diff, "\n".join(new), str(limit))
    state = load_state()
    repro = _ws.is_repro(script)
    if repro:
        state["repro"] = script  # edit.py and check.py rerun it after each change
        _ws.count_rewrite(state, digest(body), patch_empty)
    runs = state.setdefault("runs", {})
    if key in runs:
        prev = runs[key]
        print("SAME SCRIPT, SAME CODE as run #%d, so the result is the same (not run again):" % prev["n"])
        print(prev["out"])
        print("Change the script or the code before running it again.")
        save_state(state)
        return
    save_state(state)
    t = _ws.cap(limit)
    env = _ws.py_env(ws)
    code, out, err = sh(["bash", "-c", "timeout -k 2 %d python3 -B %s 2>&1 | tail -30; exit ${PIPESTATUS[0]}"
                         % (t, _quote(_ws.bound_script(script)))], ws, timeout=t + 10, env=env)
    text = (out or err or "").rstrip() or "(no output)"
    if len(text) > 2500:
        text = "...\n" + text[-2500:]
    text += "\n[exit code %d]" % code
    if code in (124, 137):
        text += "\n" + _ws.timeout_hint(t)
    print(text)
    bad = _outside_imports(ws, body, env)
    for name, origin in bad:
        print("WARNING: `import %s` loaded %s, which is NOT the repository copy, so your edits are invisible to "
              "this script. Remove sys.path/os.chdir tricks from the script." % (name, origin))
    state = load_state()
    runs = state.setdefault("runs", {})
    runs[key] = {"n": len(runs) + 1, "out": text[-1500:]}
    if len(runs) > 200:
        for k in list(runs)[:-200]:
            del runs[k]
    if repro:
        _ws.record_repro(state, script, digest(body), _ws.result_word(code), patch_empty)
        if patch_empty and state.get("rewrites", 0) >= 3:
            print("STOP rewriting the repro (%d rewrites, patch still empty): edit the most likely location now "
                  "with edit.py; edit.py reruns this repro after the edit." % state["rewrites"])
    save_state(state)


def _quote(s):
    import shlex
    return shlex.quote(s)


if __name__ == "__main__":
    _ws.run_tool(main)
