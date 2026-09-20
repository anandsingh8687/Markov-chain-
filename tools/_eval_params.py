#!/usr/bin/env python3
"""Evaluate one parameter vector. Called by tools/search_params.py; cloud-only.

Runs a seeded set of episodes with both sides swapped and prints a one-line
JSON summary. Separate process per vector on purpose: `main.py` reads
`KG_PARAMS` once at import, so a fresh interpreter is the only way to be sure
the vector under test is the one that ran.
"""

from __future__ import annotations

import json
import os
import sys


def main():
    if len(sys.argv) < 5:
        raise SystemExit("usage: _eval_params.py '<json>' <agent> <opponent> <seeds>")
    params = sys.argv[1]
    if params and params != "{}":
        os.environ["KG_PARAMS"] = params
    agent, opponent = sys.argv[2], sys.argv[3]
    seeds = [int(x) for x in sys.argv[4].split(",")]

    from kaggle_environments import make

    scores = []
    wins = losses = ties = 0
    for seed in seeds:
        for flip in (False, True):
            env = make("kaggriculture",
                       configuration={"episodeSteps": 720, "seed": seed},
                       debug=False)
            pair = [opponent, agent] if flip else [agent, opponent]
            try:
                env.run(pair)
            except Exception as exc:                      # noqa: BLE001
                print(json.dumps({"p": params, "err": str(exc)[:160]}))
                raise SystemExit(1)
            r = [s["reward"] for s in env.steps[-1]]
            if any(v is None for v in r):
                print(json.dumps({"p": params, "err": "missing reward"}))
                raise SystemExit(1)
            mine, theirs = (r[1], r[0]) if flip else (r[0], r[1])
            scores.append(mine)
            if mine > theirs:
                wins += 1
            elif mine < theirs:
                losses += 1
            else:
                ties += 1

    n = max(1, wins + losses + ties)
    print(json.dumps({"p": params, "mean": round(sum(scores) / len(scores)),
                      "min": min(scores), "win": round(wins / float(n), 3),
                      "w": wins, "l": losses, "t": ties}))


if __name__ == "__main__":
    main()
