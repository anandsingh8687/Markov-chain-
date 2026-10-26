"""Tables for the paper from data/outcomes.csv, data/lb.csv and the eval-set metadata (stdlib only).

Usage: python analysis.py [--meta tasks_meta.jsonl]
"""
import argparse
import collections
import csv
import json
import math
import random
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
R = list(csv.DictReader(open(HERE / "data" / "outcomes.csv")))
for r in R:
    r["resolved"] = int(r["resolved"])


def mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def arm(lab_bundles, exclude_hang=True, no_interface=True):
    """task_id -> resolved for the given (lab, bundle) pairs (union over labs)."""
    out = {}
    for r in R:
        if (r["lab"], r["bundle"]) in lab_bundles:
            if exclude_hang and r["outcome"] == "server_hang":
                continue
            if no_interface and r["interface_task"] == "1":
                continue
            out[r["task_id"]] = r["resolved"]
    return out


def paired(a, b, n_boot=10000, seed=0):
    ids = sorted(set(a) & set(b))
    sa, sb = sum(a[i] for i in ids), sum(b[i] for i in ids)
    only_a = sum(a[i] and not b[i] for i in ids)
    only_b = sum(b[i] and not a[i] for i in ids)
    rnd = random.Random(seed)
    d = []
    for _ in range(n_boot):
        s = [rnd.choice(ids) for _ in ids]
        d.append(sum(b[i] - a[i] for i in s))
    d.sort()
    return dict(n=len(ids), a=sa, b=sb, only_a=only_a, only_b=only_b, p=mcnemar(only_a, only_b),
                lo=d[int(0.025 * n_boot)], hi=d[int(0.975 * n_boot) - 1])


GATES = [  # (question, baseline arm, candidate arm)
    ("thinking 2048 + terse thoughts (v30) vs v29, eval set", {("lab20a", "v29"), ("lab20b", "v29")}, {("lab20a", "v30"), ("lab20b", "v30")}),
    ("eval-set-derived prompt (v32) vs v29, eval set", {("lab20a", "v29")}, {("lab21", "v32")}),
    ("T 1.0 / top_k 64 (v33t) vs T 0.2 (v29), split A", {("lab22a", "v29"), ("lab22b", "v29")}, {("lab22a", "v33t"), ("lab22b", "v33t")}),
    ("thinking 2048 + 32 calls (v34) vs v33t, sealed split B", {("lab24", "v33t")}, {("lab24", "v34")}),
    ("E4B (s1) vs 31B v29, split A (pre-hang tasks)", {("lab22a", "v29"), ("lab22b", "v29")}, {("lab23", "s1")}),
    ("E4B 40 calls (s2) vs 28 calls (s1)", {("lab23", "s1")}, {("lab23", "s2")}),
    ("v30 vs v29, older public-repo dev set (lab 18)", {("lab18a", "v29"), ("lab18b", "v29")}, {("lab18a", "v30"), ("lab18b", "v30")}),
]


def table_gates():
    print("\n## Paired gates (interface-dependent tasks and server-hang runs excluded)\n")
    print("| Question | n | base | cand | base-only | cand-only | Δ tasks (95% CI) | McNemar p |")
    print("|---|---|---|---|---|---|---|---|")
    for q, A, B in GATES:
        s = paired(arm(A), arm(B))
        print(f"| {q} | {s['n']} | {s['a']} | {s['b']} | {s['only_a']} | {s['only_b']} | "
              f"{s['b'] - s['a']:+d} ({s['lo']:+d}..{s['hi']:+d}) | {s['p']:.2f} |")


def table_mix():
    print("\n## Outcome mix per arm (eval set, interface tasks excluded)\n")
    keys = ["solved", "wrong", "empty", "timeout", "turn_limit"]
    groups = collections.defaultdict(collections.Counter)
    tok = collections.defaultdict(list)
    for r in R:
        if r["task_set"] != "evalset" or r["interface_task"] == "1" or r["outcome"] == "server_hang":
            continue
        g = (r["bundle"], {"lab20a": "A", "lab20b": "A", "lab21": "A", "lab22a": "A", "lab22b": "A",
                           "lab23": "A", "lab24": "B"}[r["lab"]], r["lab"][:5])
        groups[g][r["outcome"]] += 1
        if r["completion_tokens"]:
            tok[g].append(float(r["completion_tokens"]))
    print("| arm | split | lab | n | " + " | ".join(keys) + " | completion tokens/task |")
    print("|---|---|---|---|" + "---|" * len(keys) + "---|")
    for g in sorted(groups):
        c = groups[g]
        n = sum(c.values())
        print(f"| {g[0]} | {g[1]} | {g[2]} | {n} | " + " | ".join(str(c[k]) for k in keys)
              + f" | {statistics.mean(tok[g]):.0f} |" if tok[g] else " | |")


