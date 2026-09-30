"""Where your work stands: use it whenever you are unsure what you already did.

usage: python3 .swetools/status.py

Prints the time used, the files you viewed, your current patch, your remembered repro and whether it
passes now, the last check.py verdict and the NEXT step. Earlier conversation may have been summarized
to save memory; this reads the real state from the repository instead.
"""

import os
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
from _ws import load_state, save_state, sh, workspace  # noqa: E402


def main():
    ws = workspace()
    state = load_state()
    e, r = _ws.elapsed(), _ws.remaining()
    if e is not None:
        print("TIME: %d s used of %d, %d s left" % (e, _ws.BUDGET_S, max(0, r)))
    viewed = state.get("viewed_files") or []
    print("FILES YOU VIEWED: " + (", ".join(viewed[-8:]) if viewed else "none recorded"))
    _, stat, _ = sh(["git", "diff", "HEAD", "--stat"], ws)
    _, diff, _ = sh(["git", "diff", "HEAD", "-U1"], ws)
    modified, new = _ws.changed_files(ws)
    empty = not modified and not new
    if diff.strip() or new:
        print("YOUR PATCH:")
        print(stat.rstrip())
        for f in new:
            print(" %s (new file)" % f)
        lines = diff.splitlines()
        print("\n".join(lines[:60]))
        if len(lines) > 60:
            print("... (%d more diff lines)" % (len(lines) - 60))
    else:
        print("YOUR PATCH: empty (no file changed yet)")
    repro = state.get("repro")
    code = None
    if repro and os.path.isfile(repro):
        t = _ws.cap(_ws.SCRIPT_TIMEOUT)
        code, out, _ = sh(["bash", "-c", "timeout -k 2 %d python3 -B %s 2>&1 | tail -4; exit ${PIPESTATUS[0]}"
                           % (t, shlex.quote(repro))], ws, timeout=t + 10, env=_ws.py_env(ws))
        print("YOUR REPRO %s now: %s" % (repro, "passes" if code == 0 else "FAILS (exit %d)" % code))
        print("  " + "\n  ".join(out.strip().splitlines()[-4:]))
        if code in (124, 137):
            print("  (timed out after %d s: a hang)" % t)
        try:
            with open(repro, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            st = load_state()
            _ws.record_repro(st, repro, _ws.digest(body), _ws.result_word(code), empty)
            save_state(st)
        except OSError:
            pass
    else:
        print("YOUR REPRO: none yet (write /tmp/repro.py with run.py)")
    verdict = state.get("last_verdict") or ""
    stale = verdict and state.get("verdict_patch") and state.get("verdict_patch") != _ws.patch_digest(ws)
    print("LAST CHECK: " + (verdict or "check.py not run yet") + (" (the patch changed since)" if stale else ""))
    if empty:
        if e is not None and e >= 180:
            nxt = "EDIT NOW: make the most likely edit with edit.py (the end-of-run diff keeps it)"
        elif not repro:
            nxt = "write a failing repro with run.py, or make the change with edit.py"
        else:
            nxt = "make the change with edit.py"
    elif r is not None and r < 60:
        nxt = "LOW TIME: call submit_patch now"
    elif code not in (None, 0):
        nxt = "your repro still fails: fix the code (or the repro, if it asserts something the issue does not ask)"
    elif verdict.startswith("OK") and not stale:
        nxt = "compare the patch with the issue once more, then call submit_patch"
    else:
        nxt = "run check.py --repro %s and fix what its VERDICT lists" % (repro or "/tmp/repro.py")
    print("NEXT: " + nxt)


if __name__ == "__main__":
    _ws.run_tool(main)
