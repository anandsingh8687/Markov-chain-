#!/usr/bin/env python3
"""Cloud-only verification gate. Runs on the GitHub Actions runner, never locally.

A Kaggriculture submission fails in exactly three ways, and this gate covers all
three before a submission slot is ever spent:

  1. Import / load error on the eval host  -> `Error` submission
  2. An uncaught exception mid-episode     -> forfeited episode
  3. A turn exceeding the 1s actTimeout    -> forfeited episode

It then asserts the agent is actually competitive (beats the built-in `starter`
on the majority of seeded episodes) rather than merely non-crashing.
"""

from __future__ import annotations

import argparse
import compileall
import json
import os
import statistics
import sys
import time

ACT_TIMEOUT_S = 1.0
LATENCY_CEILING_S = 0.80          # hard fail margin under the 1s timeout
HORIZON = 720


def fail(msg):
    print("::error::{}".format(msg))
    sys.exit(1)


def check_syntax(root):
    print("[1/5] byte-compiling {}".format(root))
    if not compileall.compile_dir(root, quiet=1, force=True):
        fail("byte-compilation failed")
    print("      ok")


def check_import(root):
    print("[2/5] importing submission entrypoint")
    sys.path.insert(0, root)
    import main  # noqa: E402
    if not callable(getattr(main, "agent", None)):
        fail("main.agent is not callable")
    # The eval host exec()s main.py without __file__; make sure nothing depends
    # on it and that a bare, minimal observation is survivable.
    stub = {
        "player": 0, "day": 0, "hour": 0,
        "farms": [{"money": 3000, "tiles": [[None] * 10 for _ in range(10)],
                   "farmer": [0, 0], "hands": [], "hires_today": 0,
                   "unlocked_quadrants": ["NW"]},
                  {"money": 3000, "tiles": [[None] * 10 for _ in range(10)],
                   "farmer": [9, 9], "hands": [], "hires_today": 0,
                   "unlocked_quadrants": ["NW"]}],
        "private": {"shed": {}, "seeds": {}, "inventories": [{}]},
        "market": {"inventory": {}, "prices": {}},
        "town": {"unlocked_shops": []},
    }
    act = main.agent(stub)
    for key in ("farmer", "hands", "market"):
        if key not in act:
            fail("action missing required key '{}'".format(key))
    print("      ok (cold-start action: {})".format(act["farmer"]))
    return main


def run_episode(agents, seed, debug=False):
    from kaggle_environments import make
    cfg = {"episodeSteps": HORIZON}
    if seed is not None:
        cfg["seed"] = seed
    env = make("kaggriculture", configuration=cfg, debug=debug)
    t0 = time.time()
    env.run(agents)
    wall = time.time() - t0
    final = env.steps[-1]
    rewards = [s.get("reward") for s in final]
    statuses = [s.get("status") for s in final]
    return rewards, statuses, wall, env


def check_selfplay(root):
    print("[3/5] validation episode: agent vs. a copy of itself (720 turns)")
    path = os.path.join(root, "main.py")
    rewards, statuses, wall, env = run_episode([path, path], seed=4242, debug=True)
    for i, s in enumerate(statuses):
        if s != "DONE":
            fail("self-play player {} ended with status {} (rewards={})".format(
                i, s, rewards))
    print("      ok  rewards={}  wall={:.1f}s".format(rewards, wall))
    return env


def check_latency(env):
    print("[4/5] per-turn latency against the 1s actTimeout")
    # remainingOverageTime is a budget that only *decreases* when an agent runs
    # past actTimeout, so the meaningful statistic is its minimum, not its
    # maximum. A material drawdown means some turn went long even though the
    # episode still finished.
    lowest = None
    initial = None
    for step in env.steps:
        for s in step:
            obs = s.get("observation", {}) or {}
            ot = obs.get("remainingOverageTime")
            if ot is None:
                continue
            ot = float(ot)
            if initial is None:
                initial = ot
            lowest = ot if lowest is None else min(lowest, ot)

    if lowest is None or initial is None:
        print("      overage telemetry unavailable; DONE status already implies "
              "no turn was killed by the timeout")
        print("      ok")
        return

    used = initial - lowest
    print("      overage budget: start {:.1f}s, low-water {:.1f}s, consumed {:.1f}s"
          .format(initial, lowest, used))
    if lowest <= 0.0:
        fail("overage budget was exhausted: at least one turn blew the 1s "
             "actTimeout. This forfeits episodes on the ladder.")
    if initial > 0 and used > 0.25 * initial:
        fail("consumed {:.0f}% of the overage budget ({:.1f}s of {:.1f}s). "
             "Turns are running too close to the 1s actTimeout."
             .format(100.0 * used / initial, used, initial))
    print("      ok")


def check_strength(root, games, opponent, report_path):
    print("[5/5] strength gate: {} episodes vs. built-in '{}'".format(games, opponent))
    path = os.path.join(root, "main.py")
    wins = tie = loss = 0
    margins = []
    for g in range(games):
        seed = 9000 + g * 17
        rewards, statuses, wall, _ = run_episode([path, opponent], seed=seed)
        if statuses[0] != "DONE":
            fail("episode {} (seed {}) ended with status {}".format(g, seed, statuses[0]))
        mine = rewards[0] if rewards[0] is not None else 0.0
        theirs = rewards[1] if rewards[1] is not None else 0.0
        margins.append(mine - theirs)
        if mine > theirs:
            wins += 1
        elif mine == theirs:
            tie += 1
        else:
            loss += 1
        print("      seed {:>5}  ours={:>10.0f}  opp={:>10.0f}  {}".format(
            seed, mine, theirs, "WIN" if mine > theirs else
            ("TIE" if mine == theirs else "LOSS")))
    rate = (wins + 0.5 * tie) / float(max(1, games))
    med = statistics.median(margins) if margins else 0.0
    print("      score rate vs {}: {:.0%}  (W{} T{} L{})  median margin {:+.0f}".format(
        opponent, rate, wins, tie, loss, med))
    summary = {"opponent": opponent, "games": games, "wins": wins, "ties": tie,
               "losses": loss, "score_rate": rate, "median_margin": med}
    with open(report_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    return rate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--opponent", default="starter")
    ap.add_argument("--min-score-rate", type=float, default=0.60)
    ap.add_argument("--report", default=None,
                    help="where to write the JSON summary")
    ap.add_argument("--strength-only", action="store_true",
                    help="skip the syntax/import/self-play/latency preflight "
                         "(for a second opponent in the same job)")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    report = args.report or os.path.join(root, "verify_report.json")

    if not args.strength_only:
        check_syntax(root)
        check_import(root)
        env = check_selfplay(root)
        check_latency(env)
    else:
        print("[skip] preflight already run in this job")
    rate = check_strength(root, args.games, args.opponent, report)

    if rate < args.min_score_rate:
        fail("strength gate failed: score rate {:.0%} < required {:.0%}. "
             "Refusing to spend a submission slot.".format(rate, args.min_score_rate))
    print("\nAll gates passed. Agent is clear to submit.")


if __name__ == "__main__":
    main()
