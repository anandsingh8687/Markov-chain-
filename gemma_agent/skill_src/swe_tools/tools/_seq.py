"""Sequential two-attempt mode (bundle_v25): ONE agent, two attempts in /workspace, one after the other.

Attempt 1 works in /workspace as in v23. check.py's GATE (a source change that compiles and imports, a repro
that FAILS on the original code and passes now, no test broken) ends the task at once: FINAL. Otherwise:
  * T+SWITCH_S (150): the first helper call saves attempt 1 (cleaned diff + repro + meta) into D/att/1, resets
    /workspace to the baseline (journaled, see _duo.promote) and prints ATTEMPT 2 first. The tool itself is not
    run (its arguments belong to attempt 1), except check.py shortly after the switch time, which runs first
    and switches afterwards unless it passes the GATE.
  * attempt 2 ends with its own GATE (FINAL at once), with a check.py OK verdict (the tools pick at once), or
    at T+PICK_S (265): the first helper call saves attempt 2, picks the better attempt with pick_patch's
    ranking (pooled repros, hard filters), writes it into /workspace and prints FINAL first.
  * publisher: from T+PUBLISH_S (240) on, while attempt 2 has no compiling source change and attempt 1 had one,
    every helper call restores attempt 1 into /workspace (the floor if the harness times out before the pick).
State: D = <TMP>/.swe/<hash of /workspace>; D/seq.json {"phase": 1|2, "pending": null|"switch"|"pick",
"final": {...}|null}; D/att/<n>/{patch.diff, repro<n>.py, meta.json, digests.json}.
"""

import io
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402
import _duo  # noqa: E402

FINAL_LINE = "FINAL PATCH IS IN /workspace: call submit_patch now"
ATT2_LINE = ("ATTEMPT 2: your first attempt is saved. The workspace is reset. Try a DIFFERENT approach or location; "
             "write a new repro at /tmp/repro2.py; make the most likely edit within ~60 s.")


def _num(env, key, default):
    try:
        return float(os.environ.get(env) or _ws.cfg().get(key) or default)
    except ValueError:
        return float(default)


SWITCH_S = _num("SWE_SWITCH_S", "switch_s", 150)
PUBLISH_S = _num("SWE_PUBLISH_S", "publish_s", 240)
PICK_S = _num("SWE_PICK_S", "pick_s", 265)
CHECK_DEFER_S = 30  # check.py started within this many s after SWITCH_S still checks attempt 1 first


def _p(*names):
    return os.path.join(_duo.ddir(), *names)


def load():
    st = _duo.read_json(_p("seq.json")) or {}
    st.setdefault("phase", 1)
    return st


def save(st):
    _duo.write_json(_p("seq.json"), st)


def log(msg):
    try:
        with open(_p("seq.log"), "a") as fh:
            e = _ws.elapsed()
            fh.write("[T+%s] %s\n" % ("?" if e is None else int(e), msg))
    except OSError:
        pass


def att_dir(n):
    return _p("att", str(n))


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as fh:
            return fh.read()
    except OSError:
        return None


# ---------------------------------------------------------------- snapshots

