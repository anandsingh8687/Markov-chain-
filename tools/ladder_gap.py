#!/usr/bin/env python3
"""Measure the agent against real ladder banks, seed for seed. Cloud-only.

Every other benchmark in this repository is a local agent, and all of them
finish around a sixth of what the leaderboard actually plays at. This is the
only target that is not self-referential: real episodes from the public agent
at the top of the ladder, replayed on the seed they actually ran on.

Self-play is used for our side because the ladder rows are also same-agent
games -- that public agent is a monoculture, so its episodes are effectively
mirror matches. Comparing a mirror against a mirror on one seed is like for
like; comparing across seeds is not, because the shop draw moves the ceiling
from ~$60k to ~$125k.

    python tools/ladder_gap.py [--agent main.py]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, os.pardir, "benchmark", "ladder", "reference.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="main.py")
    ap.add_argument("--reference", default=REF)
    ap.add_argument("--max-gap", type=float, default=None,
                    help="fail if the mean gap exceeds this fraction (e.g. 0.10)")
    args = ap.parse_args()

    ref = json.load(open(args.reference))
    from kaggle_environments import make

    print("%-12s %12s %12s %10s" % ("seed", "ladder", "ours", "gap"))
    gaps = []
    for row in ref["episodes"]:
        seed = row["seed"]
        env = make("kaggriculture",
                   configuration={"episodeSteps": 720, "seed": seed}, debug=False)
        env.run([args.agent, args.agent])
        ours = max(s["reward"] for s in env.steps[-1])
        ladder = float(row["ladder_bank"])
        gap = (ladder - ours) / ladder
        gaps.append(gap)
        print("%-12d %12.0f %12.0f %9.1f%%" % (seed, ladder, ours, 100.0 * gap))

    mean_gap = sum(gaps) / len(gaps)
    beat = sum(1 for g in gaps if g <= 0)
    print("\nbeaten on %d of %d seeds; mean gap %.1f%% (negative = ahead)"
          % (beat, len(gaps), 100.0 * mean_gap))
    if args.max_gap is not None and mean_gap > args.max_gap:
        print("::error::mean ladder gap %.1f%% exceeds the %.1f%% budget"
              % (100.0 * mean_gap, 100.0 * args.max_gap))
        sys.exit(1)


if __name__ == "__main__":
    main()
