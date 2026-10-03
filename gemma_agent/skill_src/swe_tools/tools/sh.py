"""Run a plain shell command in YOUR repository copy (duo mode, attempt B).

usage: python3 /tmp/b/t/sh.py <<'EOF'
       grep -n "def foo" src/pkg/mod.py
       EOF
   or: python3 /tmp/b/t/sh.py 'git diff'

The command runs with your copy as the current directory and your copy's code first on the import path
(so python3, pytest, git diff and grep all see YOUR copy). Paths under /workspace are mapped to your copy.
Timeout 30 s; the last 60 lines of output are shown.
"""

import os
import re
import select
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
from _ws import sh, workspace  # noqa: E402


def _stdin_text():
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        return sys.stdin.read() if ready else ""
    except (OSError, ValueError):
        return ""


def main():
    ws = workspace()
    text = " ".join(sys.argv[1:]).strip() or _stdin_text().strip()
    if not text:
        print(__doc__)
        return
    bad = [l for l in text.split("\n") if re.match(r"\s*EOF\S", l)]
    if bad:
        sys.exit("REFUSED: the heredoc end marker is malformed (%r). The command must end with a line that is "
                 "exactly EOF." % bad[0].strip())
    cmd = _ws.rewrite_ws_paths(text, ws)
    if re.search(r"\bsubmit_patch\b", cmd):
        sys.exit("submit_patch is a tool, not a shell command (and only after a tool prints FINAL).")
    t = _ws.cap(30)
    code, out, err = sh(["bash", "-c", "set -o pipefail 2>/dev/null; ( %s ) 2>&1 | tail -60; exit ${PIPESTATUS[0]}"
                         % cmd], ws, timeout=t + 10, env=_ws.py_env(ws))
    text = (out or err or "").rstrip() or "(no output)"
    if len(text) > 3500:
        text = "...\n" + text[-3500:]
    print(text)
    print("[exit code %d%s]" % (code, "; 1 from grep means no match" if code == 1 and "grep" in cmd else ""))
    if code in (124, 137):
        print("TIMED OUT after %d s" % t)


if __name__ == "__main__":
    _ws.run_tool(main)