def snapshot(n, tag=""):
    """Save attempt n's cleaned /workspace diff, its remembered repro and meta (atomic: tmp dir + rename)."""
    ws = _ws.real_workspace()
    raw = _duo.export_diff(ws)
    if raw is None:
        raise RuntimeError("cannot read the /workspace diff")
    diff = _duo.clean(raw)
    d = att_dir(n)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    tmp = d + ".new%d" % os.getpid()
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with open(os.path.join(tmp, "patch.diff"), "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write(diff)
    state = _ws.load_state()
    repro = state.get("repro")
    meta = {"t": _ws.elapsed(), "digest": _duo.digest(diff), "files": [s["path"] for s in _duo.sections(diff)],
            "verdict": state.get("last_verdict") or "", "repro_path": None, "tag": tag}
    if repro and os.path.isfile(repro):
        shutil.copyfile(repro, os.path.join(tmp, "repro%d.py" % n))  # distinct names: base copies never collide
        meta["repro_path"] = repro
    hist = _duo.read_json(os.path.join(d, "digests.json"))
    if hist:
        _duo.write_json(os.path.join(tmp, "digests.json"), hist)
    _duo.write_json(os.path.join(tmp, "meta.json"), meta)
    old = d + ".old%d" % os.getpid()
    if os.path.isdir(d):
        os.rename(d, old)
    os.rename(tmp, d)
    shutil.rmtree(old, ignore_errors=True)
    return diff


def snap_diff(n):
    return read_text(os.path.join(att_dir(n), "patch.diff"))


def snap_tag(n):
    return (_duo.read_json(os.path.join(att_dir(n), "meta.json")) or {}).get("tag")


def record_check(phase, ok, gate, caused, tests_ran):
    """Remember check.py's result for the current cleaned diff of this attempt (pick: 'finished', 'caused')."""
    try:
        diff = _duo.clean(_duo.export_diff(_ws.real_workspace()) or "")
        d = att_dir(phase)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "digests.json")
        hist = _duo.read_json(path) or {}
        hist[_duo.digest(diff)] = {"ok": bool(ok), "gate": bool(gate), "caused": caused, "tests_ran": bool(tests_ran)}
        _duo.write_json(path, hist)
    except Exception as exc:
        log("record_check failed: %s" % exc)


def _reset_tool_state():
    """Attempt 2 starts with a clean state line: no repro, no verdict, no rewrites, no repeated-command memory."""
    st = _ws.load_state()
    keep = {k: st[k] for k in ("viewed_files",) if k in st}
    _ws.save_state(keep)
    try:
        os.remove(_ws._workspace_state_path(".swetools_seen"))
    except OSError:
        pass


# ---------------------------------------------------------------- the switch (T+150)

def _summary_files(diff):
    out = []
    for s in _duo.sections(diff):
        add = sum(1 for l in s["text"].splitlines() if l.startswith("+") and not l.startswith("+++"))
        rem = sum(1 for l in s["text"].splitlines() if l.startswith("-") and not l.startswith("---"))
        out.append("%s +%d-%d" % (s["path"], add, rem))
    return ", ".join(out[:4]) + (" (+%d more)" % (len(out) - 4) if len(out) > 4 else "")


def do_switch(why="time"):
    """Save attempt 1, reset /workspace to the original code, enter attempt 2. Idempotent and crash-safe:
    seq.json says 'pending: switch' until the reset is verified; the next helper call finishes it."""
    with _duo.Lock(wait=45):
        st = load()
        if st.get("final") or st.get("phase") != 1:
            return st
        if st.get("pending") != "switch" or snap_diff(1) is None or snap_tag(1) != "switch":
            st["pending"] = "switch"
            save(st)
            snapshot(1, "switch")  # /workspace is still attempt 1 here: the reset starts only after the snapshot exists
        ok, msg = _duo.promote("", "switch-reset")
        diff1 = snap_diff(1) or ""
        st.update(phase=2, pending=None, switch_t=_ws.elapsed(), reset_ok=bool(ok), switch_why=why)
        save(st)
        log("switch (%s): attempt 1 = %s; reset %s" % (why, _summary_files(diff1) or "empty", msg))
    _reset_tool_state()
    if ok:
        _ws.CONTROL.insert(0, ATT2_LINE)
    else:
        _ws.CONTROL.insert(0, "ATTEMPT 2: your first attempt is saved, but /workspace could NOT be reset (%s): "
                              "your edits continue on top of it. Try a DIFFERENT approach or location; write a new "
                              "repro at /tmp/repro2.py; make the most likely edit within ~60 s." % msg)
    print("Attempt 1 (saved, the tools compare it with attempt 2 at the end): %s." % (
        _summary_files(diff1) or "no source change"))
    print("At T+%d (or as soon as check.py says OK) the tools put the better attempt into /workspace and print "
          "FINAL. GATE PASSED in attempt 2 ends the task at once." % PICK_S)
    return load()


