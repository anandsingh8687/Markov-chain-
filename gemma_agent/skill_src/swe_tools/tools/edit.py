"""Replace a range of lines, reading the new lines from stdin (a quoted heredoc).

usage:
  python3 .swetools/edit.py FILE START END <<'EOF'
  new line 1
  new line 2
  EOF

Replaces lines START..END (inclusive, numbers from show.py) with the text
between the EOF markers, exactly as written: no escaping is needed inside a
quoted heredoc. END = START - 1 inserts before START without removing anything.
An empty heredoc deletes the lines.

Safety: the edit is refused (file unchanged) when it would leave a Python
syntax error, or when the line numbers are stale because an earlier edit moved
the lines below it (view them again with show.py first).
"""

import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
from _ws import is_test_path, load_state, save_state, sh, warn_if_repeated, workspace  # noqa: E402


def _compile_error(text, rel):
    try:
        compile(text, rel, "exec")
        return None
    except SyntaxError as exc:
        return exc


def _unescape(text):
    return text.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def _shift(block, delta):
    out = []
    for line in block:
        if not line.strip():
            out.append(line)
        elif delta >= 0:
            out.append(" " * delta + line)
        else:
            cut = min(-delta, len(line) - len(line.lstrip(" ")))
            out.append(line[cut:])
    return out


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _module(rel):
    p = rel[:-3]
    for prefix in ("src/",):
        if p.startswith(prefix):
            p = p[len(prefix):]
    p = p.replace("/", ".")
    return p[:-9] if p.endswith(".__init__") else p


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return
    ws = workspace()
    rel = _ws.rel_arg(sys.argv[1])
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

    state = load_state()
    moved = state.get("moved", {}).get(rel)
    if moved and start > moved[0]:
        sys.exit("REFUSED, file unchanged: your earlier edit moved every line below line %d by %+d, so "
                 "lines %d-%d are not the lines you think. Run show.py %s on that area first, then edit with "
                 "the new numbers." % (moved[0], moved[1], start, end, rel))

    new_text = "" if sys.stdin.isatty() else sys.stdin.read()
    bad = [l for l in new_text.split("\n") if re.match(r"\s*EOF\S", l) or l.strip() == "EOF"]
    if bad:
        sys.exit("REFUSED, file unchanged: the heredoc end marker is malformed (%r). The command must end with a "
                 "line that is exactly EOF, with nothing after it." % bad[0].strip())
    repeated = warn_if_repeated(sys.argv + [new_text, old])
    _ws.add_context(len(new_text))

    def build(text):
        nl = text.split("\n")
        if nl and nl[-1] == "":
            nl = nl[:-1]
        return nl

    new_lines = build(new_text)
    removed = lines[start - 1:end]
    notes = []
    if rel.endswith(".py"):
        def result(nl):
            return "\n".join(lines[:start - 1] + nl + lines[end:]) + "\n"
        err = _compile_error(result(new_lines), rel)
        if err is not None and "\\n" in new_text:
            alt = build(_unescape(new_text))
            if _compile_error(result(alt), rel) is None:
                new_lines, err = alt, None
                notes.append("note: your text had literal \\n sequences; decoded them so the file compiles")
        if err is not None and new_lines:
            anchor = next((l for l in removed if l.strip()), None) or next(
                (l for l in reversed(lines[:start - 1]) if l.strip()), "")
            first = next((l for l in new_lines if l.strip()), "")
            delta = _indent(anchor) - _indent(first)
            if 0 < abs(delta) <= 3:
                alt = _shift(new_lines, delta)
                if _compile_error(result(alt), rel) is None:
                    new_lines, err = alt, None
                    notes.append("note: shifted your lines by %+d spaces to match the code they replace" % delta)
        if err is not None and new_lines:
            # The most common cause: the range also covers a line the new text forgot (a closing
            # bracket, a signature end, the next statement). Find the range that compiles with the same text.
            fits = []
            for s2, e2 in [(start, e) for e in range(end - 1, start - 2, -1)] + [(s, end) for s in range(start + 1, end + 2)]:
                if (s2, e2) == (start, end) or e2 < s2 - 1:
                    continue
                cand = "\n".join(lines[:s2 - 1] + new_lines + lines[e2:]) + "\n"
                if _compile_error(cand, rel) is None:
                    fits.append((s2, e2))
            if fits:
                s2, e2 = fits[0]
                kept = [l.strip() for l in lines[start - 1:end] if l not in lines[s2 - 1:e2]]
                if repeated and len(fits) <= 2:
                    notes.append("note: you sent this refused edit again, so it was applied to lines %d-%d instead of "
                                 "%d-%d, keeping the line(s) your text left out: %s"
                                 % (s2, e2, start, end, " | ".join(k[:60] for k in kept[:3])))
                    removed = lines[s2 - 1:e2]
                    start, end, err = s2, e2, None
                else:
                    print("REFUSED, file unchanged: your text would replace lines %d-%d, but it leaves out line(s) "
                          "the file still needs: %s" % (start, end, " | ".join(k[:80] for k in kept[:3])))
                    print("The same text compiles as: python3 .swetools/edit.py %s %d %d  (END = START-1 means insert)"
                          % (rel, s2, e2))
                    print("Run that command with your heredoc, or include those lines in your text.")
                    sys.exit(1)
        if err is not None:
            print("REFUSED, file unchanged: the edit would leave a syntax error at line %s: %s"
                  % (err.lineno, err.msg))
            lo = max(1, start - 2)
            print("current lines %d-%d:" % (lo, min(len(lines), end + 2)))
            for i in range(lo - 1, min(len(lines), end + 2)):
                print("%5d| %s" % (i + 1, lines[i][:160]))
            print("rewrite the whole block with correct indentation and balanced brackets, then run edit.py again")
            sys.exit(1)

    lines[start - 1:end] = new_lines
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + ("\n" if trailing else ""))
    delta = len(new_lines) - len(removed)
    moved_map = state.setdefault("moved", {})
    if delta:
        # Lines after the new block moved; the block itself was just printed with its new numbers.
        prev = moved_map.get(rel)
        edge = start + max(len(new_lines), 1) - 1
        moved_map[rel] = [min(edge, prev[0]) if prev else edge, delta + (prev[1] if prev else 0)]
    save_state(state)

    for n in notes:
        print(n)
    print("replaced %d line(s) %d-%d with %d line(s)%s" % (
        len(removed), start, end, len(new_lines),
        "; lines below moved by %+d (view them again before editing there)" % delta if delta else ""))
    if removed:
        print("removed:")
        for l in removed[:6]:
            print("   - " + l[:160])
        if len(removed) > 6:
            print("   - ... (%d more)" % (len(removed) - 6))
    lo, hi = max(1, start - 1), min(len(lines), start + len(new_lines))
    shown = list(range(lo - 1, hi))
    if len(shown) > 14:
        shown = shown[:6] + [None] + shown[-6:]
    for i in shown:
        if i is None:
            print("   ...")
            continue
        mark = ">" if start - 1 <= i < start - 1 + len(new_lines) else " "
        print("%s%5d| %s" % (mark, i + 1, lines[i][:200]))
    if rel.endswith(".py"):
        mod = _module(rel)
        if not mod.startswith(("docs_src", "scripts", "docs.", "tests")):
            t = _ws.cap(_ws.SCRIPT_TIMEOUT)
            code, out, err = sh(["timeout", "-k", "2", str(t), "python3", "-c", "import " + mod], ws, timeout=t + 5,
                                env=_ws.py_env(ws))
            if code:
                last = ((err or out).strip().splitlines() or ["?"])[-1]
                print("syntax OK, but import %s now fails: %s" % (mod, last[:200]))
            else:
                print("syntax OK, import OK")
        else:
            print("syntax OK")
    repro = state.get("repro")
    if repro and os.path.isfile(repro) and rel.endswith(".py"):
        # Immediate feedback on the change; check.py still does the full before/after run and the tests.
        t = _ws.cap(_ws.SCRIPT_TIMEOUT)
        code, out, _ = sh(["bash", "-c", "timeout -k 2 %d python3 -B %s 2>&1 | tail -3; exit ${PIPESTATUS[0]}"
                           % (t, shlex.quote(_ws.bound_script(repro)))], ws, timeout=t + 10, env=_ws.py_env(ws))
        print("your repro %s now: %s" % (repro, "passes" if code == 0 else "FAILS (exit %d)" % code))
        for l in out.strip().splitlines()[-3:]:
            print("    " + l[:200])
        if code in (124, 137):
            print(_ws.timeout_hint(t))
        try:
            with open(repro, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            st = load_state()
            _ws.record_repro(st, repro, _ws.digest(body), _ws.result_word(code), False)
            save_state(st)
        except OSError:
            pass
    print("EDIT APPLIED to %s. Any shell error printed after this line comes from text after the EOF marker "
          "and did not undo the edit." % rel)


if __name__ == "__main__":
    _ws.run_tool(main)
