"""Run a Python script from /tmp against the repository.

usage: python3 .swetools/run.py /tmp/script.py
       python3 .swetools/run.py /tmp/script.py <<'EOF'
       ...script lines...
       EOF
With a heredoc, run.py first writes the script to that path, then runs it.

Runs the script (timeout 90 s) and prints the last 30 lines of its output with
the exit code. If neither the script nor the repository changed since an
earlier run, it does not run again: it repeats the earlier result, because the
answer cannot be different. Change the script or the code first.
"""

import os
import re
import select
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
from _ws import digest, load_state, save_state, sh, workspace, track_context  # noqa: E402


def _stdin_text():
    """The heredoc text, or "" when nothing was piped in (never blocks on an open terminal or pipe)."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        return sys.stdin.read() if ready else ""
    except (OSError, ValueError):
        return ""


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    ws = workspace()
    script = sys.argv[1]
    given = _stdin_text()
    _ws.add_context(len(given))
    if given.strip():
        bad = [l for l in given.split("\n") if re.match(r"\s*EOF\S", l) or l.strip() == "EOF"]
        if bad:
            sys.exit("REFUSED: the heredoc end marker is malformed (%r). The command must end with a line that is "
                     "exactly EOF." % bad[0].strip())
        if not script.startswith("/tmp/"):
            sys.exit("error: write scripts only under /tmp (for example /tmp/repro.py)")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(given if given.endswith("\n") else given + "\n")
        print("wrote %s (%d lines)" % (script, len(given.rstrip("\n").split("\n"))))
    try:
        with open(script, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError as exc:
        sys.exit("error: %s (write the script first, e.g. cat > /tmp/x.py <<'EOF' ... EOF)" % exc)
    _, diff, _ = sh(["git", "diff", "HEAD"], ws)
    key = digest(body, diff)
    state = load_state()
    if "repro" in os.path.basename(script):
        state["repro"] = script  # edit.py and check.py rerun it after each change
    runs = state.setdefault("runs", {})
    if key in runs:
        prev = runs[key]
        print("SAME SCRIPT, SAME CODE as run #%d, so the result is the same (not run again):" % prev["n"])
        print(prev["out"])
        print("Change the script or the code before running it again.")
        save_state(state)
        return
    code, out, err = sh(["bash", "-c", "timeout 90 python3 -B %s 2>&1 | tail -30; exit ${PIPESTATUS[0]}" % script],
                        ws, timeout=120)
    text = (out or err or "").rstrip() or "(no output)"
    text += "\n[exit code %d]" % code
    print(text)
    runs[key] = {"n": len(runs) + 1, "out": text[-1500:]}
    save_state(state)


if __name__ == "__main__":
    track_context(len(" ".join(sys.argv)))
    main()