# ---------------------------------------------------------------- the pick (T+265 or a check.py OK in attempt 2)

def _compiles(ws, files):
    for f in files:
        try:
            with open(os.path.join(ws, f), encoding="utf-8", errors="replace") as fh:
                compile(fh.read(), f, "exec")
        except SyntaxError:
            return False
        except (OSError, ValueError):
            pass
    return True


def choose(reason):
    import pick_patch
    budget = pick_patch.Budget(pick_patch._budget_seconds())
    _ws.CAP_LEFT[:] = [budget.left]
    ws = _ws.real_workspace()
    notes, cands, repros, bodies = [], [], [], []
    for n in (1, 2):
        d = att_dir(n)
        diff = snap_diff(n) or ""
        hist = _duo.read_json(os.path.join(d, "digests.json")) or {}
        dg = _duo.digest(diff)
        h = hist.get(dg) or {}
        cands.append({"att": "a" if n == 1 else "b", "n": n, "kind": "att%d" % n, "diff": diff, "digest": dg,
                      "src": _duo.src_py(diff), "src_lines": _duo.src_lines(diff),
                      "finished": bool(h.get("ok") or h.get("gate")),
                      "caused": h.get("caused") if h.get("tests_ran") else None})
        rp = os.path.join(d, "repro%d.py" % n)
        body = read_text(rp)
        if body and body.strip() and body not in bodies:
            bodies.append(body)
            repros.append({"att": "a" if n == 1 else "b", "path": rp, "repo": ws})
    seen, uniq = {}, []
    for c in cands:  # identical patches (e.g. attempt 1 restored by the publisher and kept): one candidate
        if c["digest"] in seen:
            seen[c["digest"]]["finished"] |= c["finished"]
            continue
        seen[c["digest"]] = c
        uniq.append(c)
    live = [c for c in uniq if c["src"]]
    base = None
    if len(live) >= 2 and budget.left() >= 6:
        base = pick_patch._measure(live, repros, budget, notes)
    for c in live:
        if "valid" not in c:
            c["valid"], c["unmeasured"] = True, True
        if c.get("caused") is not None:
            c["new_fail"] = c["caused"]
    cache = {}
    for _ in range(2):
        order = sorted(live, key=pick_patch.rank_key, reverse=True)
        top = order[0] if order else None
        if not top or not top.get("valid") or sum(1 for c in live if c.get("valid")) < 2 or "new_fail" in top \
                or not base:
            break
        nf = pick_patch._tests(base, top, budget, cache)
        top["new_fail"] = nf if nf is not None else 0
        if nf is None or nf < 2:
            break
    order = sorted(live, key=pick_patch.rank_key, reverse=True)
    winner = order[0] if order else None
    if winner is not None and not (winner.get("valid") and (winner.get("new_fail") or 0) < 2):
        notes.append("no candidate passed the filters: took the best-ranked one")
    w_raw = _duo.export_diff(ws)
    wrote = "kept /workspace as is"
    if winner is not None and w_raw is not None and _duo.norm(winner["diff"]) != _duo.norm(w_raw):
        r = _ws.remaining()
        w_empty = not _duo.src_py(_duo.clean(w_raw))
        if r is None or r >= 12 or (w_empty and r >= 5):
            ok, why = _duo.promote(winner["diff"], "pick-att%d" % winner["n"])
            wrote = "written into /workspace" if ok else "NOT written (%s): /workspace kept" % why
        else:
            wrote = "not written (too little time left): /workspace kept"
    elif winner is not None:
        wrote = "already in /workspace"
    e = _ws.elapsed()
    lines = ["PICK (%s, T+%s): %d attempt(s) with a source change; %s" % (
        reason, "?" if e is None else int(e), len(live), "; ".join(notes[:2]) or "measured")]
    lines.append("   att  valid  repros  new_fail  lines")
    for c in order:
        valid = "?" if c.get("unmeasured") else ("yes" if c.get("valid") else "no (%s)" % c.get("why", "")[:30])
        lines.append("%s  %d    %-6s %-7s %-9s %d" % (
            "*" if c is winner else " ", c["n"], valid[:40], "%s/%s" % (c.get("repro_pass", "-"), c.get("repro_n", "-")),
            "-" if c.get("new_fail") is None else c["new_fail"], c["src_lines"]))
    if winner is not None:
        lines.append("chosen: attempt %d -> %s" % (winner["n"], wrote))
    else:
        lines.append("neither attempt changed a source file: /workspace kept as is")
    return {"winner": winner["n"] if winner else None, "how": reason, "summary": "\n".join(lines[:10])}


