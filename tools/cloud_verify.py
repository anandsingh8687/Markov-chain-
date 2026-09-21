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
    print("[1/7] byte-compiling {}".format(root))
    if not compileall.compile_dir(root, quiet=1, force=True):
        fail("byte-compilation failed")
    print("      ok")


def check_loader(root):
    """Reproduce exactly how kaggle-environments resolves a file submission.

    `get_last_callable` exec()s the file and returns
    `[v for v in env.values() if callable(v)][-1]` -- the LAST callable bound
    in the module namespace, not the one named `agent`. A helper function
    defined below `agent` therefore becomes the submitted agent, and the
    failure looks like a bizarre runtime error rather than a loading mistake.
    This has already cost one rewrite; it is cheap to assert.
    """
    print("[2/7] resolving the entrypoint the way the evaluator does")
    path = os.path.join(root, "main.py")
    with open(path) as fh:
        raw = fh.read()
    env = {}
    exec(compile(raw, path, "exec"), env)
    callables = [k for k, v in env.items() if callable(v)]
    if not callables:
        fail("main.py binds no callable at module level")
    last = callables[-1]
    if last != "agent":
        fail("the evaluator would load '{}', not 'agent' -- kaggle-environments "
             "takes the LAST callable in the module namespace. Move '{}' above "
             "the definition of 'agent'.".format(last, last))
    print("      ok (last module-level callable is 'agent')")


def check_import(root):
    print("[3/7] importing submission entrypoint")
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
    print("[4/7] validation episode: agent vs. a copy of itself (720 turns)")
    # main.py catches its own exceptions and falls back to PASS so a single bad
    # turn cannot forfeit a ladder episode. That safety net would also hide a
    # planner bug from this gate, so verification runs with it disabled.
    os.environ["KG_STRICT"] = "1"
    path = os.path.join(root, "main.py")
    rewards, statuses, wall, env = run_episode([path, path], seed=4242, debug=True)
    for i, s in enumerate(statuses):
        if s != "DONE":
            fail("self-play player {} ended with status {} (rewards={})".format(
                i, s, rewards))
    print("      ok  rewards={}  wall={:.1f}s  (strict mode: no exception "
          "was swallowed)".format(rewards, wall))
    os.environ.pop("KG_STRICT", None)
    return env


def check_latency(env):
    print("[5/7] per-turn latency against the 1s actTimeout")
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


def check_structure(root, opponent="starter", seed=9034):
    """Assert the farm is actually being worked, and the book is not crushed.

    Absolute score hides both of the failure modes seen in this repository.
    A farm can buy 75 tiles and work thirteen of them; an allocator can pour
    tiles into the one product the town never buys and drive it to the floor.
    Neither shows up as an exception and both can still beat `starter`.

    Sampled at turn 480 (day 20, hour 12 -- NOT hour 0, where the end-of-day
    wipe of farm["hands"] makes every crew read as zero).

    The midgame staffing/utilisation form of this check is borrowed from
    PR #2, which arrived at it independently after the same 40-weed symptom.
    """
    print("[7/7] structural check at turn 480 (staffing, utilisation, book)")
    path = os.path.join(root, "main.py")
    _, _, _, env = run_episode([path, opponent], seed=seed)

    idx = 480 + 12
    if idx >= len(env.steps):
        idx = len(env.steps) // 2
    obs = env.steps[idx][0]["observation"]
    farm = obs["farms"][0]
    unlocked = productive = weeds = 0
    for row in farm["tiles"]:
        for t in row:
            if t == "LOCKED":
                continue
            unlocked += 1
            if isinstance(t, dict):
                if t.get("kind") == "PLANT" or t.get("animal"):
                    productive += 1
                elif t.get("kind") == "WEED":
                    weeds += 1
    hands = len(farm.get("hands", []) or [])
    util = 100.0 * productive / float(max(1, unlocked))
    print("      hands={}  unlocked={}  productive={}  utilisation={:.0f}%  weeds={}"
          .format(hands, unlocked, productive, util, weeds))
    if hands < 8:
        fail("only {} hands at turn 480. Labour is the cheapest capacity in the "
             "game; an under-staffed farm turns into weeds.".format(hands))
    if util < 45.0:
        fail("utilisation {:.0f}% at turn 480 ({} of {} tiles productive). The "
             "board is being bought and not worked.".format(util, productive, unlocked))
    if weeds > 20:
        fail("{} weed tiles at turn 480 -- plants are dying unwatered.".format(weeds))

    final = env.steps[-1][0]["observation"]["market"]
    inv, prices = final["inventory"], final["prices"]
    for item, base in (("MELON", 250), ("STRAWBERRY", 120), ("MILK", 160),
                       ("WOOL", 200), ("CARROT", 35)):
        over = inv.get(item, I0) - I0
        if over > 60 and prices.get(item, base) < base * 0.25:
            fail("{} finished {} units oversupplied at ${} against a ${} base. "
                 "Tile-days went into a product the book had already stopped "
                 "paying for.".format(item, over, prices.get(item), base))
    print("      ok (no farmed product crushed below a quarter of base)")