def table_calibration():
    lb = list(csv.DictReader(open(HERE / "data" / "lb.csv")))
    draws = collections.defaultdict(list)
    for x in lb:
        if x["public_score"]:
            draws[x["bundle"]].append(float(x["public_score"]))
    pooled = collections.defaultdict(lambda: [0, 0])
    for r in R:
        if r["task_set"] == "evalset" and r["interface_task"] != "1" and r["outcome"] != "server_hang":
            pooled[r["bundle"]][0] += r["resolved"]
            pooled[r["bundle"]][1] += 1
    print("\n## Eval set vs public leaderboard (58 tasks)\n")
    print("| bundle | eval solved / runs | eval rate | LB draws | LB mean | ratio LB/eval |")
    print("|---|---|---|---|---|---|")
    for b in ["v29", "v30", "v32", "v33t", "v34", "s1", "s2"]:
        s, n = pooled[b]
        d = draws.get(b, [])
        lbm = statistics.mean(d) if d else None
        rate = s / n if n else 0
        print(f"| {b} | {s}/{n} | {rate:.2f} | {', '.join(f'{x:.2f}' for x in d) or '-'} | "
              f"{lbm:.3f} | {lbm / rate:.2f} |" if d else f"| {b} | {s}/{n} | {rate:.2f} | - | - | - |")


def table_power():
    """Minimum detectable difference for a paired gate: exact McNemar, alpha 0.05, power 0.8,
    discordance rate from the measured gates."""
    print("\n## Power of a paired gate (alpha 0.05 two-sided, power 0.8)\n")
    disc = []
    for _, A, B in GATES[:4]:
        s = paired(arm(A), arm(B), n_boot=1)
        disc.append((s["only_a"] + s["only_b"]) / s["n"])
    q = statistics.mean(disc)
    print(f"mean discordance per task across 31B gates: {q:.3f}")
    rnd = random.Random(1)
    print("| tasks n | detectable gain (points, 80% power) |")
    print("|---|---|")
    for n in [24, 48, 87, 155, 300, 600]:
        found = False
        for gain in [x / 100 for x in range(1, 41)]:
            # P(cand-only) = (q + gain)/2, P(base-only) = (q - gain)/2
            pb, pa = (q + gain) / 2, (q - gain) / 2
            if pa < 0:
                break
            hits = 0
            sims = 400
            for _ in range(sims):
                b = c = 0
                for _ in range(n):
                    u = rnd.random()
                    if u < pb:
                        c += 1
                    elif u < pb + pa:
                        b += 1
                hits += mcnemar(b, c) < 0.05 and c > b
            if hits / sims >= 0.8:
                print(f"| {n} | {100 * gain:.0f} |")
                found = True
                break
        if not found:
            print(f"| {n} | none: 80% power not reached even when every discordant task favours the candidate |")


def patch_lines(patch):
    """Changed lines (+/-) in non-test files of a unified diff."""
    n, test = 0, False
    for line in patch.splitlines():
        if line.startswith("diff --git"):
            f = line.split(" b/")[-1]
            test = "test" in f.lower().split("/")[-1] or "/tests/" in f or f.startswith("tests/")
        elif not test and line[:1] in "+-" and not line.startswith(("+++", "---")):
            n += 1
    return n


