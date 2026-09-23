#!/usr/bin/env python3
"""Replay real ladder opponents against an agent. Runs in the cloud runner.

`benchmark/ghosts/ladder_ghosts.json.gz` holds 367 of this account's own ladder
episodes (v3-v7): for each one the seed, which seat we held, the final banks,
and the opponent's recorded action for every turn. The engine is
deterministic given the seed and both action streams, so replaying the
opponent's tape against our recorded side reproduces the original banks
exactly (checked for every episode kept here). Putting a different agent in
our seat then asks: "what would this agent have scored against the opponent we
actually met, on the board we actually drew?"

The one limitation is that a ghost cannot react. Its orders are the ones it
placed against our old agent, so anything that works by provoking a reaction
is invisible here, and an order the ghost can no longer afford is a silent
no-op. Use it next to the closed-loop gates, not instead of them.

    python tools/ghost_bench.py --agent main.py --filter-version v7 --limit 40
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

DATA = os.path.join("benchmark", "ghosts", "ladder_ghosts.json.gz")


def _ghost(actions):
    def agent(obs, config=None):
        t = int(obs["step"]) + 1
        a = actions[t] if t < len(actions) else None
        return a or {}
    return agent


def play(job):
    agent_path, g = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g["seed"]}, debug=False)
    me = g["seat"]
    agents = [None, None]
    agents[me] = os.path.abspath(agent_path)
    agents[1 - me] = _ghost(g["actions"])
    env.run(agents)
    last = env.steps[-1]
    r = [last[me]["reward"], last[1 - me]["reward"]]
    st = [last[me]["status"], last[1 - me]["status"]]
    return {"ep": g["ep"], "version": g["version"], "opponent": g["opponent"],
            "orig": g["bank"][0] - g["bank"][1],
            "margin": None if None in r else r[0] - r[1], "status": st[0]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="main.py")
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--filter-version", default="", help="comma list, e.g. v7")
    ap.add_argument("--only-lost", action="store_true", help="episodes the original agent lost")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--min-win-rate", type=float, default=0.0)
    ap.add_argument("--report", default="ghost_report.json")
    args = ap.parse_args()

    with gzip.open(args.data, "rt") as fh:
        ghosts = json.load(fh)
    if args.filter_version:
        keep = set(args.filter_version.split(","))
        ghosts = [g for g in ghosts if g["version"] in keep]
    if args.only_lost:
        ghosts = [g for g in ghosts if g["bank"][0] < g["bank"][1]]
    ghosts.sort(key=lambda g: -g["ep"])          # most recent first
    if args.limit:
        ghosts = ghosts[:args.limit]

    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        rows = list(ex.map(play, [(args.agent, g) for g in ghosts]))
    ok = [r for r in rows if r["margin"] is not None and r["status"] == "DONE"]
    bad = len(rows) - len(ok)
    won = sum(r["margin"] > 0 for r in ok)
    was = sum(r["orig"] > 0 for r in ok)
    flipped = sum(r["margin"] > 0 and r["orig"] <= 0 for r in ok)
    lost_now = sum(r["margin"] <= 0 and r["orig"] > 0 for r in ok)
    rate = won / len(rows) if rows else 0.0
    mean = sum(r["margin"] for r in ok) / len(ok) if ok else 0.0
    print("ghost benchmark: {} episodes in {:.0f}s".format(len(rows), time.time() - t0))
    print("  originally won {:3d}   now won {:3d}   ({:.1%})   mean margin {:+,.0f}".format(
        was, won, rate, mean))
    print("  losses turned into wins {}, wins turned into losses {}, errors {}".format(
        flipped, lost_now, bad))
    worst = sorted(ok, key=lambda r: r["margin"])[:5]
    for r in worst:
        print("  worst: ep {} {:<24s} margin {:+,.0f} (orig {:+,.0f})".format(
            r["ep"], r["opponent"][:24], r["margin"], r["orig"]))
    with open(args.report, "w") as fh:
        json.dump({"episodes": len(rows), "won": won, "win_rate": rate, "mean_margin": mean,
                   "errors": bad, "rows": rows}, fh, indent=1)
    if bad:
        sys.exit("::error::{} ghost episodes errored".format(bad))
    if rate < args.min_win_rate:
        sys.exit("::error::ghost win rate {:.1%} below {:.1%}".format(rate, args.min_win_rate))


if __name__ == "__main__":
    main()
