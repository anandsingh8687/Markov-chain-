"""Predict real scorer seconds per task from lab traces (results.jsonl + traces/trace_<id>.json).

The scorer runs tasks one at a time on 4xL4, so a task's agent time is the sum of its LLM steps plus tool time.
Per LLM call (one ATIF step that carries `metrics`):

    seconds = PER_CALL + PER_TOKEN x completion tokens + PER_KUNCACHED x uncached prompt tokens / 1000
    + PER_COMPACTION when the call follows an ADK history compaction (prompt < 0.7 x the stream's previous prompt)

plus the measured tool time (observation timestamp - call timestamp, every tool except agent tools, whose
interval holds other agents' calls), plus PER_TASK. Uncached prompt tokens = growth of that stream's prompt
since its previous call (vLLM prefix caching keeps the rest; the first call of a stream pays its whole
prompt). Calls of agents that run at the same time (ParallelAgent branches: two authors whose call ranges
overlap under the same parent) cost max(stream sums) x PARALLEL_SLOWDOWN[k]. The scorer's asyncio.timeout
cuts the agent at max_time_minutes (from the bundle's eval_config.yaml, kept by the kernel in
<out>/bundles/<name>/), so predictions are capped there (timeout flag). Task seconds = predicted agent
seconds + the row's measured non-agent time (sandbox setup + Phase 2 grading = task_seconds - real agent
seconds, e.g. rich_3772's hidden tests always run into their 300 s timeout).

Constants were fitted on the sequential REAL-clock runs lab17a (v28, v29) and lab17b (v29, v29c36), 1,433 LLM
steps: `python timepred.py --fit lab17aout lab17bout` refits and validates (in-sample and leave-one-kernel-
out). Virtual-clock runs (concurrent labs 15/16/18) are predicted with the same constants from their token
counts; their measured tool/grading seconds come from a loaded machine (6 tasks at once), so they are a bit
pessimistic.

Usage:
    python timepred.py LABOUT [LABOUT ...] [--ref v29] [--n-tasks 120] [--startup 500] [--per-task]
    python timepred.py --fit LABOUT_REAL [...]            # refit + validation table (needs real-clock runs)
    python timepred.py --json out.jsonl LABOUT ...        # per task-run predictions for other tools

LABOUT is a downloaded kernel output dir (holding lab/results.jsonl, lab/<bundle>[/r<rep>]/traces/), a lab/
dir, or a results.jsonl next to traces/ (run_official.py layout). Rows whose trace is missing are predicted
from the row's vc_* counters (calls, completion tokens, tool seconds) with the per-call averages.

Sub-agents: ADK's AgentTool forwards the parent's plugins to its own Runner (include_plugins defaults to True),
so the harness's EventDisplayPlugin sees the inner agent's events: they are in the trace (author = the
sub-agent's name), counted in llm_calls / max_turns, and charged by labworker's virtual clock. A bundle that
sets include_plugins: false makes them invisible to all three; timepred then sees one long opaque tool call
(reported as opaque_tool_s, counted as measured time).
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import statistics
import sys
from pathlib import Path

# Fitted on lab17a+lab17b (sequential, real clock): `python timepred.py --fit lab17aout lab17bout`.
CONSTS = {
    "per_call": 0.115,       # s per LLM call (request overhead; the fit intercept)
    "per_token": 0.02855,    # s per completion token (35.0 tok/s single-stream decode, thinking included)
    "per_kuncached": 0.335,  # s per 1k uncached prompt tokens (prefill ~3k tok/s)
    "per_compaction": 25.4,  # s extra per compaction (the summary call ADK makes before the next step)
    "per_task": -0.05,       # s per task outside steps and tools (mean agent-time residual)
}
PARALLEL_SLOWDOWN = {1: 1.0, 2: 1.11, 3: 1.23, 4: 1.35}  # per-stream decode slowdown, k streams at once
COMPACTION_DROP = 0.7
DEFAULT_CAP_S = 480.0
HARNESS_TOOLS = {"run_command", "read_file", "edit_file", "write_file", "submit_patch", "get_status",
                 "search_similar_code", "get_code_neighbors", "get_code_context", "run_skill_script",
                 "load_skill", "load_skill_resource", "list_skills"}


# ------------------------------------------------------------------ discovery

def find_runs(path: str) -> list[dict]:
    """[{'label', 'results': Path, 'lab': Path (dir with <bundle>/...), 'bundles_dir': Path|None}]"""
    p = Path(path)
    if p.is_file():
        return [{"label": p.parent.name, "results": p, "lab": p.parent, "bundles_dir": None}]
    for lab in (p / "lab", p):
        if (lab / "results.jsonl").is_file():
            bd = lab.parent / "bundles" if (lab.parent / "bundles").is_dir() else None
            label = (p.name if p.name != "lab" else p.parent.name)
            return [{"label": label, "results": lab / "results.jsonl", "lab": lab, "bundles_dir": bd}]
    raise FileNotFoundError(f"{path}: no results.jsonl (looked in {p}/lab and {p})")


def load_rows(path: str) -> list[dict]:
    """results.jsonl rows of a run with '_run', '_trace' (path or None) and '_cap' (agent time cap, s) attached."""
    out = []
    for run in find_runs(path):
        caps: dict = {}
        for line in run["results"].read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            r["_run"] = run["label"]
            b = r.get("bundle", "")
            rep = r.get("replicate")
            safe = str(r.get("id", "")).replace("/", "__")
            cands = []
            if rep is not None:
                cands.append(run["lab"] / b / f"r{rep}" / "traces" / f"trace_{safe}.json")
            cands += [run["lab"] / b / "traces" / f"trace_{safe}.json", run["lab"] / "traces" / f"trace_{safe}.json"]
            r["_trace"] = next((str(c) for c in cands if c.is_file()), None)
            logs = [Path(str(c).replace("/traces/trace_", "/calls/")[:-5] + ".jsonl") for c in cands]
            r["_calllog"] = next((str(c) for c in logs if c.is_file()), None)
            if b not in caps:
                caps[b] = bundle_cap(run["bundles_dir"] / b if run["bundles_dir"] else None)
            r["_cap"] = caps[b]
            out.append(r)
    return out


def bundle_cap(bundle_dir: Path | None) -> float:
    if bundle_dir is None or not (bundle_dir / "eval_config.yaml").is_file():
        return DEFAULT_CAP_S
    try:
        import yaml
        ev = (yaml.safe_load((bundle_dir / "eval_config.yaml").read_text()) or {}).get("evaluation", {}) or {}
    except Exception:  # noqa: BLE001
        import re
        m = re.search(r"max_time_minutes:\s*([0-9.]+)", (bundle_dir / "eval_config.yaml").read_text())
        ev = {"max_time_minutes": float(m.group(1))} if m else {}
    mt = ev.get("max_time_minutes")
    return float(mt) * 60.0 if mt else DEFAULT_CAP_S


# ------------------------------------------------------------------ trace parsing

def parse_trace(path: str) -> dict:
    """LLM calls of one ATIF trace with timing features (see _finish).

    A call is a step with `metrics`; following steps without metrics but with tool_calls are further function
    calls of the same response. Exact for single-agent bundles. For nested agents the ATIF converter is lossy
    (an agent tool's first inner call is merged into the caller's step), so labworker's call log
    (<results>/calls/<id>.jsonl, parse_calllog) is preferred when present.
    """
    t = json.loads(Path(path).read_text())
    steps = t.get("steps") or []
    prompt_ts = None
    calls: list[dict] = []
    last_ts = None
    nudges = 0
    for s in steps:
        ex = s.get("extra") or {}
        ts = ex.get("timestamp")
        if ts is not None:
            last_ts = ts if last_ts is None else max(last_ts, ts)
        ob = s.get("observation")
        oe = (ob.get("extra") or {}) if isinstance(ob, dict) else {}
        if oe.get("timestamp") is not None:
            last_ts = max(last_ts or oe["timestamp"], oe["timestamp"])
        et = ex.get("event_type")
        if et == "task_prompt":
            prompt_ts = ts
            continue
        if et == "continuation_nudge":
            nudges += 1
        if s.get("source") != "agent":
            continue
        tcs = s.get("tool_calls") or []
        if "metrics" in s:
            m = s["metrics"] or {}
            calls.append({"author": ex.get("author") or "", "ts": ts, "ct": int(m.get("completion_tokens") or 0),
                          "pt": int(m.get("prompt_tokens") or 0), "tools": []})
        elif not tcs or not calls:
            continue
        for tc in tcs:
            calls[-1]["tools"].append({"name": tc.get("function_name") or "",
                                       "ts": (tc.get("extra") or {}).get("timestamp", ts), "obs": oe.get("timestamp")})
    out = _finish(calls, prompt_ts, last_ts)
    out.update(nudges=nudges, fm=t.get("final_metrics") or {}, source="trace")
    merged = sum(1 for c in calls if len({tl["name"] for tl in c["tools"]} - HARNESS_TOOLS) and len(c["tools"]) > 1)
    if merged:
        out["warning"] = "ATIF merged nested-agent calls; use labworker's call log for this bundle"
    return out


def parse_calllog(path: str) -> dict:
    """labworker's per-event log: {"k": "start"|"llm"|"resp", "t", "a" author, "b" branch, "pt", "ct",
    "fc": [[name, id]], "fr": [[name, id]]}. Tool interval = function call -> matching function response."""
    recs = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    start = next((r["t"] for r in recs if r.get("k") == "start"), None)
    resp_t: dict = {}
    for r in recs:
        for name, fid in r.get("fr") or []:
            resp_t.setdefault(fid or name, r["t"])
    calls = []
    for r in recs:
        if r.get("k") != "llm":
            continue
        tools = [{"name": name, "ts": r["t"], "obs": resp_t.get(fid or name)} for name, fid in r.get("fc") or []]
        calls.append({"author": r.get("a") or "", "branch": r.get("b") or "", "ts": r["t"], "ct": int(r.get("ct") or 0),
                      "pt": int(r.get("pt") or 0), "tools": tools})
    last = max((r["t"] for r in recs), default=None)
    out = _finish(calls, start, last)
    out.update(nudges=0, fm={}, source="calllog")
    return out


def _finish(calls: list[dict], prompt_ts, last_ts) -> dict:
    """Adds per call: container flags, parent (innermost enclosing agent-tool call), unc (uncached prompt
    tokens), comp (follows a compaction), tool_s (non-container tool seconds), end, lat (s since the previous
    call's last observation; fitting only)."""
    for c in calls:
        for tl in c["tools"]:
            tl["container"] = False
    intervals = []
    for i, c in enumerate(calls):
        for tl in c["tools"]:
            # an agent tool (AgentTool's function name is the sub-agent's name, never a harness tool) whose
            # interval holds other agents' calls; a harness tool's interval may hold a parallel branch's calls
            if tl["obs"] is not None and tl["ts"] is not None and tl["name"] not in HARNESS_TOOLS:
                inner = [j for j, d in enumerate(calls) if d["ts"] is not None and tl["ts"] < d["ts"] < tl["obs"]
                         and d["author"] != c["author"]]
                if inner:
                    tl["container"] = True
                    intervals.append((tl["ts"], tl["obs"], i, tl["name"]))
    for j, d in enumerate(calls):
        par = None
        for (a, b, i, name) in intervals:
            if d["ts"] is not None and a < d["ts"] < b and i != j:
                if par is None or (a >= par[0] and b <= par[1]):
                    par = (a, b, i, name)
        d["parent"] = None if par is None else (par[2], par[3])
    # per-stream prompt growth and compaction; a stream restarts when its parent container changes
    prev_pt: dict = {}
    prev_parent: dict = {}
    for d in calls:
        key = d["author"]
        if prev_parent.get(key, "unset") != d["parent"]:
            prev_pt[key] = 0
        prev_parent[key] = d["parent"]
        pp = prev_pt.get(key, 0)
        d["comp"] = bool(pp and d["pt"] < COMPACTION_DROP * pp)
        d["unc"] = 0 if d["comp"] else max(0, d["pt"] - pp)
        prev_pt[key] = d["pt"]
    ref = prompt_ts
    opaque = 0.0
    for d in calls:
        tool_s = 0.0
        end = d["ts"]
        for tl in d["tools"]:
            if tl["obs"] is None or tl["ts"] is None:
                continue
            end = max(end or tl["obs"], tl["obs"])
            if not tl["container"]:
                dt = max(0.0, tl["obs"] - tl["ts"])
                tool_s += dt
                if tl["name"] not in HARNESS_TOOLS and dt > 30:
                    opaque += dt
        d["tool_s"] = tool_s
        d["end"] = end
        d["lat"] = (d["ts"] - ref) if (ref is not None and d["ts"] is not None) else None
        if not any(tl["container"] for tl in d["tools"]):
            ref = end if end is not None else d["ts"]
        else:
            ref = d["ts"]
    agent_s = (last_ts - prompt_ts) if (last_ts is not None and prompt_ts is not None) else None
    return {"calls": calls, "agent_s": agent_s, "prompt_ts": prompt_ts, "opaque_tool_s": round(opaque, 1)}


def concurrent_groups(calls: list[dict]) -> list[list[str]]:
    """Authors that ran at the same time: same parent container, overlapping [first ts, last end] ranges."""
    rng: dict = {}
    for d in calls:
        if d["ts"] is None:
            continue
        k = (d["author"], d["parent"])
        a, b = rng.get(k, (d["ts"], d["end"] or d["ts"]))
        rng[k] = (min(a, d["ts"]), max(b, d["end"] or d["ts"]))
    keys = list(rng)
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            k = parent[k]
        return k
    for i, x in enumerate(keys):
        for y in keys[i + 1:]:
            if x[1] != y[1]:
                continue
            (a1, b1), (a2, b2) = rng[x], rng[y]
            ov = min(b1, b2) - max(a1, a2)
            short = max(1e-6, min(b1 - a1, b2 - a2))
            if ov > 0 and ov / short > 0.3:
                parent[find(x)] = find(y)
    groups: dict = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    return [g for g in groups.values() if len(g) > 1]


# ------------------------------------------------------------------ prediction

def call_cost(d: dict, c: dict) -> float:
    s = c["per_call"] + c["per_token"] * d["ct"] + c["per_kuncached"] * d["unc"] / 1000.0
    return s + (c["per_compaction"] if d["comp"] else 0.0)


def predict_trace(tr: dict, consts: dict | None = None, cap: float | None = DEFAULT_CAP_S) -> dict:
    c = dict(CONSTS, **(consts or {}))
    calls = tr["calls"]
    groups = concurrent_groups(calls)
    in_group = {k: gi for gi, g in enumerate(groups) for k in g}
    # walk calls in time order; serial calls add, a concurrent group adds max(stream sums) x slowdown once
    # (charged when the group's last call is reached, so the cap check stays approximately in order)
    order = sorted(range(len(calls)), key=lambda i: (calls[i]["ts"] is None, calls[i]["ts"] or 0))
    gsum: dict = {}
    glast = {}
    for i in order:
        k = (calls[i]["author"], calls[i]["parent"])
        if k in in_group:
            glast[in_group[k]] = i
    t = c["per_task"]
    llm = 0.0
    tools = 0.0
    timeout = False
    n_used = 0
    for i in order:
        d = calls[i]
        k = (d["author"], d["parent"])
        cost = call_cost(d, c)
        add = 0.0
        if k in in_group:
            gi = in_group[k]
            gsum.setdefault(gi, {}).setdefault(k, 0.0)
            gsum[gi][k] += cost
            if glast[gi] == i:
                ks = len(groups[gi])
                add = max(gsum[gi].values()) * PARALLEL_SLOWDOWN.get(ks, 1.0 + 0.117 * (ks - 1))
        else:
            add = cost
        if cap is not None and t + add + d["tool_s"] > cap:
            llm += max(0.0, cap - t - d["tool_s"]) if add else 0.0
            tools += min(d["tool_s"], max(0.0, cap - t))
            t = cap
            timeout = True
            break
        llm += add
        tools += d["tool_s"]
        t += add + d["tool_s"]
        n_used += 1
    by_author: dict = {}
    for d in calls:
        a = by_author.setdefault(d["author"] or "?", {"calls": 0, "ct": 0})
        a["calls"] += 1
        a["ct"] += d["ct"]
    return {"pred_agent_s": round(t, 1), "pred_llm_s": round(llm, 1), "pred_tool_s": round(tools, 1),
            "timeout": timeout, "n_calls": len(calls), "ct": sum(d["ct"] for d in calls),
            "kunc": round(sum(d["unc"] for d in calls) / 1000.0, 1), "n_comp": sum(d["comp"] for d in calls),
            "parallel_groups": [[a for a, _ in g] for g in groups], "by_author": by_author,
            "opaque_tool_s": tr.get("opaque_tool_s", 0.0), "nudges": tr.get("nudges", 0)}


# averages of v29 lab traces, used when a row has no trace (vc_* counters only)
FALLBACK_PER_CALL = {"kunc": 1.05, "comp": 0.04}


def predict_row(r: dict, consts: dict | None = None, use_cap: bool = True, overhead: str = "measured") -> dict:
    """Prediction for one results.jsonl row (with _trace/_cap from load_rows)."""
    c = dict(CONSTS, **(consts or {}))
    cap = r.get("_cap", DEFAULT_CAP_S) if use_cap else None
    out = {"run": r.get("_run"), "bundle": r.get("bundle"), "id": r.get("id"), "replicate": r.get("replicate"),
           "clock": r.get("clock") or "real", "task_s": r.get("task_seconds")}
    tr = None
    for key, fn in (("_calllog", parse_calllog), ("_trace", parse_trace)):
        if tr is None and r.get(key):
            try:
                tr = fn(r[key])
            except Exception as exc:  # noqa: BLE001
                out["trace_error"] = str(exc)[:200]
    if tr is not None and tr.get("warning"):
        out["warning"] = tr["warning"]
    if tr is not None and tr["calls"]:
        out.update(predict_trace(tr, c, cap))
        meas_agent = tr["agent_s"]
        out["source"] = tr.get("source", "trace")
    elif r.get("vc_llm_calls"):
        n, ct, tool = int(r["vc_llm_calls"]), int(r.get("vc_completion_tokens") or 0), float(r.get("vc_tool_seconds") or 0)
        llm = n * (c["per_call"] + c["per_kuncached"] * FALLBACK_PER_CALL["kunc"]
                   + c["per_compaction"] * FALLBACK_PER_CALL["comp"]) + c["per_token"] * ct
        t = c["per_task"] + llm + tool
        out.update(pred_agent_s=round(min(t, cap) if cap else t, 1), pred_llm_s=round(llm, 1), pred_tool_s=round(tool, 1),
                   timeout=bool(cap and t > cap), n_calls=n, ct=ct, source="vc_counters")
        meas_agent = r.get("real_agent_seconds")
    else:
        out.update(pred_agent_s=None, source="none")
        return out
    if r.get("clock") in (None, "real") and meas_agent is None:
        meas_agent = r.get("real_agent_seconds")
    out["meas_agent_s"] = round(meas_agent, 1) if meas_agent is not None else None
    real_agent = r.get("real_agent_seconds") if r.get("real_agent_seconds") is not None else meas_agent
    if r.get("task_seconds") is not None and real_agent is not None:
        out["non_agent_s"] = round(max(0.0, r["task_seconds"] - real_agent), 1)
    if overhead.startswith("fixed:"):
        out["non_agent_s"] = float(overhead.split(":", 1)[1])
    if out.get("non_agent_s") is not None:
        out["pred_task_s"] = round(out["pred_agent_s"] + out["non_agent_s"], 1)
    return out


# ------------------------------------------------------------------ fitting

def fit(rows: list[dict]) -> tuple[dict, dict]:
    """Least squares on normal steps of sequential real-clock traces: lat = a + b ct + d kunc; compaction excess
    = mean(lat - a - b ct) on compaction steps; per_task = mean residual of agent seconds."""
    import numpy as np
    X, y, comp_ex, traces = [], [], [], []
    for r in rows:
        if r.get("clock") not in (None, "real") or not r.get("_trace"):
            continue
        tr = parse_trace(r["_trace"])
        traces.append(tr)
        for d in tr["calls"]:
            if d["lat"] is None or d["parent"] is not None:
                continue
            if d["comp"]:
                comp_ex.append((d["lat"], d["ct"]))
            elif 0 < d["lat"] < 400:
                X.append([1.0, d["ct"], d["unc"] / 1000.0])
                y.append(d["lat"])
    if len(y) < 20:
        raise SystemExit("too few real-clock steps to fit (need sequential real-clock runs, e.g. lab17a/b)")
    A, Y = np.array(X), np.array(y)
    coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
    rmse = float(np.sqrt(np.mean((Y - A @ coef) ** 2)))
    c = dict(CONSTS, per_call=round(float(coef[0]), 3), per_token=round(float(coef[1]), 5),
             per_kuncached=round(float(coef[2]), 3))
    if comp_ex:
        c["per_compaction"] = round(float(np.mean([lat - c["per_call"] - c["per_token"] * ct for lat, ct in comp_ex])), 1)
    c["per_task"] = 0.0
    res = []
    for tr in traces:
        if tr["agent_s"] is None:
            continue
        p = predict_trace(tr, c, None)
        res.append(tr["agent_s"] - p["pred_agent_s"])
    c["per_task"] = round(float(np.mean(res)), 2) if res else 0.0
    return c, {"n_steps": len(y), "rmse_step_s": round(rmse, 2), "n_compactions": len(comp_ex), "n_tasks": len(res)}


# ------------------------------------------------------------------ reporting

def pct(xs: list, q: float):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summarize(preds: list[dict], key=lambda p: (p["run"], p["bundle"])) -> list[dict]:
    groups: dict = {}
    for p in preds:
        groups.setdefault(key(p), []).append(p)
    out = []
    for k, ps in sorted(groups.items(), key=lambda kv: str(kv[0])):
        ok = [p for p in ps if p.get("pred_agent_s") is not None]
        tot = [p["pred_task_s"] for p in ok if p.get("pred_task_s") is not None]
        meas = [p["task_s"] for p in ok if p.get("task_s") is not None and p.get("pred_task_s") is not None]
        out.append({"group": k, "n": len(ps), "n_pred": len(ok),
                    "pred_agent_mean": _mean([p["pred_agent_s"] for p in ok]),
                    "meas_agent_mean": _mean([p.get("meas_agent_s") for p in ok if p.get("clock") == "real"]),
                    "pred_task_mean": _mean(tot), "meas_task_mean": _mean(meas) if all(p.get("clock") == "real" for p in ok) else None,
                    "p50": pct(tot, .5), "p90": pct(tot, .9), "p95": pct(tot, .95),
                    "timeouts": sum(bool(p.get("timeout")) for p in ok),
                    "compactions": _mean([p.get("n_comp") for p in ok]), "calls": _mean([p.get("n_calls") for p in ok]),
                    "ct": _mean([p.get("ct") for p in ok])})
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 1) if xs else None


