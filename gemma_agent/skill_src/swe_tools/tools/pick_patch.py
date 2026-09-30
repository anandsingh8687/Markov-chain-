"""Pick the best patch of the two attempts and put it in /workspace (duo mode).

usage: python3 .swetools/pick_patch.py [--finisher]

Runs once per task (later calls print the same result): at the attempt deadline the first tool call of
either attempt runs it, and the finisher agent runs it as a backstop.

Candidates: each attempt's current patch and its last GATE-passing snapshot, with test, config and
scratch changes stripped, deduplicated. Hard filters: a changed source .py file, the patch applies to the
original code, the changed files compile, the changed modules import (only counted when they import on
the original code), fewer than 2 new failures in the related tests. Ranking: number of pooled repros the
patch passes (one repro per attempt, its latest plus the GATE one if different, counted only when it fails
on the original code) > finished normally (check.py OK or GATE on exactly this patch) > larger source diff
> attempt A. The winner is written into /workspace crash-safely; then every tool prints FINAL.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
import _duo  # noqa: E402

MAX_S = 40.0      # wall budget of one pick
MARGIN_S = 30.0   # keep this much of the session for submit_patch and the final reply


def rank_key(c):
    """Deterministic ranking (larger is better). Also replayed offline on stored attempts."""
    return (bool(c.get("valid")) and (c.get("new_fail") or 0) < 2,
            int(c.get("repro_pass") or 0),
            bool(c.get("finished")),
            int(c.get("src_lines") or 0),
            1 if c.get("att") == "a" else 0,
            1 if c.get("kind") == "current" else 0)


class Budget:
    def __init__(self, seconds):
        self.end = time.time() + seconds

    def left(self):
        return self.end - time.time()

    def t(self, want):
        return max(1, int(min(want, self.left())))


def _budget_seconds():
    r = _ws.remaining()
    if r is None:
        return MAX_S
    return max(0.0, min(MAX_S, r - MARGIN_S))


def _collect():
    snaps = os.path.join(_duo.ddir(), "snap")
    cands, repros = [], []
    for att, repo in sorted(_duo.repos().items()):
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        hist = _duo.read_json(os.path.join(snaps, att, "digests.json")) or {}
        raw = _duo.export_diff(repo)
        items = [("current", _duo.clean(raw or ""), raw)]
        gate_dir = os.path.join(snaps, att, "gate")
        try:
            with open(os.path.join(gate_dir, "patch.diff"), encoding="utf-8", errors="surrogateescape") as fh:
                items.append(("gate", fh.read(), None))
        except OSError:
            pass
        for kind, diff, raw_diff in items:
            d = _duo.digest(diff)
            h = hist.get(d) or {}
            cands.append({"att": att, "kind": kind, "diff": diff, "raw": raw_diff, "digest": d,
                          "src": _duo.src_py(diff), "src_lines": _duo.src_lines(diff),
                          "finished": bool(h.get("ok") or h.get("gate") or kind == "gate"),
                          "caused": h.get("caused") if h.get("tests_ran") else None})
        # one repro per attempt: its latest, plus the GATE one if different
        st = _ws.load_state(repo)
        bodies = []
        for path in (st.get("repro"), os.path.join(gate_dir, "repro.py")):
            if path and os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        body = fh.read()
                except OSError:
                    continue
                if body.strip() and body not in bodies:
                    bodies.append(body)
                    repros.append({"att": att, "path": path, "repo": repo})
    # dedupe identical patches (keep the first; merge 'finished')
    seen, out = {}, []
    for c in cands:
        if c["digest"] in seen:
            seen[c["digest"]]["finished"] |= c["finished"]
            if seen[c["digest"]].get("caused") is None:
                seen[c["digest"]]["caused"] = c.get("caused")
            continue
        seen[c["digest"]] = c
        out.append(c)
    return out, repros


def _reset(base):
    code, _, _ = _ws.sh("git checkout -q -f -- . && git clean -fdq", base, timeout=30)
    return code == 0


def _env(base, tag):
    import tempfile
    return _ws.py_env(base, {"PYTHONDONTWRITEBYTECODE": "1",
                             "PYTHONPYCACHEPREFIX": os.path.join(tempfile.gettempdir(), ".swe_pyc_" + tag)})


def _run(base, script, env, budget, limit=10):
    t = budget.t(limit)
    code, _, _ = _ws.sh(["bash", "-c", "timeout -k 2 %d python3 -B %s >/dev/null 2>&1" % (t, _q(script))],
                        base, timeout=t + 5, env=env)
    return code


def _q(s):
    import shlex
    return shlex.quote(s)


def _imports(base, mod, env, budget):
    t = budget.t(10)
    code, _, _ = _ws.sh(["timeout", "-k", "2", str(t), "python3", "-c", "import " + mod], base, timeout=t + 5,
                        env=env)
    return code == 0


def _measure(cands, repros, budget, notes):
    """Fill valid / repro_pass / new_fail for each candidate using the shared baseline copy."""
    import check
    base, why = check.ensure_base(_ws.real_workspace())
    if not base:
        notes.append("no baseline copy (%s): ranked without measurements" % why)
        return False
    if not _reset(base):
        notes.append("baseline copy could not be reset: ranked without measurements")
        return False
    env0 = _env(base, "base")
    mods = []
    for c in cands:
        for f in c["src"]:
            m = check.module_name(f)
            if not m.startswith(("docs_src", "scripts", "docs.", "tests")) and m not in mods:
                mods.append(m)
    base_ok = {m: _imports(base, m, env0, budget) for m in mods[:4] if budget.left() > 4}
    # repros that fail on the original code
    kept = []
    for r in repros:
        if budget.left() < 4:
            break
        extra = [r["repo"]] if r["repo"] != _ws.real_workspace() else []
        script = check.script_for_base(r["repo"], base, r["path"], extra)
        code = _run(base, script, env0, budget)
        if code != 0:
            kept.append(dict(r, script=script))
    notes.append("%d of %d repros fail on the original code" % (len(kept), len(repros)))
    for i, c in enumerate(cands):
        c["repro_n"] = len(kept)
        if budget.left() < 3:
            c["valid"] = True
            c["unmeasured"] = True
            continue
        _reset(base)
        dfile = os.path.join(_duo.ddir(), "cand%d.diff" % i)
        with open(dfile, "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write(c["diff"])
        code, _, err = _ws.sh(["git", "apply", "--whitespace=nowarn", dfile], base, timeout=budget.t(20))
        if code:
            c["valid"], c["why"] = False, "does not apply"
            continue
        bad = None
        for f in c["src"]:
            try:
                with open(os.path.join(base, f), encoding="utf-8", errors="replace") as fh:
                    compile(fh.read(), f, "exec")
            except SyntaxError as exc:
                bad = "syntax error in %s" % f
                break
            except (OSError, ValueError):
                pass
        env = _env(base, "c%d" % i)
        if not bad:
            for f in c["src"]:
                m = check.module_name(f)
                if base_ok.get(m) and budget.left() > 3 and not _imports(base, m, env, budget):
                    bad = "import %s fails" % m
                    break
        if bad:
            c["valid"], c["why"] = False, bad
            continue
        c["valid"] = True
        c["repro_pass"] = sum(1 for r in kept if budget.left() > 2 and _run(base, r["script"], env, budget) == 0)
    _reset(base)
    return base


def _tests(base, c, budget, cache):
    """New failures of candidate c in the related tests (vs the original code), or None if not measured."""
    import check
    if budget.left() < 15:
        return None
    tests = check.related_tests(base, c["src"])[:3]
    if not tests:
        return 0
    key = tuple(tests)
    if key not in cache:
        _reset(base)
        out0, to0, _ = check.run_pytest(tests, base, _env(base, "base"), min(20, budget.left() / 3))
        cache[key] = None if to0 else set(check.failed_ids(out0))
    before = cache[key]
    if before is None or budget.left() < 8:
        return None
    _reset(base)
    dfile = os.path.join(_duo.ddir(), "cand_t.diff")
    with open(dfile, "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write(c["diff"])
    if _ws.sh(["git", "apply", "--whitespace=nowarn", dfile], base, timeout=budget.t(20))[0]:
        return None
    out, to, _ = check.run_pytest(tests, base, _env(base, "t"), min(20, budget.left() - 3))
    _reset(base)
    if to:
        return None
    return len(set(check.failed_ids(out)) - before)


def _choose(reason):
    budget = Budget(_budget_seconds())
    _ws.CAP_LEFT[:] = [budget.left]
    notes = []
    cands, repros = _collect()
    real = _ws.real_workspace()
    w_raw = _duo.export_diff(real) or ""
    live = [c for c in cands if c["src"]]
    base = None
    if len(live) >= 2 and budget.left() >= 6:
        base = _measure(live, repros, budget, notes)
    for c in live:
        if "valid" not in c:
            c["valid"], c["unmeasured"] = True, True
        if c.get("caused") is not None:
            c["new_fail"] = c["caused"]
    # hard filter on test regressions, for the candidates that would win (cheapest first: known results)
    cache = {}
    for _ in range(3):
        order = sorted(live, key=rank_key, reverse=True)
        top = order[0] if order else None
        valid_n = sum(1 for c in live if c.get("valid"))
        if not top or not top.get("valid") or valid_n < 2 or "new_fail" in top or not base:
            break
        nf = _tests(base, top, budget, cache)
        top["new_fail"] = nf if nf is not None else 0
        top["tests"] = nf is not None
        if nf is None or nf < 2:
            break
    order = sorted(live, key=rank_key, reverse=True)
    winner = order[0] if order and order[0].get("valid") and (order[0].get("new_fail") or 0) < 2 else None
    if winner is None:
        w_clean = _duo.clean(w_raw)
        if _duo.src_py(w_clean):
            winner = next((c for c in live if c["att"] == "a" and c["kind"] == "current"), None)
            notes.append("no candidate passed the filters: /workspace kept")
        else:
            for att, kind in (("b", "current"), ("b", "gate"), ("a", "gate")):
                winner = next((c for c in live if c["att"] == att and c["kind"] == kind), None)
                if winner:
                    notes.append("no candidate passed the filters: /workspace was empty, took the latest non-empty patch")
                    break
    wrote = "kept /workspace as is"
    if winner is not None and _duo.norm(winner["diff"]) != _duo.norm(w_raw):
        r = _ws.remaining()
        w_empty = not _duo.src_py(_duo.clean(w_raw))
        if r is None or r >= 12 or (w_empty and r >= 5):
            ok, why = _duo.promote(winner["diff"], "pick-%s-%s" % (winner["att"], winner["kind"]))
            wrote = "written into /workspace" if ok else "NOT written (%s): /workspace kept" % why
            if not ok:
                notes.append(why)
        else:
            wrote = "not written (too little time left): /workspace kept"
    elif winner is not None:
        wrote = "already in /workspace"
    # table
    e = _ws.elapsed()
    lines = ["PICK (%s, T+%s): %d candidate(s) with a source change; %s" % (
        reason, "?" if e is None else int(e), len(live), "; ".join(notes[:2]) or "measured")]
    lines.append("   att kind     valid  repros  new_fail  lines")
    for c in order[:8]:
        valid = "?" if c.get("unmeasured") else ("yes" if c.get("valid") else "no (%s)" % c.get("why", "")[:30])
        lines.append("%s  %s   %-8s %-6s %-7s %-9s %d" % (
            "*" if c is winner else " ", c["att"].upper(), c["kind"], valid[:40],
            "%s/%s" % (c.get("repro_pass", "-"), c.get("repro_n", "-")),
            "-" if c.get("new_fail") is None else c["new_fail"], c["src_lines"]))
    if winner is not None:
        lines.append("chosen: attempt %s, %s patch -> %s" % (winner["att"].upper(), winner["kind"], wrote))
    else:
        lines.append("no attempt changed any source file: /workspace kept as is")
    summary = "\n".join(lines[:12])
    return {"winner": winner["att"] if winner else None, "kind": winner["kind"] if winner else None,
            "how": reason, "summary": summary}


def pick(reason, finisher=False):
    """Choose, write into /workspace, mark FINAL (once). Returns the final info, or None for NOT FINAL."""
    try:
        with _duo.Lock(wait=45):
            fin = _duo.final_info()
            if fin is None:
                e = _ws.elapsed()
                if finisher and e is not None and e < _ws.DEADLINE_S - 60:
                    cands, _ = _collect()
                    nudges = int((_duo.read_json(os.path.join(_duo.ddir(), "nudges.json")) or {}).get("n", 0))
                    if not any(c["src"] for c in cands) and nudges < 2:
                        _duo.write_json(os.path.join(_duo.ddir(), "nudges.json"), {"n": nudges + 1})
                        _ws.CONTROL.insert(0, "NOT FINAL: both attempts stopped early (T+%ds) without any source "
                                              "change. Reply with one line and do NOT call submit_patch: the "
                                              "attempts will continue." % e)
                        _duo._log("NOT FINAL (finisher at T+%d, nudge %d)" % (e, nudges + 1))
                        return None
                try:
                    fin = _choose(reason)
                except Exception as exc:  # selection must always end in FINAL
                    fin = {"winner": None, "how": reason, "summary": "pick failed (%s): /workspace kept" % exc}
                _duo.write_final(fin)
    except TimeoutError:
        fin = {"summary": "the pick lock is busy: /workspace kept as is"}
    if _duo.FINAL_LINE not in _ws.CONTROL:
        _ws.CONTROL.insert(0, _duo.FINAL_LINE)
    print(fin.get("summary", ""))
    return fin


def main():
    if not _ws.duo():
        print("pick_patch.py is for the two-attempt mode; in single mode just call submit_patch.")
        return
    pick("finisher" if "--finisher" in sys.argv else "manual", finisher="--finisher" in sys.argv)


if __name__ == "__main__":
    _ws.run_tool(main)
