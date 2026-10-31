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
_ap = argparse.ArgumentParser()
_ap.add_argument("--meta", help="tasks_meta.jsonl of the release (tasks.jsonl must sit next to it)")
_ap.add_argument("--data", default=str(HERE / "data"), help="directory holding outcomes.csv and lb.csv")
ARGS = _ap.parse_args()
DATA = Path(ARGS.data)
R = list(csv.DictReader(open(DATA / "outcomes.csv")))
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
    ("v30 vs v29, older public-repo dev set (lab 18, earlier 0.164 s + 22.1 ms/token clock)", {("lab18a", "v29"), ("lab18b", "v29")}, {("lab18a", "v30"), ("lab18b", "v30")}),
    ("A/A: v29 run twice on the same tasks (lab 20 -> lab 22)", {("lab20a", "v29"), ("lab20b", "v29")}, {("lab22a", "v29"), ("lab22b", "v29")}),
    ("A/A: v33t run twice on the same tasks (lab 22 -> lab 25)", {("lab22a", "v33t"), ("lab22b", "v33t")}, {("lab25a", "v33t"), ("lab25b", "v33t")}),
    ("issue kept in the instruction (v35) vs v33t, same kernel (lab 25)", {("lab25a", "v33t"), ("lab25b", "v33t")}, {("lab25a", "v35"), ("lab25b", "v35")}),
    ("v35 without read_file / graph tools (v36) vs v33t, same kernel (lab 25)", {("lab25a", "v33t"), ("lab25b", "v33t")}, {("lab25a", "v36"), ("lab25b", "v36")}),
    ("31B -> E4B as deployed: v33t (lab 25) vs s3 (lab 27, E4B clock), split A", {("lab25a", "v33t"), ("lab25b", "v33t")}, {("lab27", "s3")}),
    ("E4B temperature 0.3 (s4) vs 1.0 (s3), same kernel (lab 27)", {("lab27", "s3")}, {("lab27", "s4")}),
    ("T 1.0 (v33t) vs T 0.2 (v29), sealed split B, same kernel (lab 26)", {("lab26a", "v29"), ("lab26b", "v29")}, {("lab26a", "v33t"), ("lab26b", "v33t")}),
    ("T 1.0 (v33t) vs T 0.2 (v29), pooled split A (lab 22) + split B (lab 26)", {("lab22a", "v29"), ("lab22b", "v29"), ("lab26a", "v29"), ("lab26b", "v29")}, {("lab22a", "v33t"), ("lab22b", "v33t"), ("lab26a", "v33t"), ("lab26b", "v33t")}),
    ("A/A: v33t run twice on split B (lab 24 -> lab 26)", {("lab24", "v33t")}, {("lab26a", "v33t"), ("lab26b", "v33t")}),
    ("v36 vs v33t, sealed split B, same kernel (lab 26)", {("lab26a", "v33t"), ("lab26b", "v33t")}, {("lab26a", "v36"), ("lab26b", "v36")}),
    ("v36 vs v33t, pooled split A (lab 25) + split B (lab 26)", {("lab25a", "v33t"), ("lab25b", "v33t"), ("lab26a", "v33t"), ("lab26b", "v33t")}, {("lab25a", "v36"), ("lab25b", "v36"), ("lab26a", "v36"), ("lab26b", "v36")}),
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
                           "lab23": "A", "lab24": "B", "lab28s": "A", "lab25a": "A", "lab25b": "A", "lab27": "A",
                           "lab26a": "B", "lab26b": "B"}[r["lab"]], r["lab"][:5])
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


PRE25 = {"lab17a", "lab17b", "lab18a", "lab18b", "lab19", "lab20a", "lab20b", "lab21", "lab22a", "lab22b", "lab23", "lab24", "lab28s"}


def table_calibration():
    lb = list(csv.DictReader(open(DATA / "lb.csv")))
    draws = collections.defaultdict(list)
    for x in lb:
        if x["public_score"]:
            draws[x["bundle"]].append(float(x["public_score"]))
    pooled = collections.defaultdict(lambda: [0, 0])
    for r in R:  # analysis set fixed before lab 25 (the v35/v36 gate)
        if r["task_set"] == "evalset" and r["interface_task"] != "1" and r["outcome"] != "server_hang" and r["lab"] in PRE25:
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