def do_pick(reason):
    """Save attempt 2, choose the better attempt, write it into /workspace, mark FINAL (once)."""
    try:
        with _duo.Lock(wait=45):
            st = load()
            fin = st.get("final")
            if not fin:
                if st.get("phase") != 2:  # never switched (no time anchor before): attempt 1 is all there is
                    fin = {"winner": 1, "how": reason, "summary": "single attempt: /workspace kept"}
                else:
                    if st.get("pending") != "pick" or snap_diff(2) is None or snap_tag(2) != "pick":
                        st["pending"] = "pick"  # after a kill the redo uses this snapshot, not /workspace
                        save(st)
                        snapshot(2, "pick")
                    try:
                        fin = choose(reason)
                    except Exception as exc:  # the pick must always end in FINAL
                        fin = {"winner": None, "how": reason, "summary": "pick failed (%s): /workspace kept" % exc}
                fin["t"] = _ws.elapsed()
                st.update(final=fin, pending=None)
                save(st)
                log("FINAL (%s): %s" % (reason, fin.get("summary", "").replace("\n", " | ")[:300]))
    except TimeoutError:
        fin = {"summary": "the pick lock is busy: /workspace kept as is"}
    if FINAL_LINE not in _ws.CONTROL:
        _ws.CONTROL.insert(0, FINAL_LINE)
    print(fin.get("summary", ""))
    return fin


def finalize_gate(phase):
    with _duo.Lock(wait=45):
        st = load()
        if not st.get("final"):
            st.update(final={"winner": phase, "how": "gate", "t": _ws.elapsed(),
                             "summary": "attempt %d passed the GATE; its patch is in /workspace" % phase},
                      pending=None)
            save(st)
            log("FINAL: GATE in attempt %d" % phase)
    if FINAL_LINE not in _ws.CONTROL:
        _ws.CONTROL.insert(0, FINAL_LINE)


# ---------------------------------------------------------------- publisher (T+240 .. pick)

def publish():
    """Attempt 2 has no compiling source change but attempt 1 had one: put attempt 1 into /workspace, so a
    harness timeout before the pick still submits it."""
    ws = _ws.real_workspace()
    d1 = snap_diff(1) or ""
    if not _duo.src_py(d1):
        return
    raw = _duo.export_diff(ws)
    if raw is None:
        return
    cl = _duo.clean(raw)
    src = _duo.src_py(cl)
    if src and _compiles(ws, src):
        return
    with _duo.Lock(wait=30):
        st = load()
        if st.get("final") or st.get("phase") != 2:
            return
        if src:
            snapshot(2)  # keep attempt 2's broken version on record
        ok, why = _duo.promote(d1, "publish-att1")
        st["published"] = st.get("published", 0) + (1 if ok else 0)
        save(st)
        log("publisher: attempt 2 %s; attempt 1 restored: %s" % ("does not compile" if src else "empty", why))
    if ok:
        _ws.WARN.append("NOTE: attempt 2 has %s, so attempt 1's patch was put back into /workspace as the fallback "
                        "(your next edits apply on top of it). At T+%d the tools pick the better attempt."
                        % ("a syntax error" if src else "no source change yet", PICK_S))