def project_hours(mean_task_s: float, n_tasks: int = 120, startup_s: float = 500.0) -> float:
    return (startup_s + n_tasks * mean_task_s) / 3600.0


def print_table(summ: list[dict], n_tasks: int, startup: float, file=sys.stdout) -> None:
    print(f"{'run':<12} {'bundle':<10} {'n':>3} {'pred_agent':>10} {'meas_agent':>10} {'pred_task':>9} {'meas_task':>9} "
          f"{'err%':>6} {'p50':>6} {'p90':>6} {'p95':>6} {'t/o':>4} {'comp':>5} {'calls':>5} {'ctok':>6} {'h@' + str(n_tasks):>6}",
          file=file)
    for s in summ:
        run, b = s["group"] if isinstance(s["group"], tuple) else (s["group"], "")
        err = (100.0 * (s["pred_task_mean"] - s["meas_task_mean"]) / s["meas_task_mean"]) \
            if s.get("meas_task_mean") and s.get("pred_task_mean") else None
        hours = project_hours(s["pred_task_mean"], n_tasks, startup) if s["pred_task_mean"] else None
        f = lambda v, w=6, d=1: (f"{v:>{w}.{d}f}" if isinstance(v, (int, float)) else f"{'-':>{w}}")  # noqa: E731
        print(f"{str(run)[:12]:<12} {str(b)[:10]:<10} {s['n']:>3} {f(s['pred_agent_mean'], 10)} {f(s['meas_agent_mean'], 10)} "
              f"{f(s['pred_task_mean'], 9)} {f(s['meas_task_mean'], 9)} {f(err, 6)} {f(s['p50'])} {f(s['p90'])} {f(s['p95'])} "
              f"{s['timeouts']:>4} {f(s['compactions'], 5, 2)} {f(s['calls'], 5)} {f(s['ct'], 6, 0)} {f(hours, 6, 2)}", file=file)


