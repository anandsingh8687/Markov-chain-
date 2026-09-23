#!/usr/bin/env python3
"""Self-play A/B: candidate (KG_PARAMS) vs a frozen champion. Cloud-only.

Against a weak opponent the order book is effectively free, so an absolute
score measures how much of an uncontested market the agent can harvest. On a
competitive ladder the book is shared and the drain is fixed: whoever reaches
the high-value products first gets the higher quotes, and the loser is priced
into whatever is left. Those are different problems, and a change can be
worth nothing in the first and decisive in the second.

So strategic changes are judged here -- candidate against the current
champion, both sides swapped -- and only sanity-checked against the weak
benchmarks.
"""
from __future__ import annotations

import json
import os
import sys


def main():
    params = sys.argv[1]
    if params and params != "{}":
        os.environ["KG_PARAMS"] = params
    cand = sys.argv[2] if len(sys.argv) > 2 else "agents/scratch/main.py"
    champ = sys.argv[3] if len(sys.argv) > 3 else "champion.py"
    seeds = [int(x) for x in sys.argv[4].split(",")]

    from kaggle_environments import make

    w = l = t = 0
    mine, theirs = [], []
    for seed in seeds:
        for flip in (False, True):
            env = make("kaggriculture",
                       configuration={"episodeSteps": 720, "seed": seed},
                       debug=False)
            pair = [champ, cand] if flip else [cand, champ]
            try:
                env.run(pair)
            except Exception as exc:                       # noqa: BLE001
                print(json.dumps({"p": params, "err": str(exc)[:160]}))
                raise SystemExit(1)
            r = [s["reward"] for s in env.steps[-1]]
            a, b = (r[1], r[0]) if flip else (r[0], r[1])
            if a is None or b is None:
                print(json.dumps({"p": params, "err": "missing reward"}))
                raise SystemExit(1)
            mine.append(a)
            theirs.append(b)
            if a > b:
                w += 1
            elif a < b:
                l += 1
            else:
                t += 1
    n = max(1, w + l + t)
    print(json.dumps({
        "p": params, "w": w, "l": l, "t": t,
        "score": round((w + 0.5 * t) / float(n), 3),
        "cand": round(sum(mine) / len(mine)),
        "champ": round(sum(theirs) / len(theirs)),
        "edge": round((sum(mine) - sum(theirs)) / len(mine)),
    }))


if __name__ == "__main__":
    main()