def table_profile(meta_path):
    M = [json.loads(l) for l in open(meta_path)]
    T = {json.loads(l)["instance_id"]: json.loads(l) for l in open(Path(meta_path).with_name("tasks.jsonl"))}
    for m in M:
        m["gold_lines"] = patch_lines(T[m["instance_id"]]["patch"])
    print("\n## Eval set profile\n")
    num = lambda k: [float(m[k]) for m in M if m.get(k) not in (None, "None", "")]
    gl, nf = num("gold_lines"), num("n_files")
    f2p = [len(eval(m["FAIL_TO_PASS"])) if isinstance(m["FAIL_TO_PASS"], str) else len(m["FAIL_TO_PASS"]) for m in M]
    print(f"tasks {len(M)}, repos {len({m['repo'] for m in M})}, split A {sum(m['split'] == 'A' for m in M)} / "
          f"B {sum(m['split'] == 'B' for m in M)}")
    print(f"task dates {min(m['task_created_at'] for m in M)[:10]} .. {max(m['task_created_at'] for m in M)[:10]}")
    print(f"gold lines median {statistics.median(gl):.0f} (p25 {statistics.quantiles(gl, n=4)[0]:.0f}, "
          f"p75 {statistics.quantiles(gl, n=4)[2]:.0f}, max {max(gl):.0f}); files median {statistics.median(nf):.0f}, max {max(nf):.0f}")
    print(f"FAIL_TO_PASS tests per task median {statistics.median(f2p):.0f}")
    print("sources", dict(collections.Counter(m["dataset"] for m in M)))
    print("problem statement sources", dict(collections.Counter(m["ps_source"] for m in M)))
    print("licenses", dict(collections.Counter(m["license"] for m in M).most_common(8)))
    stars = num("repo_stars")
    print(f"repo stars median {statistics.median(stars):.0f}, p90 {statistics.quantiles(stars, n=10)[8]:.0f}")
    print(f"snapshot MB total {sum(num('snapshot_mb')):.0f}, wheels MB total {sum(num('wheels_mb')):.0f}")
    print(f"gold verification seconds median {statistics.median(num('gold_seconds_max')):.0f}")
    # difficulty vs solve rate of the 31B arms
    solved = collections.defaultdict(list)
    for r in R:
        if r["task_set"] == "evalset" and r["model"] == "31b":
            solved[r["task_id"]].append(r["resolved"])
    bins = [(0, 10), (11, 30), (31, 80), (81, 10 ** 6)]
    print("| gold lines | tasks | 31B solve rate (all runs) |")
    print("|---|---|---|")
    for lo, hi in bins:
        ids = [m["instance_id"] for m in M if m.get("gold_lines") not in (None, "None")
               and lo <= float(m["gold_lines"]) <= hi and m["instance_id"] in solved]
        runs = [x for i in ids for x in solved[i]]
        print(f"| {lo}-{hi if hi < 10 ** 6 else ''} | {len(ids)} | {sum(runs) / len(runs):.2f} ({sum(runs)}/{len(runs)}) |")
    ever = sum(any(v) for v in solved.values())
    print(f"tasks solved by at least one 31B run: {ever}/{len(solved)}; never solved: {len(solved) - ever}")


def table_compaction(trace_root):
    """First history compaction vs first edit in v33t runs (needs the trajectories)."""
    import glob
    res = {(r["lab"], r["task_id"]): r["resolved"] for r in R if r["bundle"] == "v33t"}
    c = collections.Counter()
    for lab in ("lab22a", "lab22b", "lab24"):
        for f in glob.glob(f"{trace_root}/{lab}/v33t/*.json") + glob.glob(f"{trace_root}/{lab}out/lab/v33t/r0/traces/*.json"):
            tid = Path(f).stem.replace("trace_", "")
            d = json.load(open(f))
            prev = comp = edit = None
            k = 0
            for st in d["steps"]:
                pt = (st.get("metrics") or {}).get("prompt_tokens")
                if pt:
                    k += 1
                    if prev and pt < 0.7 * prev and comp is None:
                        comp = k
                    prev = pt
                for t in st.get("tool_calls") or []:
                    if t.get("function_name") in ("edit_file", "write_file") and edit is None:
                        edit = k
            key = ("no compaction" if comp is None else "compaction, never edited" if edit is None
                   else "compaction before first edit" if comp < edit else "first edit before compaction")
            c[key, res.get((lab, tid), 0)] += 1
    print("\n## v33t: first compaction vs first edit\n")
    print("| order | runs | solved |")
    print("|---|---|---|")
    for key in ("no compaction", "first edit before compaction", "compaction before first edit", "compaction, never edited"):
        n = c[key, 0] + c[key, 1]
        print(f"| {key} | {n} | {c[key, 1]} |")


ap = argparse.ArgumentParser()
ap.add_argument("--meta")
ap.add_argument("--traces", help="trajectory root (traces/<lab>/<bundle>/*.json or <lab>out/lab/...)")
a = ap.parse_args()
table_gates()
table_mix()
table_calibration()
table_power()
if a.meta:
    table_profile(a.meta)
if a.traces:
    table_compaction(a.traces)
