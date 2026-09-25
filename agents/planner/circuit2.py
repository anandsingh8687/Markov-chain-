"""Circuit planner, executor v2: every unit's day is planned exactly each morning.

At hour 0 the planner lists every tile's jobs for today (feed/care/collect/harvest for
animals; water, harvest-and-replant, fertilize, dig for crops), then cuts each quadrant's
tiles into nearest-neighbour tours from that quadrant's shed corner. A tour is closed as
soon as its exact cost (pickups + moves + operations) would exceed a unit's turns, so
every tile on a tour is reached today. One unit per tour: the farmer takes the first,
one hand is hired for each of the others.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from circuit import (Planner as _Base, P, CROPS, ANIMALS, ACCESS, ACCESS_TILES, QUAD_TILES,
                     dist, step_toward, fib, MAXORD)

P2 = {"FARMER_TURNS": 23, "HAND_TURNS": 21, "MAX_TOURS": 12}


class Planner(_Base):
    # -------------------------------------------------------------- daily jobs
    def tile_plan(self, obs, s, p, day):
        """Ops for tile p today, and what they consume: (ops, need) with need a dict of
        items to carry (WHEAT, FERTILIZER, animals) and seeds."""
        me = int(obs["player"]); farm = obs["farms"][me]
        t = farm["tiles"][p[1]][p[0]]; role = s["design"].get(p)
        ops, need = [], {}
        if role is None or t == "LOCKED":
            return ops, need
        if role in ANIMALS:
            a = ANIMALS[role]
            if t is None:
                ops = [a["build"], "PLACE"]; need[role] = 1
            elif isinstance(t, dict) and t.get("kind") == "WEED":
                ops = ["DIG", a["build"], "PLACE"]; need[role] = 1
            elif isinstance(t, dict) and t.get("kind") == a["struct"] and "animal" not in t:
                ops = ["PLACE"]; need[role] = 1
            elif isinstance(t, dict) and t.get("animal"):
                ops = ["FEED", "CARE"]; need["WHEAT"] = 1
                if t.get("fertilizer_available"):
                    ops.append("COLLECT_FERTILIZER")
                if int(t.get("yield_units", 0)) > 0:
                    ops.append("HARVEST")
            return ops, need
        c = CROPS[role]
        replant = self.crop_fits(role, day) and day <= self.plant_until(role)
        if t is None:
            if replant:
                ops = ["PLANT", "WATER"]; need["seed:" + role] = 1
        elif isinstance(t, dict) and t.get("kind") == "WEED":
            ops = ["DIG"] + (["PLANT", "WATER"] if replant else [])
            if replant:
                need["seed:" + role] = 1
        elif isinstance(t, dict) and t.get("kind") == "PLANT":
            crop = t["crop"]; c = CROPS[crop]
            age = day - int(t.get("planted_day", day)); y = int(t.get("yield_units", 0))
            if not c["ongoing"]:
                if age >= c["myd"]:
                    ops = ["WATER", "HARVEST"]
                    if replant and s["design"].get(p) == crop or (replant and s["design"].get(p) in CROPS):
                        ops += ["PLANT", "WATER"]; need["seed:" + s["design"][p]] = 1
                else:
                    ops = ["WATER"] if self.needs_water(t, c, age, day) else []
            else:
                last = c["fyd"] + c["interval"] * (c["my"] - 1)
                if age > last and y == 0:
                    ops = ["DIG"] + (["PLANT", "WATER"] if replant else [])
                    if replant:
                        need["seed:" + s["design"][p]] = 1
                else:
                    ops = ["WATER"] if self.needs_water(t, c, age, day) else []
                    if c["fyd"] - 1 <= age <= last and int(t.get("fertilized_until_day", -1)) < day:
                        ops.append("FERTILIZE"); need["FERTILIZER"] = 1
                    if y >= 2 or (y > 0 and (age >= last or day >= 29)):
                        ops.append("HARVEST")
        return ops, need

    def needs_water(self, t, c, age, day):
        """Water only when survival or yield depends on it: a plant survives one dry day;
        non-ongoing crops gain yield from waterings in their window; fertilized ongoing
        crops need a watered production day for the bonus."""
        if int(t.get("consecutive_unwatered", 0)) >= 1:
            return True
        if not c["ongoing"]:
            return age >= (c["myd"] + 1) // 2 - 1
        return int(t.get("fertilized_until_day", -1)) >= day or age >= c["fyd"] - 1

    def build_zones(self, obs, s, owned):
        """Exact daily tours. Stores s['tours']: list of dicts(quad, stops=[(p, ops)], carry)."""
        day = int(obs["step"]) // 24
        tours = []
        for q in owned:
            jobs = []
            for p in QUAD_TILES[q]:
                ops, need = self.tile_plan(obs, s, p, day)
                if ops:
                    jobs.append((p, ops, need))
            left = jobs[:]
            while left:
                last = ACCESS[q]; cost = 0; stops = []; carry = {}
                budget = P2["FARMER_TURNS"] if not tours else P2["HAND_TURNS"]
                while left:
                    j = min(left, key=lambda j: (dist(last, j[0]), j[0]))
                    add = dist(last, j[0]) + len(j[1])
                    new_items = [k for k in j[2] if not k.startswith("seed:") and k not in carry]
                    add += len(new_items)                       # one PICKUP per new item type
                    if stops and cost + add > budget:
                        break
                    stops.append((j[0], list(j[1]))); cost += add; last = j[0]; left.remove(j)
                    for k, v in j[2].items():
                        carry[k] = carry.get(k, 0) + v
                tours.append({"quad": q, "stops": stops, "carry": carry, "cost": cost,
                              "animals": sum(1 for p, ops in stops if "FEED" in ops or "PLACE" in ops)})
        tours.sort(key=lambda t: -t["animals"])
        if len(tours) > P2["MAX_TOURS"] and not s.get("_capping"):
            me = int(obs["player"]); farm = obs["farms"][me]
            spare = [p for p, r in s["design"].items() if r in CROPS and farm["tiles"][p[1]][p[0]] is None]
            spare.sort(key=lambda p: -min(dist(p, a) for a in ACCESS.values()))
            for p in spare[:max(1, 3 * (len(tours) - P2["MAX_TOURS"]))]:
                s["design"].pop(p, None)
            s["_capping"] = True
            try:
                return self.build_zones(obs, s, owned)
            finally:
                s["_capping"] = False
        s["tours"] = tours
        s["zones"] = tours           # the base market() sizes hires by len(zones)


    # ------------------------------------------------------- market-aware targets
    def opp_supply(self, obs):
        """Daily output of the opponent's farm, from its visible tiles."""
        me = int(obs["player"]); f = obs["farms"][1 - me]
        out = {}
        for row in f["tiles"]:
            for t in row:
                if isinstance(t, dict) and t.get("animal"):
                    prod, rate = {"COW": ("MILK", 1.5), "SHEEP": ("WOOL", 1.33), "GOOSE": ("EGG", 2.0)}[t["animal"]]
                    out[prod] = out.get(prod, 0) + rate
                elif isinstance(t, dict) and t.get("kind") == "PLANT":
                    c = CROPS[t["crop"]]
                    rate = (8.0 / 16) if t["crop"] == "STRAWBERRY" else (8.0 / 11 if t["crop"] == "TOMATO" else (c["my"] - 1) / (c["myd"] + 1))
                    out[t["crop"]] = out.get(t["crop"], 0) + rate
        return out

    def targets(self, day, dem):
        t = _Base.targets(self, day, dem)
        obs = getattr(self, "_obs", None)
        if obs is None or day < 4:
            return t
        opp = self.opp_supply(obs)
        # a shop consumes 6 of each product a day (12 for single-product shops) plus
        # the town centre's 1; a few more shops arrive later in the season
        grow = 1.0 + max(0, 18 - day) / 30.0
        room = {k: max(0.0, (dem.get(k, 0) + 1) * grow - opp.get(k, 0)) for k in ("MILK", "WOOL", "EGG")}
        t["COW"] = max(2, min(t["COW"], int(room["MILK"] / 1.5 + 1)))
        t["SHEEP"] = max(2, min(t["SHEEP"], int(room["WOOL"] / 1.33 + 1)))
        t["GOOSE"] = min(8, t["GOOSE"] + (2 if room["EGG"] > 6 else 0))
        herd = t["COW"] + t["SHEEP"] + t["GOOSE"]
        t["WHEAT"] = max(t["WHEAT"], int(herd * P["WHEAT_PER_ANIMAL"]) + 4)
        return t

    def plan_design(self, obs, s, day):
        self._obs = obs
        return _Base.plan_design(self, obs, s, day)

    # ----------------------------------------------------------------- execution
    def dispatch(self, obs, s, day, hour):
        me = int(obs["player"]); farm = obs["farms"][me]
        n_units = 1 + len(farm["hands"])
        if s.get("run_day") != day:
            s["run_day"] = day; s["runs"] = {}
        tours = s.get("tours", [])
        shed_left = dict(obs["private"]["shed"])
        seeds = dict(obs["private"]["seeds"])
        cmds = []
        for idx in range(n_units):
            if idx >= len(tours):
                cmds.append(["PASS"]); continue
            run = s["runs"].setdefault(idx, {"stops": [(p, list(ops)) for p, ops in tours[idx]["stops"]],
                                             "carry": dict(tours[idx]["carry"]), "loaded": False})
            cmds.append(self.run_unit(obs, s, idx, run, tours[idx], day, hour, shed_left, seeds))
        return cmds

    def run_unit(self, obs, s, idx, run, tour, day, hour, shed_left, seeds):
        me = int(obs["player"]); farm = obs["farms"][me]
        pos = tuple(farm["farmer"] if idx == 0 else farm["hands"][idx - 1])
        inv = obs["private"]["inventories"][idx] if idx < len(obs["private"]["inventories"]) else {}
        if not run["loaded"]:
            if pos in ACCESS_TILES:
                for item, n in sorted(run["carry"].items()):
                    if item.startswith("seed:"):
                        continue
                    want = min(n, shed_left.get(item, 0)) - inv.get(item, 0)
                    if want > 0:
                        shed_left[item] -= want
                        run["carry"][item] = 0
                        return ["PICKUP", item, want]
                    run["carry"][item] = 0
                run["loaded"] = True
            else:
                return [step_toward(pos, ACCESS[tour["quad"]])]
        farm_tiles = farm["tiles"]
        while run["stops"]:
            p, ops = run["stops"][0]
            if pos != p:
                return [step_toward(pos, p)]
            while ops:
                op = ops[0]
                cmd = self.valid_op(obs, s, p, op, inv, seeds, day)
                if cmd:
                    ops.pop(0)
                    if cmd[0] == "PLANT":
                        seeds[cmd[1]] -= 1
                    return cmd
                ops.pop(0)
            run["stops"].pop(0)
        return ["PASS"]

    def valid_op(self, obs, s, p, op, inv, seeds, day):
        me = int(obs["player"]); t = obs["farms"][me]["tiles"][p[1]][p[0]]
        role = s["design"].get(p)
        if op in ("BUILD_PASTURE", "BUILD_COOP"):
            return [op] if t is None else None
        if op == "PLACE":
            if role in ANIMALS and inv.get(role, 0) > 0:
                return ["PLACE", role]
            return None
        if op == "DIG":
            return ["DIG"] if isinstance(t, dict) and "animal" not in t and t.get("kind") in ("WEED", "PLANT") else None
        if op == "PLANT":
            # after a HARVEST/DIG in this same visit the tile is empty on the next step
            crop = role if role in CROPS else None
            if crop and seeds.get(crop, 0) > 0 and t is None:
                return ["PLANT", crop]
            return None
        if op == "WATER":
            return ["WATER"] if isinstance(t, dict) and t.get("kind") == "PLANT" and not t.get("watered_today") else None
        if op == "HARVEST":
            return ["HARVEST"] if isinstance(t, dict) and int(t.get("yield_units", 0)) > 0 else None
        if op == "FEED":
            return ["FEED"] if isinstance(t, dict) and t.get("animal") and not t.get("fed_today") and inv.get("WHEAT", 0) > 0 else None
        if op == "CARE":
            return ["CARE"] if isinstance(t, dict) and t.get("animal") and not t.get("cared_today") else None
        if op == "COLLECT_FERTILIZER":
            return [op] if isinstance(t, dict) and t.get("fertilizer_available") else None
        if op == "FERTILIZE":
            return [op] if isinstance(t, dict) and t.get("kind") == "PLANT" and inv.get("FERTILIZER", 0) > 0 else None
        return None

    # ----------------------------------------------------------------- market
    def market(self, obs, s, day, hour, step):
        """At most 10 orders a turn and one HIRE per order, so slots are budgeted: at the
        start of the day seeds, feed and animals first, hires in the remaining slots, and
        the rest of the hires, seeds and sales over hours 1-3. Investments only with
        tomorrow's wages and feed kept in the bank."""
        from circuit import SELL_ITEMS, BASE, LAND_PRICES, LAST
        me = int(obs["player"]); farm = obs["farms"][me]; priv = obs["private"]
        prices = obs["market"]["prices"]; shed = priv["shed"]
        money = float(farm["money"]); orders = []
        room = lambda: len(orders) < MAXORD
        tours = s.get("tours", [])
        herd = sum(1 for row in farm["tiles"] for t in row if isinstance(t, dict) and "animal" in t)
        final = step >= LAST - 2
        spend = 0.0
        morning = hour <= 3
        # 1. hires: one unit per tour (the farmer takes one)
        if morning:
            have = len(farm["hands"]) + 1
            k = 0
            while have + k < len(tours) and have + k - 1 < P["MAX_HANDS"] and len(orders) < MAXORD - 3 \
                    and spend + fib(int(farm["hires_today"]) + k) <= money - 5:
                spend += fib(int(farm["hires_today"]) + k); k += 1
            orders += [["HIRE"] for _ in range(k)]
        # 2. seeds for today's plantings
        if morning:
            want = {}
            for t in tours:
                for kk, v in t["carry"].items():
                    if kk.startswith("seed:"):
                        want[kk[5:]] = want.get(kk[5:], 0) + v
            for crop, n in sorted(want.items(), key=lambda kv: -CROPS[kv[0]]["seed"]):
                q = min(n - priv["seeds"].get(crop, 0), int(max(0, money - spend - 5) // CROPS[crop]["seed"]))
                if q > 0 and room():
                    orders.append(["BUY_SEED", crop, q]); spend += q * CROPS[crop]["seed"]
        # 3. feed
        wheat = shed.get("WHEAT", 0) + sum(i.get("WHEAT", 0) for i in priv["inventories"])
        need = int(herd * P["FEED_BUFFER"]) + 2 - wheat
        if need > 0 and day < 29 and room():
            q = min(need, int(max(0, money - spend - 5) // max(1, prices["WHEAT"] + 2)))
            if q > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", q]); spend += q * (prices["WHEAT"] + 2)
        # 4. sales with the slots that are left
        for item in SELL_ITEMS:
            if not room():
                break
            q = int(shed.get(item, 0))
            if item == "WHEAT" and not final:
                q -= int(herd * P["FEED_BUFFER"]) + 2
            if item == "FERTILIZER" and not final:
                q -= sum(t["carry"].get("FERTILIZER", 0) for t in tours) + 2
            if q <= 0:
                continue
            if not final and prices.get(item, 0) < P["SELL_FRAC"] * BASE[item] and sum(shed.values()) < 70 and day < 28:
                continue
            orders.append(["SELL", item, q])
        # 5. investments with tomorrow's wages and feed kept back
        keep = sum(fib(kk) for kk in range(min(P["MAX_HANDS"], len(tours) + 1))) + herd * (prices.get("WHEAT", 30) + 2) + 50
        free = money - spend - keep
        if hour <= 6:
            for a in ("SHEEP", "COW", "GOOSE"):
                n = sum(t["carry"].get(a, 0) for t in tours)
                q = min(n - shed.get(a, 0), int(max(0, free) // ANIMALS[a]["cost"]))
                if q > 0 and room():
                    orders.append(["BUY_ANIMAL", a, q]); free -= q * ANIMALS[a]["cost"]
        n_extra = len(farm["unlocked_quadrants"]) - 1
        if n_extra < 3 and P["LAND_DAYS"][n_extra] <= day <= 14 and room() and free >= LAND_PRICES[n_extra] + P["LAND_BUFFER"]:
            orders.append(["BUY_LAND"])
        return orders


_PLANNER = Planner()


def agent(observation, configuration=None):
    try:
        return _PLANNER.act(observation, configuration)
    except Exception:
        return {"farmer": ["PASS"], "hands": [], "market": []}
