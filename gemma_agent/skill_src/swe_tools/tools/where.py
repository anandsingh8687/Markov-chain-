"""List every place a name is defined, set or passed, and where it is read.

usage: python3 .swetools/where.py NAME

Use it to thread an option through every layer (constructor, router, route,
handler) or to find each copy of the code that uses a value.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import is_test_path, sh, warn_if_repeated, workspace, track_context  # noqa: E402


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", sys.argv[1]):
        print(__doc__)
        return
    warn_if_repeated(sys.argv)
    name = sys.argv[1]
    ws = workspace()
    _, out, _ = sh(["git", "grep", "-n", "-w", "-e", name, "--", "*.py"], ws)
    groups = {"DEFINED": [], "SET OR PASSED": [], "READ": []}
    tests = set()
    for hit in out.splitlines():
        parts = hit.split(":", 2)
        if len(parts) < 3:
            continue
        path, lineno, text = parts
        if is_test_path(path):
            tests.add(path)
            continue
        if path.startswith(("docs_src/", "docs/", "scripts/")):
            continue
        code = text.strip()
        if re.match(r"(async\s+)?(def|class)\s+%s\b" % name, code):
            kind = "DEFINED"
        elif (re.search(r"(^|[.\s])%s\s*(:[^=]*)?=[^=]" % name, code) or re.search(r"\b%s\s*=" % name, code)
              or re.match(r"(async\s+)?def\s", code)):
            kind = "SET OR PASSED"
        else:
            kind = "READ"
        groups[kind].append("%s:%s  %s" % (path, lineno, code[:130]))
    if not any(groups.values()):
        print("no source line uses %s as a whole word (try locate.py for similar names)" % name)
    for kind, rows in groups.items():
        if rows:
            print("%s (%d)" % (kind, len(rows)))
            for r in rows[:15]:
                print("  " + r)
            if len(rows) > 15:
                print("  ... %d more" % (len(rows) - 15))
    if tests:
        print("TESTS USING IT: " + ", ".join(sorted(tests)[:6]))


if __name__ == "__main__":
    track_context(len(" ".join(sys.argv)))
    main()
