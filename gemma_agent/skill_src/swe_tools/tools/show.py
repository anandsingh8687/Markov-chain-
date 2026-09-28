"""Show numbered lines of a file.

usage: python3 .swetools/show.py FILE START [END]     (at most 80 lines)
       python3 .swetools/show.py FILE /regex/          (every matching line, numbered)
The numbers are what edit.py expects.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import workspace  # noqa: E402


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
    arg = sys.argv[2]
    if arg.startswith("/") and arg.endswith("/") and len(arg) > 1:
        pat = re.compile(arg[1:-1])
        hits = [i for i, l in enumerate(lines) if pat.search(l)][:40]
        for i in hits:
            print("%5d| %s" % (i + 1, lines[i]))
        if not hits:
            print("no match")
        return
    start = max(1, int(arg))
    end = int(sys.argv[3]) if len(sys.argv) > 3 else start + 39
    end = min(end, start + 79, len(lines))
    for i in range(start - 1, end):
        print("%5d| %s" % (i + 1, lines[i]))
    if end < len(lines):
        print("  ... (%d lines in file)" % len(lines))


if __name__ == "__main__":
    main()
