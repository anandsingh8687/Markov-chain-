"""Where your work stands: use it whenever you are unsure what you already did.

usage: python3 .swetools/status.py

Prints the files you viewed, your current patch, your remembered repro and whether it passes now, and
the last check.py verdict. Earlier conversation may have been summarized to save memory; this reads the
real state from the repository instead.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import load_state, sh, track_context, workspace  # noqa: E402


def main():
    ws = workspace()
    state = load_state()
    viewed = state.get("viewed_files") or []
    print("FILES YOU VIEWED: " + (", ".join(viewed[-8:]) if viewed else "none recorded"))
    _, stat, _ = sh(["git", "diff", "HEAD", "--stat"], ws)
    _, diff, _ = sh(["git", "diff", "HEAD", "-U1"], ws)
    if diff.strip():
        print("YOUR PATCH:")
        print(stat.rstrip())
        lines = diff.splitlines()
        print("\n".join(lines[:60]))
        if len(lines) > 60:
            print("... (%d more diff lines)" % (len(lines) - 60))
    else:
        print("YOUR PATCH: empty (no file changed yet)")
    repro = state.get("repro")
    if repro and os.path.isfile(repro):
        code, out, _ = sh(["bash", "-c", "timeout 60 python3 -B %s 2>&1 | tail -4; exit ${PIPESTATUS[0]}" % repro],
                          ws, timeout=90)
        print("YOUR REPRO %s now: %s" % (repro, "passes" if code == 0 else "FAILS (exit %d)" % code))
        print("  " + "\n  ".join(out.strip().splitlines()[-4:]))
    else:
        print("YOUR REPRO: none yet (write /tmp/repro.py with run.py)")
    print("LAST CHECK: " + (state.get("last_verdict") or "check.py not run yet"))
    if not diff.strip():
        nxt = "make the change with edit.py"
    elif state.get("last_verdict", "").startswith("OK"):
        nxt = "compare the patch with the issue once more, then call submit_patch"
    else:
        nxt = "run check.py --repro /tmp/repro.py and fix what its VERDICT lists"
    print("NEXT: " + nxt)


if __name__ == "__main__":
    track_context(len(" ".join(sys.argv)))
    main()
