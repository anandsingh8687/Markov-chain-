"""Replace a range of lines, reading the new lines from stdin (a quoted heredoc).

usage:
  python3 .swetools/edit.py FILE START END <<'EOF'
  new line 1
  new line 2
  EOF

Replaces lines START..END (inclusive, numbers from show.py) with the text
between the EOF markers, exactly as written: no escaping is needed inside a
quoted heredoc. END = START - 1 inserts before START without removing anything.
An empty heredoc deletes the lines. Prints the result with new line numbers and
checks the file still compiles.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import is_test_path, workspace  # noqa: E402


def unescape_if_flattened(text):
    """Over-escaped input arrives as one line with literal \\n sequences: decode it."""
    body = text.rstrip("\n")
    if "\n" not in body and "\\n" in body:
        return body.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"') + "\n", True
    return text, False


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return
    ws = workspace()
    rel = sys.argv[1]
    path = os.path.join(ws, rel)
    if is_test_path(rel) or os.path.basename(rel) in ("conftest.py", "pytest.ini"):
        sys.exit("error: do not edit test or pytest config files")
    try:
        start, end = int(sys.argv[2]), int(sys.argv[3])
    except ValueError:
        sys.exit("error: START and END must be line numbers")
    try:
        with open(path, encoding="utf-8") as fh:
            old = fh.read()
    except OSError as exc:
        sys.exit("error: %s" % exc)
    lines = old.split("\n")
    trailing = old.endswith("\n")
    if trailing:
        lines = lines[:-1]
    if not (1 <= start <= len(lines) + 1) or not (start - 1 <= end <= len(lines)):
        sys.exit("error: file has %d lines; need 1 <= START <= END <= %d (or END = START-1 to insert)"
                 % (len(lines), len(lines)))
    new_text = "" if sys.stdin.isatty() else sys.stdin.read()
    new_text, fixed = unescape_if_flattened(new_text)
    new_lines = new_text.split("\n")
    if new_lines and new_lines[-1] == "":
        new_lines = new_lines[:-1]
    removed = lines[start - 1:end]
    lines[start - 1:end] = new_lines
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + ("\n" if trailing else ""))
    if fixed:
        print("note: input had literal \\n sequences and no real newlines; decoded them")
    print("replaced %d line(s) %d-%d with %d line(s); later lines shift by %+d"
          % (len(removed), start, end, len(new_lines), len(new_lines) - len(removed)))
    lo, hi = max(1, start - 3), min(len(lines), start + len(new_lines) + 2)
    for i in range(lo - 1, hi):
        mark = ">" if start - 1 <= i < start - 1 + len(new_lines) else " "
        print("%s%5d| %s" % (mark, i + 1, lines[i]))
    if path.endswith(".py"):
        try:
            compile("\n".join(lines) + "\n", rel, "exec")
            print("syntax OK")
        except SyntaxError as exc:
            print("SYNTAX ERROR now at line %s: %s" % (exc.lineno, exc.msg))
            print("fix it with another edit.py call (show.py FILE %s to see the lines)" % exc.lineno)


if __name__ == "__main__":
    main()