def paired_ratio(preds: list[dict], ref: str) -> list[tuple]:
    """(run, bundle, n paired, mean pred task s, ref mean on the same tasks, ratio) against bundle `ref`."""
    by: dict = {}
    for p in preds:
        if p.get("pred_task_s") is not None:
            by.setdefault((p["run"], p["bundle"]), {})[(p["id"], p.get("replicate"))] = p["pred_task_s"]
    refs = {k: v for k, v in by.items() if k[1] == ref}
    ref_all: dict = {}
    for v in refs.values():
        for (tid, _), s in v.items():
            ref_all.setdefault(tid, []).append(s)
    out = []
    for (run, b), v in sorted(by.items()):
        if b == ref:
            continue
        same_run = refs.get((run, ref))
        pairs = []
        for (tid, rep), s in v.items():
            if same_run and (tid, rep) in same_run:
                pairs.append((s, same_run[(tid, rep)]))
            elif not same_run and tid in ref_all:
                pairs.append((s, statistics.mean(ref_all[tid])))
        if pairs:
            a, bb = statistics.mean(x for x, _ in pairs), statistics.mean(y for _, y in pairs)
            out.append((run, b, len(pairs), round(a, 1), round(bb, 1), round(a / bb, 3)))
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="kernel output dirs / lab dirs / results.jsonl files")
    ap.add_argument("--fit", action="store_true", help="refit the constants on the real-clock runs given and validate")
    ap.add_argument("--consts", default=None, help="JSON dict overriding constants (per_call, per_token, ...)")
    ap.add_argument("--no-cap", action="store_true", help="do not cap agent time at max_time_minutes")
    ap.add_argument("--overhead", default="measured", help="'measured' (task_s - real agent s) or fixed:SECONDS")
    ap.add_argument("--ref", default="v29", help="bundle to compare against (paired by task)")
    ap.add_argument("--n-tasks", type=int, default=120, help="tasks in the projected scorer run")
    ap.add_argument("--startup", type=float, default=500.0, help="s before the first task (wheelhouse + vLLM)")
    ap.add_argument("--per-task", action="store_true", help="print one line per task-run")
    ap.add_argument("--json", default=None, help="write per task-run predictions (jsonl)")
    a = ap.parse_args(argv)
    consts = dict(CONSTS, **(json.loads(a.consts) if a.consts else {}))
    rows = [r for path in a.runs for r in load_rows(path)]
    if a.fit:
        c, info = fit(rows)
        print("fitted:", json.dumps(c), info)
        consts = c
        groups = sorted({(r["_run"], r["bundle"]) for r in rows if r.get("clock") in (None, "real")})
        print("\nleave-one-kernel-out (fit on the other kernels, predict this one):")
        for run in sorted({g[0] for g in groups}):
            train = [r for r in rows if r["_run"] != run]
            if not any(r.get("clock") in (None, "real") for r in train):
                continue
            cl, _ = fit(train)
            preds = [predict_row(r, cl, not a.no_cap, a.overhead) for r in rows if r["_run"] == run]
            print_table(summarize(preds), a.n_tasks, a.startup)
        print("\nin-sample:")
    preds = [predict_row(r, consts, not a.no_cap, a.overhead) for r in rows]
    print_table(summarize(preds), a.n_tasks, a.startup)
    rr = paired_ratio(preds, a.ref)
    if rr:
        print(f"\npaired against {a.ref} (same run when it has {a.ref}, else mean of {a.ref} over the runs given):")
        for run, b, n, x, y, ratio in rr:
            print(f"  {run:<12} {b:<10} n={n:<3} pred {x:7.1f} s vs {a.ref} {y:7.1f} s  ratio {ratio:.3f}")
    if a.per_task:
        print()
        for p in preds:
            print(json.dumps({k: p.get(k) for k in ("run", "bundle", "replicate", "id", "clock", "pred_agent_s", "meas_agent_s",
                                                   "pred_task_s", "task_s", "n_calls", "ct", "kunc", "n_comp", "pred_tool_s",
                                                   "timeout", "parallel_groups", "opaque_tool_s")}))
    if a.json:
        with open(a.json, "w") as fh:
            for p in preds:
                fh.write(json.dumps(p) + "\n")
    print(f"\nconstants: {json.dumps(consts)}; h@{a.n_tasks} = ({a.startup:.0f} s startup + {a.n_tasks} x mean pred_task) / 3600")


if __name__ == "__main__":
    main()