# ---------------------------------------------------------------- hooks around every helper tool

def before_tool(tool):
    """True = do not run the tool. May print the ATTEMPT 2 / FINAL text (CONTROL lines come first)."""
    _duo.recover()
    st = load()
    if st.get("pending") == "switch" and not st.get("final"):
        do_switch("recovered")
        print("(Your command was not run: it belonged to attempt 1.)")
        return True
    if st.get("pending") == "pick" and not st.get("final"):
        do_pick("recovered")
        return True
    if st.get("final"):
        _ws.CONTROL.insert(0, FINAL_LINE)
        print("The attempts are over: " + (st["final"].get("summary") or "") + "\nCall submit_patch now.")
        return True
    e = _ws.elapsed()
    if e is None:
        return False
    if st.get("phase") == 1 and e >= SWITCH_S:
        if tool == "check.py" and e < SWITCH_S + CHECK_DEFER_S:
            return False  # check attempt 1 first (a GATE ends the task); the switch follows in after_tool
        print("ATTEMPT 1 TIME UP (T+%ds)." % e)
        do_switch()
        print("(Your command was not run: it belonged to attempt 1.)")
        return True
    if st.get("phase") == 2 and e >= PICK_S:
        print("ATTEMPT 2 TIME UP (T+%ds): picking the better attempt." % e)
        do_pick("deadline")
        return True
    if st.get("phase") == 2 and e >= PUBLISH_S:
        publish()
    return False


def after_tool(tool):
    st = load()
    if st.get("final") or st.get("pending"):
        return
    e = _ws.elapsed()
    if e is not None and st.get("phase") == 1 and e >= SWITCH_S:
        print("\nATTEMPT 1 TIME UP (T+%ds): no GATE." % e)
        do_switch()


def finish_check(ws, problems, info, repro, changed_src, caused, tests_found, tests_ran):
    """check.py's ending in seq mode: verdict, GATE -> FINAL, attempt 2 OK -> pick now."""
    st0 = load()
    phase = st0.get("phase", 1)
    final = bool(st0.get("final"))
    gate = (not problems and bool(changed_src) and info.get("before_definite") and info.get("before") == "FAILS"
            and info.get("now") == "passes" and (tests_ran or not tests_found))
    if problems:
        print("VERDICT: FIX BEFORE SUBMITTING")
        for p in problems:
            print("  - " + p)
    elif gate:
        print("VERDICT: GATE PASSED (source change, compiles, imports, repro FAILS->passes, no test broken)")
    else:
        why = []
        if repro is None or not info.get("before_definite") or info.get("before") != "FAILS":
            why.append("a repro that FAILS without your change (check.py --repro /tmp/repro%s.py)"
                       % ("2" if phase == 2 else ""))
        if tests_found and not tests_ran:
            why.append("the related tests to finish")
        print("VERDICT: OK, but no GATE yet: the GATE also needs %s." % " and ".join(why or ["a clean run"]))
    st = _ws.load_state()  # remembered for status.py and the state line
    st["last_verdict"] = ("FIX BEFORE SUBMITTING: " + " | ".join(p[:120] for p in problems[:4])) if problems else "OK"
    st["verdict_patch"] = _ws.patch_digest(ws)
    if repro and info.get("body"):
        st["rs"] = {"path": repro, "body": info["body"], "before": info.get("before", "?"),
                    "now": info.get("now", "?")}
    _ws.save_state(st)
    if final:
        return
    record_check(phase, not problems, gate, len(caused), tests_ran)
    if gate:
        finalize_gate(phase)
        print("Your verified patch is in /workspace: call submit_patch now.")
    elif not problems and phase == 2:
        print("Attempt 2 is complete: picking the better of your two attempts now.")
        do_pick("check-ok")
    elif not problems and (_ws.elapsed() or 0) < SWITCH_S:
        print("Improve that if you can (do not call submit_patch yet). If not, keep this patch: at T+%d it is saved, "
              "you get a second attempt, and the better one is submitted." % SWITCH_S)


