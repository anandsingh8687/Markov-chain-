#!/usr/bin/env python3
"""Coordinate search over the agent's tunables. Cloud-only.

`main.py` reads an optional `KG_PARAMS` JSON override at import time, so the
search can vary a parameter vector without editing the agent. The override is
unset on the Kaggle evaluator, where the baked-in defaults apply -- so what is
searched here is exactly what ships, and the search can never leak into a
submission.

The objective is mean final bank against a FIXED opponent over a seeded set,
both sides swapped. Mean is used rather than win rate because both players draw
from the same order book: an absolute score is only interpretable relative to
who was on the other side of it, and the margin is far lower variance than the
binary outcome at these sample sizes.

A warning worth heeding, because this search has produced it twice. Results
here are conditional on the opponent AND the seed set:

  * a four-seed run against an older agent preferred `PLACE_FIX=0` by 10%;
    re-checked over eight seeds against the incumbent, the same change LOST
    16% and the ranking reversed;
  * `FEED_DAYS=3` scored +12% over eight seeds; over 32 held-out and fresh
    episodes it was dead level on mean and 18% worse on the worst episode.

At sixteen episodes the standard error on the mean is several thousand, so a
difference under roughly 8% is not a result. Treat every output of this script
as a hypothesis, confirm it on seeds the search did not use, and look at the
worst episode as well as the mean before changing a default in `main.py`.

    python tools/search_params.py --agent agents/scratch/main.py \
        --opponent benchmark/legacy/pr1/main.py --seeds 1,2,3,4 --rounds 2
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.join(HERE, "_eval_params.py")

GRID = [
    ("HIRE_WINDOW", [0, 1, 2, 3]),
    ("WHEAT_BUF", [1.2, 1.8, 2.4, 3.0]),
    ("DISC", [0.0, 0.05, 0.10]),
    ("HIRE_FRAC", [0.10, 0.16, 0.22, 0.32]),
    ("MAX_HANDS", [11, 12, 13, 14, 15]),
    ("HIRE_OFF", [0, 1, 2]),
    ("RUNWAY", [2.0, 3.0, 4.0, 6.0, 9.0]),
    ("OVERSUPPLY", [1.0, 1.35, 1.8, 2.5]),
    ("BUY_RATE", [2, 4, 7]),
    ("LAND_OPEN", [5, 8, 14, 22]),
    ("CARRY_DROP", [7, 11, 16, 24]),
    ("PER_RANCHER", [2.5, 3.0, 3.5, 4.2, 5.5]),
    ("OPEN_FAST", [0, 4, 8]),
    ("ACT_ANIMAL", [2.2, 2.9, 3.8]),
    ("ACT_CROP", [0.85, 1.15, 1.5]),
    ("MOVE", [1.5, 1.85, 2.3]),
    ("WEED_W", [3.0, 6.0, 7.5, 11.0]),
    ("ANIM_MARGIN", [0.6, 1.0, 1.5]),
    ("LAND_LABOR", [0.4, 1.0, 2.0]),
    ("PLACE_FIX", [0, 1]),
    ("FERT_USE", [0, 1]),
    ("SELL_SLOTS", [4, 6, 9]),
]


def run_batch(params, agent, opponent, seeds, jobs):
    procs = []
    for p in params:
        procs.append((p, subprocess.Popen(
            [sys.executable, EVAL, json.dumps(p), agent, opponent, seeds],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)))
    out = []
    for p, pr in procs:
        so, _ = pr.communicate()
        try:
            r = json.loads(so.decode().strip().splitlines()[-1])
            out.append((p, -1e9 if "err" in r else r["mean"], r))
        except Exception:
            out.append((p, -1e9, {"err": "unparseable"}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="agents/scratch/main.py")
    ap.add_argument("--opponent", default="benchmark/legacy/pr1/main.py")
    ap.add_argument("--seeds", default="1,2,3,4,5,6,7,8")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--min-gain", type=float, default=250.0,
                    help="keep the incumbent value unless a candidate beats it "
                         "by this much; guards against chasing seed noise")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    best = {}
    res = run_batch([{}], args.agent, args.opponent, args.seeds, args.jobs)
    bestval = res[0][1]
    print("base mean={:.0f}".format(bestval), flush=True)

    for rnd in range(args.rounds):
        for key, vals in GRID:
            cands = [dict(best, **{key: v}) for v in vals if best.get(key) != v]
            allres = []
            for i in range(0, len(cands), args.jobs):
                allres += run_batch(cands[i:i + args.jobs], args.agent,
                                    args.opponent, args.seeds, args.jobs)
            allres.sort(key=lambda x: -x[1])
            if allres and allres[0][1] > bestval + args.min_gain:
                best, bestval = allres[0][0], allres[0][1]
                print("r{} {} -> {}  mean={:.0f}".format(
                    rnd, key, best.get(key), bestval), flush=True)
            else:
                top = allres[0][1] if allres else float("nan")
                print("r{} {} keep (best candidate {:.0f} vs {:.0f})".format(
                    rnd, key, top, bestval), flush=True)

    print("BEST {} mean={:.0f}".format(json.dumps(best, sort_keys=True), bestval))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump({"params": best, "mean": bestval,
                       "opponent": args.opponent, "seeds": args.seeds}, fh, indent=2)


if __name__ == "__main__":
    main()
