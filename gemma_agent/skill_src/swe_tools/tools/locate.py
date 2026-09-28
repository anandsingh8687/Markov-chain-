"""Rank the code most relevant to an issue.

usage: python3 .swetools/locate.py TERM [TERM ...]
TERMs are identifiers, option names, error messages or phrases from the issue,
e.g.  locate.py strict_content_type "JSON requests" APIRouter "Content-Type"

Prints the best-matching definitions (file:line, signature, why), exact text
hits for each term, and the test files that exercise the top matches.
"""

import ast
import math
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ws import is_test_path, tracked_py, workspace, warn_if_repeated  # noqa: E402

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def subtokens(word):
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", word).lower().split("_")
    return [p for p in parts if len(p) > 2]


def defs_in(path, text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    lines = text.splitlines()
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            body = "\n".join(lines[node.lineno - 1:end])
            out.append((node.name, node.lineno, end, lines[node.lineno - 1].strip(), body))
    return out


def main():
    warn_if_repeated(sys.argv)
    terms = [t for t in sys.argv[1:] if t.strip()]
    if not terms:
        print(__doc__)
        return
    # "padding width" -> padding_width / paddingWidth, so phrases also match identifiers.
    for t in list(terms):
        words = re.findall(r"[A-Za-z][A-Za-z0-9]*", t)
        if 2 <= len(words) <= 3 and " " in t.strip():
            snake = "_".join(w.lower() for w in words)
            camel = words[0].lower() + "".join(w.capitalize() for w in words[1:])
            for v in (snake, camel):
                if v not in terms:
                    terms.append(v)
    ws = workspace()
    files = tracked_py(ws)
    src = [f for f in files if not is_test_path(f)]
    tests = [f for f in files if is_test_path(f) and os.path.basename(f) != "conftest.py"]

    idents = [t for t in terms if WORD.fullmatch(t)]
    phrases = [t for t in terms if not WORD.fullmatch(t)]
    toks = Counter()
    for t in terms:
        for w in WORD.findall(t):
            for s in subtokens(w):
                toks[s] += 1

    texts = {}
    for f in src:
        try:
            with open(os.path.join(ws, f), encoding="utf-8", errors="replace") as fh:
                texts[f] = fh.read()
        except OSError:
            pass

    # Inverse document frequency over definitions for sub-tokens.
    all_defs = []
    df = Counter()
    for f, text in texts.items():
        for d in defs_in(f, text):
            all_defs.append((f,) + d)
            words = set(s for w in WORD.findall(d[4]) for s in subtokens(w))
            for s in toks:
                if s in words:
                    df[s] += 1
    n = max(1, len(all_defs))

    scored = []
    for f, name, start, end, sig, body in all_defs:
        score, why = 0.0, []
        low_name = name.lower()
        for ident in idents:
            li = ident.lower()
            if li == low_name:
                score += 12; why.append("defines " + ident)
            elif li in low_name:
                score += 5; why.append("name~" + ident)
            c = body.count(ident)
            if c:
                score += 3 + math.log1p(c); why.append("%s x%d" % (ident, c))
        low_body = body.lower()
        for ph in phrases:
            if ph.lower() in low_body:
                score += 6; why.append('"%s"' % ph[:30])
        body_words = Counter(s for w in WORD.findall(body) for s in subtokens(w))
        for s in toks:
            if body_words[s]:
                score += math.log(1 + n / (1 + df[s])) * (0.4 + 0.15 * math.log1p(body_words[s]))
        for s in toks:
            if s in f.lower():
                score += 0.8
        # Prefer focused definitions over whole classes / huge functions.
        score /= 1 + 0.35 * math.log1p(max(0, end - start - 60))
        if f.startswith(("docs_src/", "docs/", "examples/", "scripts/")):
            score *= 0.5
        if score > 0:
            scored.append((score, f, start, end, sig, why))
    scored.sort(key=lambda x: -x[0])

    print("TOP DEFINITIONS (file:line-end  signature  [why])")
    shown, per_file = 0, Counter()
    for score, f, start, end, sig, why in scored:
        if per_file[f] >= 3:
            continue
        per_file[f] += 1
        shown += 1
        print("%2d. %s:%d-%d  %s  [%s]" % (shown, f, start, end, sig[:110], ", ".join(why[:4])))
        if shown >= 12:
            break

    print("\nEXACT TEXT HITS (first 4 per term, library code first)")
    ordered = sorted(src, key=lambda f: f.startswith(("docs_src/", "docs/", "examples/", "scripts/")))
    for t in terms:
        hits = []
        needle = t if WORD.fullmatch(t) else t.lower()
        for f in ordered:
            text = texts.get(f, "")
            hay = text if WORD.fullmatch(t) else text.lower()
            if needle in hay:
                for i, line in enumerate(hay.splitlines(), 1):
                    if needle in line:
                        hits.append("%s:%d" % (f, i))
                        if len(hits) >= 4:
                            break
            if len(hits) >= 4:
                break
        print('  "%s": %s' % (t[:40], ", ".join(hits) if hits else "no match in source"))

    top_names = []
    for score, f, start, end, sig, why in scored[:8]:
        m = re.match(r"(?:async\s+)?(?:def|class)\s+(\w+)", sig)
        if m and m.group(1) not in top_names and not m.group(1).startswith("__"):
            top_names.append(m.group(1))
    top_mods = set(os.path.splitext(os.path.basename(f))[0] for _, f, *_ in scored[:8])
    test_hits = defaultdict(int)
    for t in tests:
        try:
            with open(os.path.join(ws, t), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for name in top_names + idents:
            if name in text:
                test_hits[t] += text.count(name)
        base = os.path.basename(t)
        for mod in top_mods:
            if base in ("test_%s.py" % mod, "%s_test.py" % mod):
                test_hits[t] += 20
    print("\nTEST FILES FOR THIS CODE (hidden tests usually go into one of these)")
    ranked = sorted(test_hits.items(), key=lambda kv: -kv[1])[:6]
    print("  " + (", ".join("%s" % t for t, _ in ranked) if ranked else "none found"))


if __name__ == "__main__":
    main()
