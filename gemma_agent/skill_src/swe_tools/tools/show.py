"""Show numbered lines of a file.

usage: python3 .swetools/show.py FILE START [END]     (at most 40 lines; 30 in duo mode)
       python3 .swetools/show.py FILE /regex/          (every matching line, numbered)
The numbers are what edit.py expects.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
from _ws import digest, load_state, save_state, sh, workspace  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    if sys.argv[2].startswith("/") and len(sys.argv) > 3 and not (len(sys.argv[2]) > 1 and sys.argv[2].endswith("/")):
        # The shell split a /regex with spaces/ into several arguments: join them again.
        for j in range(3, len(sys.argv)):
            if sys.argv[j].endswith("/"):
                sys.argv[2:j + 1] = [" ".join(sys.argv[2:j + 1])]
                break
    m = re.fullmatch(r"(\d+)\s*[-:,]\s*(\d+)", sys.argv[2]) if len(sys.argv) == 3 else None
    if m:  # accept FILE 10-50, 10:50 and 10,50 as well as FILE 10 50
        sys.argv[2:] = [m.group(1), m.group(2)]
    arg = sys.argv[2]
    if not (arg.isdigit() or (arg.startswith("/") and arg.endswith("/") and len(arg) > 1)) or (
            len(sys.argv) > 3 and not sys.argv[3].isdigit()):
        sys.exit("error: use show.py FILE START END (numbers) or show.py FILE /regex/")
    sys.argv[1] = _ws.rel_arg(sys.argv[1])
    path = os.path.join(workspace(), sys.argv[1])
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except OSError as exc:
        sys.exit("error: %s" % exc)
    state = load_state()
    rel = sys.argv[1]
    key = digest(*(sys.argv[1:] + ["\n".join(lines)]))
    seen = state.get("shown")
    if not isinstance(seen, dict):
        seen = state["shown"] = {}
    moved = state.get("moved", {})
    if rel in moved:
        del moved[rel]
    viewed = state.setdefault("viewed_files", [])
    if rel not in viewed:
        viewed.append(rel)
    count = seen.get(key, 0)
    seen[key] = count + 1
    save_state(state)
    if count >= 2:
        # Reprinting the same lines (v16) or printing nothing (v13) both let the model loop 20+ times.
        # Refuse, and show where the work stands instead.
        ws = workspace()
        print("REFUSED: you have viewed these exact unchanged lines %d times already. Viewing them again cannot "
              "tell you anything new. Here is where your work stands:" % count)
        _, stat, _ = sh(["git", "diff", "HEAD", "--stat"], ws)
        _, diff, _ = sh(["git", "diff", "HEAD", "-U1"], ws)
        if diff.strip():
            print(stat.rstrip())
            print("\n".join(diff.splitlines()[:40]))
        else:
            print("  your patch is EMPTY: you have not changed any file yet.")
        repro = state.get("repro")
        if repro and os.path.isfile(repro):
            t = _ws.cap(_ws.SCRIPT_TIMEOUT)
            code, out, _ = sh(["bash", "-c", "timeout -k 2 %d python3 -B '%s' 2>&1 | tail -4; exit ${PIPESTATUS[0]}"
                               % (t, _ws.bound_script(repro))], ws, timeout=t + 10, env=_ws.py_env(ws))
            print("your repro %s now: %s" % (repro, "passes" if code == 0 else "FAILS (exit %d)" % code))
            print("  " + "\n  ".join(out.strip().splitlines()[-4:]))
        print("Next step: %s" % ("make the change with edit.py now, using the line numbers you already have."
                                 if not diff.strip() else
                                 "run check.py --repro /tmp/repro.py, fix what its VERDICT lists, then submit_patch."))
        return
    if count == 1:
        print("REPEAT VIEW: these lines are unchanged since you last viewed them. Next step: edit them with "
              "edit.py, run your public-API repro, or look at a different range. A third view is refused.")
    arg = sys.argv[2]
    if arg.startswith("/") and arg.endswith("/") and len(arg) > 1:
        try:
            pat = re.compile(arg[1:-1])
        except re.error as exc:
            pat = re.compile(re.escape(arg[1:-1]))
            print("note: %s is not a valid regex (%s); searched for the literal text" % (arg, exc))
        hits = [i for i, l in enumerate(lines) if pat.search(l)][:25]
        for i in hits:
            print("%5d| %s" % (i + 1, lines[i]))
        if not hits:
            print("no match")
        return
    start = max(1, int(arg))
    n = _ws.VIEW_LINES
    end = int(sys.argv[3]) if len(sys.argv) > 3 else start + n - 1
    end = min(end, start + n - 1, len(lines))
    for i in range(start - 1, end):
        print("%5d| %s" % (i + 1, lines[i][:200]))
    if end < len(lines):
        print("  ... (%d lines in file; at most %d per view; next: show.py %s %d %d)"
              % (len(lines), n, rel, end + 1, min(end + n, len(lines))))


if __name__ == "__main__":
    _ws.run_tool(main)
