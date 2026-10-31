"""Solve counts, paired comparisons and a mechanism dashboard for lab runs.

    python stats.py RUN [RUN ...] [--graded FILE ...] [--tasks tasks.jsonl] [--subset NAME=@ids.txt ...]
                    [--ref v29 | --pair A,B ...] [--split-runs] [--empty-fails] [--boot 10000] [--json out.json]

RUN is a kernel output dir (lab/results.jsonl inside), a lab/ dir, or a results.jsonl. Graded files (localeval
regrades: the kernel row plus local_resolved) are picked up automatically as <RUN>_graded.jsonl next to the run
dir, or given with --graded; when a row has local_resolved it is used instead of resolved_kaggle_env
(--kernel-only to ignore them).

Arms: rows are grouped by bundle name, pooled over runs and replicates (the same bundle in two kernels on
different tasks is one arm over the union; on the same task the runs are repeats). --split-runs makes each
(run, bundle) its own arm "bundle@run".

Paired comparison of arms A and B on the tasks both ran:
  * solve counts, per-task solve rate pooled over repeats (mean of that task's runs);
  * exact McNemar (two-sided binomial on discordant pairs); with repeats, the k-th run of A on a task is paired
    with the k-th run of B on it (extra repeats unpaired);
  * paired bootstrap over tasks of the difference of pooled solve rates (percentile 95% CI, in points and
    tasks).

Mechanism dashboard per arm: empty-patch %, call-cap-hit % (tool_calls >= the bundle's max_tool_calls),
8-min timeout % (timepred: the scorer clock would reach max_time_minutes), context-overflow %, crash %,
% of non-empty patches touching >= 1 / all of the gold patch's non-test files (--tasks), post-submit LLM calls,
compactions, predicted real seconds p50/p90/p95 and projected hours for --n-tasks (timepred), and for two-attempt
bundles (rows with extra_patches, see make_lab.py --grade-extra-patches): A alone, B alone, oracle (A or B or
picked) and picked (the submitted patch).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import timepred  # noqa: E402

OVERFLOW_PAT = re.compile(r"context.?length|ContextWindowExceeded|maximum context|context window|too many tokens|"
                          r"exceeds the model|max_model_len", re.I)


# ------------------------------------------------------------------ loading

def graded_for(run: str) -> Path | None:
    p = Path(run)
    base = p.parent if p.is_file() else p
    if base.name == "lab":
        base = base.parent
    name = base.name[:-3] if base.name.endswith("out") else base.name
    for c in (base.parent / f"{name}_graded.jsonl", base.parent / f"{base.name}_graded.jsonl"):
        if c.is_file():
            return c
    return None


def _read_graded(path) -> dict:
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if "local_resolved" in r:  # keyed by the patch text: a regrade applies only to that exact patch
                out[(r.get("bundle"), r.get("id"), _h(r.get("patch")))] = bool(r["local_resolved"])
    return out


def load(runs: list[str], graded: list[str], kernel_only: bool = False) -> list[dict]:
    """Rows of all runs with _resolved. Graded rows (local_resolved) replace the in-kernel verdict when bundle, id
    and patch text match: <RUN>_graded.jsonl applies to its own run, --graded FILE to every run, --graded
    LABEL=FILE to the run with that label (the run dir's name)."""
    glob_map: dict = {}
    run_maps: dict = {}
    if not kernel_only:
        for g in graded:
            if "=" in g and not Path(g).is_file():
                label, path = g.split("=", 1)
                run_maps.setdefault(label, {}).update(_read_graded(path))
            else:
                glob_map.update(_read_graded(g))
    rows = []
    for run in runs:
        rmap = dict(glob_map)
        gf = None if kernel_only else graded_for(run)
        if gf is not None:
            rmap.update(_read_graded(gf))
        for r in timepred.load_rows(run):
            m = dict(rmap, **run_maps.get(r["_run"], {}))
            key = (r.get("bundle"), r.get("id"), _h(r.get("patch")))
            if key in m:
                r["_resolved"], r["_graded"] = m[key], True
            else:
                r["_resolved"], r["_graded"] = bool(r.get("resolved_kaggle_env")), False
            rows.append(r)
    return rows


def _h(text) -> str:
    import hashlib
    return hashlib.sha1((text or "").encode("utf-8", "replace")).hexdigest()


def gold_files(tasks_path: str | None) -> dict:
    if not tasks_path:
        return {}
    out = {}
    for line in Path(tasks_path).read_text().splitlines():
        if line.strip():
            t = json.loads(line)
            files = [f for f in timepred_patch_files(t.get("patch", "")) if not is_test_path(f)]
            out[t["instance_id"]] = files
    return out


def timepred_patch_files(patch: str) -> list:
    """Files a unified diff touches: 'diff --git a/X b/Y' headers, else '+++ b/Y' (or '--- a/X' when deleted)."""
    out = [m.group(2) for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)", patch or "", re.M)]
    if not out:
        minus = None
        for line in (patch or "").splitlines():
            if line.startswith("--- "):
                minus = line[4:].split("\t")[0].strip()
            elif line.startswith("+++ "):
                plus = line[4:].split("\t")[0].strip()
                f = plus if plus != "/dev/null" else (minus or "")
                f = f[2:] if f.startswith(("a/", "b/")) else f
                if f and f != "/dev/null":
                    out.append(f)
    return list(dict.fromkeys(out))


def is_test_path(f: str) -> bool:
    parts = f.split("/")
    return any(p in ("tests", "test", "testing") for p in parts[:-1]) or parts[-1].startswith("test_") \
        or parts[-1].endswith("_test.py") or parts[-1] == "conftest.py"


def find_max_tool_calls(run: str, bundle: str) -> int | None:
    for info in timepred.find_runs(run):
        bd = info["bundles_dir"]
        if bd and (bd / bundle / "eval_config.yaml").is_file():
            m = re.search(r"max_tool_calls:\s*(\d+)", (bd / bundle / "eval_config.yaml").read_text())
            if m:
                return int(m.group(1))
    return None


# ------------------------------------------------------------------ statistics

def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p (binomial, p=0.5, on the b + c discordant pairs)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / 2.0 ** n
    return min(1.0, 2.0 * tail)


def paired(arm_a: dict, arm_b: dict, n_boot: int = 10000, seed: int = 0) -> dict:
    """arm: task -> [resolved bools in run order]."""
    tasks = sorted(set(arm_a) & set(arm_b))
    if not tasks:
        return {"n_tasks": 0}
    ra = {t: statistics.mean(arm_a[t]) for t in tasks}
    rb = {t: statistics.mean(arm_b[t]) for t in tasks}
    b = c = both = neither = 0
    for t in tasks:
        for x, y in zip(arm_a[t], arm_b[t]):
            if x and not y:
                b += 1
            elif y and not x:
                c += 1
            elif x and y:
                both += 1
            else:
                neither += 1
    d = [ra[t] - rb[t] for t in tasks]
    rng = random.Random(seed)
    n = len(tasks)
    boots = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += d[rng.randrange(n)]
        boots.append(s / n)
    boots.sort()
    lo, hi = boots[int(0.025 * n_boot)], boots[min(n_boot - 1, int(0.975 * n_boot))]
    mean_d = sum(d) / n
    return {"n_tasks": n, "solves_a": round(sum(ra.values()), 2), "solves_b": round(sum(rb.values()), 2),
            "diff_tasks": round(mean_d * n, 2), "diff_pts": round(100 * mean_d, 2),
            "ci95_pts": (round(100 * lo, 2), round(100 * hi, 2)), "ci95_tasks": (round(lo * n, 2), round(hi * n, 2)),
            "p_boot_le0": round(sum(1 for x in boots if x <= 0) / n_boot, 4),
            "a_only": b, "b_only": c, "both": both, "neither": neither, "mcnemar_p": round(mcnemar_exact(b, c), 4)}


def pct(x, n):
    return round(100.0 * x / n, 1) if n else None


# ------------------------------------------------------------------ dashboard

def arm_key(r: dict, split_runs: bool) -> str:
    return f"{r.get('bundle')}@{r.get('_run')}" if split_runs else str(r.get("bundle"))


def dashboard(rows: list[dict], preds: dict, gold: dict, max_calls: dict, n_tasks: int, startup: float) -> dict:
    n = len(rows)
    empty = sum(1 for r in rows if not (r.get("patch") or "").strip())
    crash = sum(1 for r in rows if str(r.get("error", "")).startswith("CRASH"))
    overflow = sum(1 for r in rows if OVERFLOW_PAT.search(str(r.get("error", ""))))
    cap_hit = 0
    cap_known = 0
    for r in rows:
        mc = max_calls.get((r.get("_run"), r.get("bundle")))
        if mc and r.get("tool_calls") is not None:
            cap_known += 1
            cap_hit += int(r["tool_calls"]) >= mc
    ps = [preds.get(id(r)) for r in rows]
    ps = [p for p in ps if p and p.get("pred_agent_s") is not None]
    tot = [p["pred_task_s"] for p in ps if p.get("pred_task_s") is not None]
    touch_any = touch_all = n_g = 0
    for r in rows:
        pf = timepred_patch_files(r.get("patch") or "")
        g = gold.get(r.get("id"))
        if pf and g:
            n_g += 1
            touch_any += bool(set(pf) & set(g))
            touch_all += set(g) <= set(pf)
    post = [p.get("post_submit_calls") for p in ps if p.get("post_submit_calls") is not None]
    out = {"n": n, "solved": sum(r["_resolved"] for r in rows), "solve_pct": pct(sum(r["_resolved"] for r in rows), n),
           "graded_rows": sum(r["_graded"] for r in rows),
           "empty_pct": pct(empty, n), "crash_pct": pct(crash, n), "overflow_pct": pct(overflow, n),
           "call_cap_pct": pct(cap_hit, cap_known) if cap_known else None,
           "timeout8_pct": pct(sum(bool(p.get("timeout")) for p in ps), len(ps)) if ps else None,
           "gold_touch_any_pct": pct(touch_any, n_g) if n_g else None,
           "gold_touch_all_pct": pct(touch_all, n_g) if n_g else None,
           "post_submit_calls": round(statistics.mean(post), 1) if post else None,
           "compactions": round(statistics.mean(p.get("n_comp", 0) for p in ps), 2) if ps else None,
           "calls": round(statistics.mean(p.get("n_calls", 0) for p in ps), 1) if ps else None,
           "ctok": round(statistics.mean(p.get("ct", 0) for p in ps)) if ps else None,
           "pred_p50": _r(timepred.pct(tot, .5)), "pred_p90": _r(timepred.pct(tot, .9)), "pred_p95": _r(timepred.pct(tot, .95)),
           "pred_mean": _r(statistics.mean(tot)) if tot else None,
           "hours_at_n": round(timepred.project_hours(statistics.mean(tot), n_tasks, startup), 2) if tot else None}
    two = [r for r in rows if isinstance(r.get("extra_patches"), dict) and r["extra_patches"]]
    if two:
        names = sorted({k for r in two for k in r["extra_patches"]})
        tw = {"n": len(two)}
        for k in names:
            tw[k] = sum(bool((r["extra_patches"].get(k) or {}).get("resolved")) for r in two)
            tw[k + "_empty"] = sum(not (r["extra_patches"].get(k) or {}).get("chars") for r in two)
        tw["oracle"] = sum(any(bool((r["extra_patches"].get(k) or {}).get("resolved")) for k in names) or r["_resolved"]
                           for r in two)
        tw["picked"] = sum(r["_resolved"] for r in two)
        out["two_attempt"] = tw
    return out


def _r(x):
    return round(x, 1) if isinstance(x, (int, float)) else None


def post_submit_calls(r: dict) -> int | None:
    """LLM calls after the first submit_patch call (call log when present, else the ATIF trace)."""
    try:
        if r.get("_calllog"):
            tr = timepred.parse_calllog(r["_calllog"])
        elif r.get("_trace"):
            tr = timepred.parse_trace(r["_trace"])
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    seen = False
    k = 0
    for d in tr["calls"]:
        if seen:
            k += 1
        if any(t["name"] == "submit_patch" for t in d["tools"]):
            seen = True
    return k


# ------------------------------------------------------------------ main

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--graded", nargs="*", default=[], help="graded jsonl files (rows with local_resolved)")
    ap.add_argument("--kernel-only", action="store_true", help="ignore graded files; use resolved_kaggle_env")
    ap.add_argument("--empty-fails", action="store_true", help="an empty patch never counts as solved")
    ap.add_argument("--tasks", default=None, help="tasks.jsonl with gold patches (for the gold-file metric)")
    ap.add_argument("--subset", nargs="*", default=[], help="NAME=@ids.txt (or NAME=id,id,...) breakdowns")
    ap.add_argument("--only", default=None, help="@ids.txt or id,id: restrict to these tasks")
    ap.add_argument("--split-runs", action="store_true", help="each (run, bundle) is its own arm bundle@run")
    ap.add_argument("--ref", default=None, help="compare every arm against this one")
    ap.add_argument("--pair", nargs="*", default=[], help="A,B arm pairs to compare (default: all pairs, <= 6 arms)")
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-tasks", type=int, default=120)
    ap.add_argument("--startup", type=float, default=500.0)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    def ids_of(spec: str) -> set:
        return set(Path(spec[1:]).read_text().split()) if spec.startswith("@") else set(spec.split(","))

    rows = load(a.runs, a.graded, a.kernel_only)
    if a.only:
        keep = ids_of(a.only)
        rows = [r for r in rows if r.get("id") in keep]
    if a.empty_fails:
        for r in rows:
            if not (r.get("patch") or "").strip():
                r["_resolved"] = False
    gold = gold_files(a.tasks)
    max_calls = {}
    for run in a.runs:
        for info in timepred.find_runs(run):
            for b in {r.get("bundle") for r in rows if r.get("_run") == info["label"]}:
                max_calls[(info["label"], b)] = find_max_tool_calls(run, b) or 28
    preds = {}
    for r in rows:
        p = timepred.predict_row(r)
        p["post_submit_calls"] = post_submit_calls(r)
        preds[id(r)] = p

    arms: dict = {}
    for r in rows:
        arms.setdefault(arm_key(r, a.split_runs), []).append(r)
    report: dict = {"arms": {}, "pairs": [], "subsets": {}}

    ng = sum(r["_graded"] for r in rows)
    print(f"SOLVES (resolved = local_resolved for the {ng} rows matched in a graded file by bundle+id+patch, else "
          "in-kernel resolved_kaggle_env" + ("; empty patch = fail" if a.empty_fails else "") + ")")
    print(f"{'arm':<22} {'runs':>4} {'tasks':>5} {'rows':>5} {'solved':>6} {'pooled':>7} {'rate%':>6}  per run")
    per_task: dict = {}
    for name, rs in sorted(arms.items()):
        pt: dict = {}
        for r in sorted(rs, key=lambda r: (r.get("_run"), r.get("replicate") or 0)):
            pt.setdefault(r["id"], []).append(bool(r["_resolved"]))
        per_task[name] = pt
        pooled = sum(statistics.mean(v) for v in pt.values())
        runs = {}
        for r in rs:
            k = f"{r.get('_run')}/r{r.get('replicate') or 0}"
            runs.setdefault(k, [0, 0])
            runs[k][0] += r["_resolved"]
            runs[k][1] += 1
        per_run = " ".join(f"{k}:{v[0]}/{v[1]}" for k, v in sorted(runs.items()))
        print(f"{name:<22} {len({r.get('_run') for r in rs}):>4} {len(pt):>5} {len(rs):>5} "
              f"{sum(r['_resolved'] for r in rs):>6} {pooled:>7.2f} {100 * pooled / max(1, len(pt)):>6.1f}  {per_run}")
        report["arms"][name] = {"tasks": len(pt), "rows": len(rs), "solved_rows": sum(r["_resolved"] for r in rs),
                                "pooled_solves": round(pooled, 2), "per_run": runs}

    for spec in a.subset:
        sname, ids = spec.split("=", 1)
        ids = ids_of(ids)
        print(f"\nsubset {sname} ({len(ids)} ids):")
        report["subsets"][sname] = {}
        for name, pt in sorted(per_task.items()):
            sub = {t: v for t, v in pt.items() if t in ids}
            s = sum(statistics.mean(v) for v in sub.values())
            print(f"  {name:<22} {s:6.2f} / {len(sub)}")
            report["subsets"][sname][name] = [round(s, 2), len(sub)]

    names = sorted(per_task)
    pairs = []
    if a.pair:
        pairs = [tuple(p.split(",", 1)) for p in a.pair]
    elif a.ref:
        pairs = [(x, a.ref) for x in names if x != a.ref]
    elif len(names) <= 6:
        pairs = [(x, y) for i, x in enumerate(names) for y in names[i + 1:]]
    if pairs:
        print("\nPAIRED (tasks both ran; pooled per-task rate; bootstrap over tasks; exact McNemar on run pairs)")
        print(f"{'A':<16} {'B':<16} {'tasks':>5} {'A':>6} {'B':>6} {'A-B':>6} {'95% CI (tasks)':>16} {'pts':>6} "
              f"{'95% CI (pts)':>15} {'A>B':>4} {'B>A':>4} {'McN p':>6} {'P(d<=0)':>7}")
        for x, y in pairs:
            if x not in per_task or y not in per_task:
                print(f"  unknown arm in pair {x},{y}; arms: {names}")
                continue
            res = paired(per_task[x], per_task[y], a.boot, a.seed)
            if not res["n_tasks"]:
                print(f"{x:<16} {y:<16} no common tasks")
                continue
            print(f"{x[:16]:<16} {y[:16]:<16} {res['n_tasks']:>5} {res['solves_a']:>6.1f} {res['solves_b']:>6.1f} "
                  f"{res['diff_tasks']:>+6.1f} {'[%+.1f, %+.1f]' % res['ci95_tasks']:>16} {res['diff_pts']:>+6.1f} "
                  f"{'[%+.1f, %+.1f]' % res['ci95_pts']:>15} {res['a_only']:>4} {res['b_only']:>4} {res['mcnemar_p']:>6.3f} "
                  f"{res['p_boot_le0']:>7.3f}")
            report["pairs"].append(dict(a=x, b=y, **res))

    print("\nMECHANISMS (timepred: predicted scorer seconds per task, 8-min timeouts; gold = non-test files of the"
          " reference patch" + ("" if gold else ", needs --tasks") + ")")
    hdr = (f"{'arm':<22} {'n':>4} {'solve%':>6} {'empty%':>6} {'cap%':>5} {'8min%':>5} {'ovfl%':>5} {'crash%':>6} "
           f"{'gold1%':>6} {'goldA%':>6} {'post':>5} {'comp':>5} {'calls':>5} {'ctok':>6} {'p50':>6} {'p90':>6} "
           f"{'p95':>6} {'mean':>6} {'h@%d' % a.n_tasks:>6}")
    print(hdr)
    two_any = False
    for name, rs in sorted(arms.items()):
        d = dashboard(rs, preds, gold, max_calls, a.n_tasks, a.startup)
        report["arms"][name]["mechanisms"] = d
        f = lambda v, w=6, dd=1: (f"{v:>{w}.{dd}f}" if isinstance(v, (int, float)) else f"{'-':>{w}}")  # noqa: E731
        print(f"{name[:22]:<22} {d['n']:>4} {f(d['solve_pct'])} {f(d['empty_pct'])} {f(d['call_cap_pct'], 5)} "
              f"{f(d['timeout8_pct'], 5)} {f(d['overflow_pct'], 5)} {f(d['crash_pct'])} {f(d['gold_touch_any_pct'])} "
              f"{f(d['gold_touch_all_pct'])} {f(d['post_submit_calls'], 5)} {f(d['compactions'], 5, 2)} {f(d['calls'], 5)} "
              f"{f(d['ctok'], 6, 0)} {f(d['pred_p50'])} {f(d['pred_p90'])} {f(d['pred_p95'])} {f(d['pred_mean'])} "
              f"{f(d['hours_at_n'], 6, 2)}")
        two_any = two_any or "two_attempt" in d
    if two_any:
        print("\nTWO-ATTEMPT (extra_patches graded in-kernel; oracle = any attempt or the picked patch solves)")
        for name in sorted(arms):
            tw = report["arms"][name]["mechanisms"].get("two_attempt")
            if tw:
                print(f"  {name:<22} " + " ".join(f"{k}={v}" for k, v in tw.items()))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