def _binpmf(n, p):
    return [math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                     + k * math.log(p) + (n - k) * math.log(1 - p)) for k in range(n + 1)]


def mcnemar_power(n, d, g, alpha=0.05):
    """Exact power of a two-sided exact McNemar test on n paired tasks: each task is discordant with
    probability d, and a discordant task favours the candidate with probability (d + g) / (2d)."""
    q = (d + g) / (2 * d)
    if q > 1:
        return None
    power = 0.0
    for m, pm in enumerate(_binpmf(n, d)):
        if pm < 1e-12:
            continue
        crit = next((c for c in range(m // 2 + 1, m + 1) if mcnemar(m - c, c) < alpha), None)
        if crit is not None:
            power += pm * sum(_binpmf(m, q)[crit:]) if 0 < q < 1 else pm * (q == 1)
    return power


def table_power():
    """Smallest solve-rate gain detectable with 80% power, at the discordance measured between 31B variants."""
    print("\n## Power of a paired gate (exact McNemar, alpha 0.05 two-sided, power 0.8)\n")
    disc = []
    for _, A, B in GATES[:4]:
        s = paired(arm(A), arm(B), n_boot=1)
        disc.append((s["only_a"] + s["only_b"]) / s["n"])
    d = statistics.mean(disc)
    print(f"mean discordance per task across the four 31B gates: {d:.3f}; rule of thumb n ~ 8d/gain^2")
    print("| tasks n | detectable gain (points, 80% power) |")
    print("|---|---|")
    for n in [24, 48, 60, 87, 155, 300, 600]:
        found = None
        for gi in range(1, 41):
            pw = mcnemar_power(n, d, gi / 100)
            if pw is None:
                break
            if pw >= 0.8:
                found = gi
                break
        print(f"| {n} | {found if found else 'none: too few discordant tasks even if all favour the candidate'} |")

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
    print("licenses", dict(collections.Counter(m["license"] for m in M).most_common()))
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


def table_compaction(bundle="v33t"):
    """First history compaction vs first edit (outcomes.csv fields from the trajectories)."""
    c = collections.Counter()
    for r in R:
        if r["bundle"] != bundle or r["task_set"] != "evalset" or r["llm_steps"] in ("", "0") or r["lab"] not in PRE25:
            continue
        comp, edit = r["first_compaction_step"], r["first_edit_step"]
        key = ("no compaction" if not comp else "compaction, never edited" if not edit
               else "compaction before first edit" if int(comp) < int(edit) else "first edit before compaction")
        c[key, r["resolved"]] += 1
    print(f"\n## {bundle}: first compaction vs first edit\n")
    print("| order | runs | solved |")
    print("|---|---|---|")
    for key in ("no compaction", "first edit before compaction", "compaction before first edit", "compaction, never edited"):
        print(f"| {key} | {c[key, 0] + c[key, 1]} | {c[key, 1]} |")


def table_malformed():
    """Tool calls whose parsed name/argument keys are not the tool's own (outcomes.csv, from the trajectories)."""
    c = collections.defaultdict(lambda: [0, 0])
    for r in R:
        if r["traced_calls"] in ("", "0"):
            continue
        k = (r["model"], r["bundle"])
        c[k][0] += int(r["malformed_calls"])
        c[k][1] += int(r["traced_calls"])
    print("\n## Malformed tool calls per traced call\n")
    print("| model | bundle | malformed / traced calls | rate |")
    print("|---|---|---|---|")
    for k in sorted(c):
        b, n = c[k]
        print(f"| {k[0]} | {k[1]} | {b}/{n} | {100 * b / n:.1f}% |")


table_gates()
table_mix()
table_calibration()
table_power()
if ARGS.meta:
    table_profile(ARGS.meta)
table_compaction()
table_malformed()