# ---------------------------------------------------------------- state line and the tool wrapper

def state_line():
    try:
        ws = _ws.workspace()
        st = load()
        state = _ws.load_state()
        e = _ws.elapsed()
        clock = "T+%ds/%d" % (e, _ws.BUDGET_S) if e is not None else "T+?/%d" % _ws.BUDGET_S
        patch, empty = _ws._patch_summary(ws)
        if st.get("final"):
            return "[%s | FINAL | patch: %s | call submit_patch now]" % (clock, patch)
        phase = st.get("phase", 1)
        who = "attempt 1 until T+%d" % SWITCH_S if phase == 1 else "attempt 2 until T+%d" % PICK_S
        rs = state.get("rs") or {}
        if rs.get("path"):
            rep = "repro %s: %s" % (rs["path"], rs.get("now", "?")) if empty else \
                "repro %s: %s->%s" % (rs["path"], rs.get("before", "?"), rs.get("now", "?"))
        else:
            rep = "repro: none"
        verdict = state.get("last_verdict") or ""
        if not verdict:
            chk = "not run"
        else:
            chk = "OK" if verdict.startswith("OK") else "FIX"
            if not empty and state.get("verdict_patch") and state.get("verdict_patch") != _ws.patch_digest(ws):
                chk += " (patch changed since)"
        parts = [clock, who, "patch: " + patch, rep, "check: " + chk, "rewrites %d" % state.get("rewrites", 0)]
        start = 0 if phase == 1 else (st.get("switch_t") or SWITCH_S)
        if empty and e is not None and e - start >= (90 if phase == 1 else 45):
            parts.append("EDIT NOW: make the most likely edit")
        elif phase == 1 and e is not None and SWITCH_S - e < 40 and not empty:
            parts.append("LOW TIME: check.py --repro now; GATE PASSED ends the task")
        elif phase == 2 and e is not None and PICK_S - e < 40 and not empty:
            parts.append("LOW TIME: finish with check.py; at T+%d the tools pick the better attempt" % PICK_S)
        return "[" + " | ".join(parts) + "]"
    except Exception as exc:  # the state line must never break a tool
        return "[state unavailable: %s]" % str(exc)[:80]


def run_tool(main):
    """_ws.run_tool for seq mode: the hooks, then CONTROL lines (ATTEMPT 2 / FINAL) FIRST, then the state line."""
    real = sys.stdout
    buf = io.StringIO()
    sys.stdout = buf
    code = 0
    tool = os.path.basename(sys.argv[0])
    try:
        try:
            _ws.clean_stale_lock(_ws.workspace())
        except SystemExit:
            raise
        except Exception:
            pass
        skip = False
        try:
            skip = before_tool(tool)
        except Exception as exc:  # the hooks must never break a tool
            log("before_tool error: %s" % exc)
        try:
            if not skip:
                main()
        finally:
            try:
                after_tool(tool)
            except Exception as exc:
                log("after_tool error: %s" % exc)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            buf.write(exc.code + "\n")
            code = 1
        else:
            code = exc.code or 0
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:  # never leave the model with a bare traceback
        import traceback
        buf.write("tool error: %s\n%s" % (exc, "".join(traceback.format_exc().splitlines(True)[-4:])))
        code = 1
    finally:
        sys.stdout = real
    out = "".join(l + "\n" for l in _ws.CONTROL + _ws.WARN) + state_line() + "\n" + buf.getvalue().rstrip("\n") + "\n"
    real.write(_ws._cap_text(out, _ws.OUTPUT_CAP))
    real.flush()
    sys.exit(code)
