"""Run a Python script from /tmp against the repository.

usage: python3 .swetools/run.py /tmp/script.py

Runs the script (timeout 90 s) and prints the last 30 lines of its output with
the exit code. If neither the script nor the repository changed since an
earlier run, it does not run again: it repeats the earlier result, because the
answer cannot be different. Change the script or the code first.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import digest, load_state, save_state, sh, workspace  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    ws = workspace()
    script = sys.argv[1]
    try:
        with open(script, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError as exc:
        sys.exit("error: %s (write the script first, e.g. cat > /tmp/x.py <<'EOF' ... EOF)" % exc)
    _, diff, _ = sh(["git", "diff", "HEAD"], ws)
    key = digest(body, diff)
    state = load_state()
    runs = state.setdefault("runs", {})
    if key in runs:
        prev = runs[key]
        print("SAME SCRIPT, SAME CODE as run #%d, so the result is the same (not run again):" % prev["n"])
        print(prev["out"])
        print("Change the script or the code before running it again.")
        return
    code, out, err = sh(["bash", "-c", "timeout 90 python3 -B %s 2>&1 | tail -30; exit ${PIPESTATUS[0]}" % script],
                        ws, timeout=120)
    text = (out or err or "").rstrip() or "(no output)"
    text += "\n[exit code %d]" % code
    print(text)
    runs[key] = {"n": len(runs) + 1, "out": text[-1500:]}
    save_state(state)


if __name__ == "__main__":
    main()
