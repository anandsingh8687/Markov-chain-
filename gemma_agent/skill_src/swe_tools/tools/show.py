"""Show numbered lines of a file.

usage: python3 .swetools/show.py FILE START [END]     (at most 40 lines)
       python3 .swetools/show.py FILE /regex/          (every matching line, numbered)
The numbers are what edit.py expects.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import digest, load_state, save_state, workspace  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    path = os.path.join(workspace(), sys.argv[1])
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
    except OSError as exc:
        sys.exit("error: %s" % exc)
    state = load_state()
    rel = sys.argv[1]
    key = digest(*(sys.argv[1:] + ["\n".join(lines)]))
    seen = state.setdefault("shown", [])
    moved = state.get("moved", {})
    if rel in moved:
        del moved[rel]
    repeated = key in seen
    if not repeated:
        seen.append(key)
    save_state(state)
    if repeated:
        # Printing nothing made the model repeat the same view ~20 times; show it again and push forward.
        print("REPEAT VIEW: these lines are unchanged since you last viewed them. Next step: edit them with "
              "edit.py, run your public-API repro, or look at a different range. Do not view them again.")
    arg = sys.argv[2]
    if arg.startswith("/") and arg.endswith("/") and len(arg) > 1:
        pat = re.compile(arg[1:-1])
        hits = [i for i, l in enumerate(lines) if pat.search(l)][:25]
        for i in hits:
            print("%5d| %s" % (i + 1, lines[i]))
        if not hits:
            print("no match")
        return
    start = max(1, int(arg))
    end = int(sys.argv[3]) if len(sys.argv) > 3 else start + 39
    end = min(end, start + 39, len(lines))
    for i in range(start - 1, end):
        print("%5d| %s" % (i + 1, lines[i][:200]))
    if end < len(lines):
        print("  ... (%d lines in file)" % len(lines))


if __name__ == "__main__":
    main()
