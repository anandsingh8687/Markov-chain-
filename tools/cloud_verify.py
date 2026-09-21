#!/usr/bin/env python3
"""Cloud-only verification gate. Runs on the GitHub Actions runner.

Covers the three ways a Kaggriculture submission dies, then asserts strength:

  1. Import / load error on the eval host  -> Error submission
  2. Uncaught exception mid-episode        -> forfeited episode
  3. A turn exceeding the 1s actTimeout    -> forfeited episode

Beating the built-in starter is table stakes. The second gate is a stronger
carrot-scaling opponent defined here (not a public ladder agent) so a
submission that only farms the starter cannot pass. The third gate is the
frozen PR #1 agent in benchmark/rival/ — the strongest prior agent in this
tree — so a 17%-utilisation farm cannot read as green.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import statistics
import sys
import time

CRUSH_BASE = {
    "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250,
    "MILK": 160, "WOOL": 200,
}
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
MARKET_I0 = 10000


def fail(msg):
    print("::error::{}".format(msg))
    sys.exit(1)


def check_syntax(root):
    print("[1/5] parsing submission sources")
    for name in ("main.py", "agent.py"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            if name == "agent.py":
                continue
            fail("missing {}".format(name))
        with open(path, "r", encoding="utf-8") as fh:
            ast.parse(fh.read(), filename=name)
    print("      ok")


def check_import(root):
    print("[2/5] importing submission entrypoint")
    sys.path.insert(0, root)
    import main  # noqa: E402
    if not callable(getattr(main, "agent", None)):
        fail("main.agent is not callable")
    stub = {
        "player": 0, "day": 0, "hour": 0,
        "farms": [
            {"money": 3000, "tiles": [[None] * 10 for _ in range(10)],
             "farmer": [4, 4], "hands": [], "hires_today": 0,
             "unlocked_quadrants": ["NW"]},
            {"money": 3000, "tiles": [[None] * 10 for _ in range(10)],
             "farmer": [4, 4], "hands": [], "hires_today": 0,
             "unlocked_quadrants": ["NW"]},
        ],
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


def _census_farm(me):
    tiles = (me or {}).get("tiles") or []
    kinds = {}
    animals = {}
    locked = empty = 0
    for row in tiles:
        for t in row:
            if t == "LOCKED":
                locked += 1
                continue
            if t is None:
                empty += 1
                continue
            if isinstance(t, dict):
                if t.get("animal"):
                    animals[t["animal"]] = animals.get(t["animal"], 0) + 1
                else:
                    k = t.get("crop") or t.get("kind") or "?"
                    kinds[k] = kinds.get(k, 0) + 1
    return me or {}, kinds, animals, empty, locked


def _tile_census(env, player=0, step=-1):
    last = env.steps[step]
    obs = (last[0] or {}).get("observation") or {}
    farms = obs.get("farms") or []
    me = farms[player] if player < len(farms) else {}
    return _census_farm(me)


def _empty_struct_count(env, player=0):
    try:
        _me, kinds, _animals, _empty, _locked = _tile_census(env, player)
        return int(kinds.get("COOP", 0) or 0) + int(kinds.get("PASTURE", 0) or 0)
    except Exception:
        return 0


def _weed_count(env, player=0):
    try:
        _me, kinds, _animals, _empty, _locked = _tile_census(env, player)
        return int(kinds.get("WEED", 0) or 0)
    except Exception:
        return 0


def _productive(kinds, animals):
    n = sum(int(v or 0) for v in animals.values())
    for k, v in kinds.items():
        if k in ("COOP", "PASTURE", "WEED", "?"):
            continue
        n += int(v or 0)
    return n


def _midgame_staff(env, at=500):
    """Hour 20 of day 20. Not hour 0 — EOD wipes farm['hands']."""
    try:
        idx = at if at < len(env.steps) else -1
        me, kinds, animals, empty, locked = _tile_census(env, 0, idx)
        hands = len(me.get("hands") or [])
        unlocked = max(1, 100 - locked)
        prod = _productive(kinds, animals)
        util = prod / float(unlocked)
        n_animals = sum(int(v or 0) for v in animals.values())
        if hands < 8:
            return False, ("under-staffed midgame: {} hands (need 8). "
                           "HIREs were dropped by the 10-order cap or fib-exploded."
                           .format(hands))
        if unlocked >= 40 and util < 0.35:
            return False, ("under-utilized midgame: {:.0%} of {} tiles (need 35%). "
                           "Weeds were under-staffing; shrinking the board froze idle land."
                           .format(util, unlocked))
        if unlocked >= 50 and n_animals < 6:
            return False, ("herd stall midgame: {} animals on {} tiles (need 6). "
                           "Hour-0 wipe reset goose_cap to the farmer and dropped the ramp."
                           .format(n_animals, unlocked))
        return True, ""
    except Exception:
        return True, ""


def _farmed_products(kinds, animals):
    farmed = set()
    for k in kinds or {}:
        if k in CRUSH_BASE or k in ("WHEAT", "EGG"):
            farmed.add(k)
    for a, n in (animals or {}).items():
        if n and a in ANIMAL_PRODUCT:
            farmed.add(ANIMAL_PRODUCT[a])
    return farmed


def _book_crush(env, player=0):
    """Fail if a farmed premium/staple (not wheat/egg) finished oversupplied
    below a quarter of base. That is the melon-at-$7 inversion: 12 tiles of
    the only crop with no shop, while strawberry sat at 2.2× base unfarmed.
    """
    try:
        last = env.steps[-1]
        obs = (last[0] or {}).get("observation") or {}
        market = obs.get("market") or {}
        inv = market.get("inventory") or {}
        prices = market.get("prices") or {}
        _me, kinds, animals, _empty, _locked = _tile_census(env, player, 500)
        farmed = _farmed_products(kinds, animals)
        crushed = []
        for prod in farmed:
            if prod in ("WHEAT", "EGG", "FERTILIZER"):
                continue
            base = CRUSH_BASE.get(prod)
            if not base:
                continue
            inventory = float(inv.get(prod, MARKET_I0) or MARKET_I0)
            price = float(prices.get(prod, base) or base)
            if inventory > MARKET_I0 and price < 0.25 * base:
                crushed.append("{} inv={:.0f} quote=${:.0f} (base ${})".format(
                    prod, inventory, price, base))
        if crushed:
            return False, ("book crush: {}. Staffing filled tiles; the mix "
                           "walked a shop-less book to the floor.".format(
                               "; ".join(crushed)))
        return True, ""
    except Exception:
        return True, ""


def book_telemetry(env, label="p0"):
    try:
        last = env.steps[-1]
        obs = (last[0] or {}).get("observation") or {}
        market = obs.get("market") or {}
        inv = market.get("inventory") or {}
        prices = market.get("prices") or {}
        bits = []
        for prod in ("MELON", "STRAWBERRY", "WHEAT", "MILK", "WOOL", "EGG"):
            bits.append("{}={:.0f}/${:.0f}".format(
                prod.lower()[:6],
                float(inv.get(prod, MARKET_I0) or MARKET_I0) - MARKET_I0,
                float(prices.get(prod, 0) or 0)))
        print("      book {} {}".format(label, " ".join(bits)))
    except Exception as exc:
        print("      book telemetry unavailable: {}".format(exc))


def farm_telemetry(env, label="p0", step=-1):
    """Farm snapshot. Mid-horizon (step 480) is utilisation; T=720 is after harvest."""
    try:
        me, kinds, animals, empty, locked = _tile_census(env, 0, step)
        hands = len(me.get("hands") or [])
        unlocked = max(1, 100 - locked)
        prod = _productive(kinds, animals)
        print("      telemetry {} money={} hands={} quads={} animals={} crops={} "
              "empty={} locked={} util={:.0%}".format(
                  label, me.get("money"), hands, me.get("unlocked_quadrants"),
                  animals, kinds, empty, locked, prod / float(unlocked)))
    except Exception as exc:
        print("      telemetry unavailable: {}".format(exc))


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
    farm_telemetry(env, "self-play-p0-end", -1)
    farm_telemetry(env, "self-play-p0-mid", 500)
    return env


def check_latency(env):
    print("[4/5] per-turn latency against the 1s actTimeout")
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


def carrot_scaler(obs):
    """Stronger-than-starter cloud gate opponent. Not a ladder solution.

    Hires cheap hands, plants the whole NW quadrant with carrots, waters,
    harvests at first_yield_day, sells the shed. Exists only so the gate
    cannot be satisfied by beating the built-in wheat loop.
    """
    player = obs.get("player", 0)
    farms = obs.get("farms", [])
    me = farms[player] if player < len(farms) else {}
    private = obs.get("private", {}) or {}
    seeds = private.get("seeds", {}) or {}
    shed = private.get("shed", {}) or {}
    tiles = me.get("tiles", []) or []
    farmer = list(me.get("farmer", [4, 4]) or [4, 4])
    hands = [list(h) for h in (me.get("hands", []) or [])]
    money = float(me.get("money", 0) or 0)
    hires = int(me.get("hires_today", 0) or 0)
    day = int(obs.get("day", 0) or 0)
    hour = int(obs.get("hour", 0) or 0)
    fx, fy = farmer[0], farmer[1]

    market = []
    if shed.get("CARROT", 0):
        market.append(["SELL", "CARROT", int(shed["CARROT"])])
    if shed.get("WHEAT", 0):
        market.append(["SELL", "WHEAT", int(shed["WHEAT"])])
    have = int(seeds.get("CARROT", 0) or 0)
    if have < 25 and money >= 20:
        n = min(25 - have, int(money // 20))
        if n > 0:
            market.append(["BUY_SEED", "CARROT", n])
    if hour <= 1 and hires < 4 and money > 8:
        market.append(["HIRE"])
        if hires < 3:
            market.append(["HIRE"])

    workers = [(fx, fy)] + [(h[0], h[1]) for h in hands]
    actions = []
    claimed = set()
    for wx, wy in workers:
        tile = None
        try:
            tile = tiles[wy][wx]
        except Exception:
            tile = "LOCKED"
        if tile is None and seeds.get("CARROT", 0) > 0 and hour < 23:
            actions.append(["PLANT", "CARROT"])
            continue
        if isinstance(tile, dict) and tile.get("kind") == "PLANT":
            age = day - int(tile.get("planted_day", day))
            if tile.get("yield_units", 0) > 0 and age >= 2:
                actions.append(["HARVEST"])
                continue
            if not tile.get("watered_today"):
                actions.append(["WATER"])
                continue
        if isinstance(tile, dict) and tile.get("kind") == "WEED":
            actions.append(["DIG"])
            continue
        target = None
        best = 10 ** 9
        for y, row in enumerate(tiles):
            for x, t in enumerate(row):
                if (x, y) in claimed or t == "LOCKED":
                    continue
                score = None
                if isinstance(t, dict) and t.get("kind") == "PLANT":
                    age = day - int(t.get("planted_day", day))
                    if t.get("yield_units", 0) > 0 and age >= 2:
                        score = 0
                    elif not t.get("watered_today"):
                        score = 1
                elif t is None and seeds.get("CARROT", 0) > 0 and hour < 23:
                    score = 2
                elif isinstance(t, dict) and t.get("kind") == "WEED":
                    score = 3
                if score is None:
                    continue
                d = abs(x - wx) + abs(y - wy) + score * 20
                if d < best:
                    best, target = d, (x, y)
        if target is None:
            actions.append(["PASS"])
            continue
        claimed.add(target)
        tx, ty = target
        if tx > wx:
            actions.append(["EAST"])
        elif tx < wx:
            actions.append(["WEST"])
        elif ty > wy:
            actions.append(["SOUTH"])
        elif ty < wy:
            actions.append(["NORTH"])
        else:
            actions.append(["PASS"])

    farmer_action = actions[0] if actions else ["PASS"]
    hand_actions = actions[1:1 + len(hands)]
    while len(hand_actions) < len(hands):
        hand_actions.append(["PASS"])
    return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


def load_callable_agent(path):
    """Load a frozen rival's agent(obs) without shadowing the submission."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("kaggriculture_rival", path)
    if spec is None or spec.loader is None:
        fail("could not load rival agent from {}".format(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "agent", None)
    if not callable(fn):
        fail("rival at {} has no callable agent()".format(path))
    return fn


def check_strength(root, games, opponent, report_path):
    print("[5/5] strength gate: {} episodes vs '{}'".format(games, opponent))
    path = os.path.join(root, "main.py")
    if opponent == "carrot_scaler":
        opp = carrot_scaler
    elif opponent in ("pr1_rival", "rival"):
        opp = load_callable_agent(os.path.join(root, "benchmark", "rival", "agent.py"))
    else:
        opp = opponent
    wins = tie = loss = 0
    margins = []
    # A win at 6.6k is a ramp collapse: we parked on the opponent's book.
    # 38+ empty coops is the next collapse: we built sheds faster than we fed.
    if opponent in ("pr1_rival", "rival"):
        min_farm = 16000.0
    elif opponent == "carrot_scaler":
        min_farm = 20000.0
    else:
        min_farm = 18000.0
    max_empty_structs = 16
    for g in range(games):
        seed = 9000 + g * 17
        rewards, statuses, wall, env = run_episode([path, opp], seed=seed)
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
        farm_telemetry(env, "seed-{}-end".format(seed), -1)
        farm_telemetry(env, "seed-{}-mid".format(seed), 500)
        book_telemetry(env, "seed-{}".format(seed))
        if mine < min_farm:
            fail("ramp collapse vs {} seed {}: score {:.0f} < {:.0f}. "
                 "We won or lost with a farm that never left the opponent's book."
                 .format(opponent, seed, mine, min_farm))
        empty_structs = _empty_struct_count(env)
        if empty_structs > max_empty_structs:
            fail("structure explosion vs {} seed {}: {} empty COOP/PASTURE (max {}). "
                 "Workers reserved every empty tile for sheds while geese starved."
                 .format(opponent, seed, empty_structs, max_empty_structs))
        weeds = _weed_count(env)
        if weeds > 20:
            fail("weed farm vs {} seed {}: {} weeds. Plants were sown faster "
                 "than leftover workers could water them."
                 .format(opponent, seed, weeds))
        ok, reason = _midgame_staff(env)
        if not ok:
            fail("{} vs {} seed {}".format(reason, opponent, seed))
        ok, reason = _book_crush(env)
        if not ok:
            fail("{} vs {} seed {}".format(reason, opponent, seed))
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
    ap.add_argument("--report", default=None)
    ap.add_argument("--strength-only", action="store_true")
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