def check_strength(root, games, opponent, report_path):
    print("[6/7] strength gate: {} episodes vs. built-in '{}'".format(games, opponent))
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


I0 = 10000


def diagnose(root, opponent, seed=9000):
    """Print a per-day census of one episode. Telemetry, not a gate.

    Absolute score says a strategy is losing; it does not say where. This
    shows the farm and the book side by side, so an under-planted board, an
    unsold shed, a starved herd or a stalled land purchase are each visible
    on sight rather than inferred.
    """
    print("\n=== census: ours vs. {} (seed {}) ===".format(opponent, seed))
    path = os.path.join(root, "main.py")
    rewards, statuses, wall, env = run_episode([path, opponent], seed=seed)

    hdr = ("day  money   land  crops(W/C/T/S/M)  animals  weed empty  "
           "hands shed  sold(units by product)")
    print(hdr)
    for day in (1, 3, 5, 8, 12, 16, 20, 24, 28, 29):
        idx = day * 24
        if idx >= len(env.steps):
            break
        try:
            obs = env.steps[idx][0]["observation"]
            farm = obs["farms"][0]
            priv = obs["private"]
            tiles = farm["tiles"]
        except Exception:
            continue

        counts = {"WHEAT": 0, "CARROT": 0, "TOMATO": 0, "STRAWBERRY": 0, "MELON": 0}
        animals = weeds = empty = locked = 0
        for row in tiles:
            for t in row:
                if t == "LOCKED":
                    locked += 1
                elif t is None:
                    empty += 1
                elif isinstance(t, dict):
                    k = t.get("kind")
                    if k == "PLANT":
                        c = t.get("crop")
                        if c in counts:
                            counts[c] += 1
                    elif k == "WEED":
                        weeds += 1
                    elif t.get("animal"):
                        animals += 1
        shed = priv.get("shed", {}) or {}
        shed_n = sum(v for v in shed.values() if isinstance(v, (int, float)))
        inv = (obs.get("market", {}) or {}).get("inventory", {}) or {}
        sold = {k: int(v - I0) for k, v in inv.items() if v and (v - I0) > 0}
        sold_s = " ".join("{}:{}".format(k[:3], v) for k, v in
                          sorted(sold.items(), key=lambda kv: -kv[1])[:5])
        print("{:>3}  {:>6.0f}  {:>4}  {:>2}/{:>2}/{:>2}/{:>2}/{:>2}       "
              "{:>3}     {:>3} {:>4}   {:>3}  {:>3}  {}".format(
                  day, farm.get("money", 0), 100 - locked,
                  counts["WHEAT"], counts["CARROT"], counts["TOMATO"],
                  counts["STRAWBERRY"], counts["MELON"],
                  animals, weeds, empty, len(farm.get("hands", []) or []),
                  int(shed_n), sold_s))
    print("final: ours={} opp={}".format(rewards[0], rewards[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--opponent", default="starter")
    ap.add_argument("--min-score-rate", type=float, default=0.60)
    ap.add_argument("--report", default=None,
                    help="where to write the JSON summary")
    ap.add_argument("--diagnose", action="store_true",
                    help="print a per-day census instead of gating")
    ap.add_argument("--strength-only", action="store_true",
                    help="skip the syntax/import/self-play/latency preflight "
                         "(for a second opponent in the same job)")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    report = args.report or os.path.join(root, "verify_report.json")

    if args.diagnose:
        sys.path.insert(0, root)
        diagnose(root, args.opponent)
        return

    if not args.strength_only:
        check_syntax(root)
        check_loader(root)
        check_import(root)
        env = check_selfplay(root)
        check_latency(env)
        check_structure(root)
    else:
        print("[skip] preflight already run in this job")
    rate = check_strength(root, args.games, args.opponent, report)

    if rate < args.min_score_rate:
        fail("strength gate failed: score rate {:.0%} < required {:.0%}. "
             "Refusing to spend a submission slot.".format(rate, args.min_score_rate))
    print("\nAll gates passed. Agent is clear to submit.")


if __name__ == "__main__":
    main()
