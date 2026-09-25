"""Circuit planner (v12 research): an adaptive Kaggriculture agent built from scratch.

Design (see docs/V12.md):
  * Every quadrant's inner corner touches the shed (the only place to pick up and drop
    off). Each unit owns a *zone*: a small set of tiles in one quadrant, worked as a
    circuit that starts at that corner. Zones are sized so the whole day's work fits
    in a unit's turns, so nothing planted is ever left to dry out.
  * A tile only gets a crop or an animal if some zone has room to tend it daily.
  * Investment (land, animals, seeds) and the product mix are decided from the live
    market, the town's shops and the cash on hand.
"""
import math

BOARD = 10
ACCESS = {"NW": (4, 4), "NE": (5, 4), "SW": (4, 5), "SE": (5, 5)}
ACCESS_TILES = set(ACCESS.values())
LAND_ORDER = ("NE", "SW", "SE")
LAND_PRICES = (1000, 2000, 4000)
MAXORD = 10
LAST = 718
MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}

CROPS = {
    "WHEAT":      dict(seed=10, fyd=2, myd=4, interval=0, my=6, ongoing=False),
    "CARROT":     dict(seed=20, fyd=2, myd=3, interval=0, my=4, ongoing=False),
    "TOMATO":     dict(seed=50, fyd=8, myd=8, interval=1, my=4, ongoing=True),
    "STRAWBERRY": dict(seed=100, fyd=10, myd=10, interval=2, my=4, ongoing=True),
    "MELON":      dict(seed=80, fyd=10, myd=12, interval=0, my=6, ongoing=False),
}
ANIMALS = {
    "GOOSE": dict(cost=300, struct="COOP", build="BUILD_COOP", fyd=4, interval=1, prod="EGG"),
    "COW":   dict(cost=400, struct="PASTURE", build="BUILD_PASTURE", fyd=8, interval=2, prod="MILK"),
    "SHEEP": dict(cost=500, struct="PASTURE", build="BUILD_PASTURE", fyd=6, interval=3, prod="WOOL"),
}
BASE = {"WHEAT": 25, "CARROT": 35, "TOMATO": 60, "STRAWBERRY": 120, "MELON": 250,
        "EGG": 50, "MILK": 160, "WOOL": 200, "FERTILIZER": 100}
SELL_ITEMS = ("MELON", "STRAWBERRY", "WOOL", "MILK", "TOMATO", "EGG", "CARROT", "WHEAT", "FERTILIZER")

P = {
    "TURNS": 22,             # work budget per unit-day (spawn, pickups and slack excluded)
    "ANIMAL_OPS": 3.2,       # feed, care, collect fertilizer, product share
    "CROP_OPS": 1.25,        # water daily, plus plant/harvest share
    "MAX_HANDS": 14,
    "RESERVE": 150,
    "FEED_BUFFER": 1.5,
    "SELL_FRAC": 0.55,       # hold a product while its quote is below this share of base
    "LAND_DAYS": (5, 8, 11),
    "WHEAT_PER_ANIMAL": 1.2,
    "LAND_BUFFER": 1500,
}


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def quad_of(x, y):
    return ("N" if y < 5 else "S") + ("W" if x < 5 else "E")


def step_toward(pos, tgt):
    x, y = pos
    if x != tgt[0]:
        return "EAST" if tgt[0] > x else "WEST"
    if y != tgt[1]:
        return "SOUTH" if tgt[1] > y else "NORTH"
    return None


QUAD_TILES = {}
for _q, _a in ACCESS.items():
    tiles = [(x, y) for y in range(BOARD) for x in range(BOARD) if quad_of(x, y) == _q and (x, y) != _a]
    tiles.sort(key=lambda p: (dist(p, _a), p))
    QUAD_TILES[_q] = tiles


def fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def shop_demand(shops):
    d = {}
    for s in shops:
        for item in {"BAKERY": ("EGG", "WHEAT"), "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
                     "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"), "YARN_STORE": ("WOOL", "WOOL"),
                     "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"), "PET_CAFE": ("CARROT", "CARROT"),
                     "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
                     "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY")}[s]:
            d[item] = d.get(item, 0) + 6
    return d


class Planner:
    def __init__(self):
        self.S = {}

    # ------------------------------------------------------------------ state
    def state(self, player, step):
        s = self.S.get(player)
        if s is None or step < s["step"]:
            s = self.S[player] = {"step": -1, "design": {}, "zones": [], "assign": {}, "day": -1}
        s["step"] = step
        return s

    # ----------------------------------------------------------------- design
    def plan_design(self, obs, s, day):
        """Target-driven design: dated asset targets (DSM-like opening, adjusted to the
        town's shops), placed animals-nearest-the-corner, crops beyond."""
        me = int(obs["player"]); farm = obs["farms"][me]
        owned = [q for q in ("NW", "NE", "SW", "SE") if q == "NW" or q in farm["unlocked_quadrants"]]
        design = s["design"]
        dem = shop_demand(obs["town"]["unlocked_shops"])
        # roles of tiles in use; free tiles whose crop is done lose their role
        for q in owned:
            for p in QUAD_TILES[q]:
                t = farm["tiles"][p[1]][p[0]]
                if isinstance(t, dict) and "animal" in t:
                    design[p] = t["animal"]
                elif isinstance(t, dict) and t.get("kind") == "PLANT":
                    design[p] = t["crop"]
                elif isinstance(t, dict) and t.get("kind") in ("PASTURE", "COOP"):
                    pass
                elif design.get(p) in CROPS and (not self.crop_fits(design[p], day) or day > self.plant_until(design[p])):
                    design.pop(p, None)
        tgt = self.targets(day, dem)
        count = {}
        for p, r in design.items():
            count[r] = count.get(r, 0) + 1
        free = []
        for q in owned:
            for p in QUAD_TILES[q]:
                t = farm["tiles"][p[1]][p[0]]
                if p not in design and (t is None or (isinstance(t, dict) and t.get("kind") == "WEED")):
                    free.append((dist(p, ACCESS[q]), q, p))
        free.sort()
        # animals take the tiles nearest a corner, crops the rest
        for role in ("COW", "SHEEP", "GOOSE"):
            while count.get(role, 0) < tgt.get(role, 0) and free:
                _, q, p = free.pop(0)
                design[p] = role; count[role] = count.get(role, 0) + 1
        for role in ("MELON", "STRAWBERRY", "TOMATO", "CARROT", "WHEAT"):
            if not self.crop_fits(role, day) or day > self.plant_until(role):
                continue
            while count.get(role, 0) < tgt.get(role, 0) and free:
                _, q, p = free.pop()
                design[p] = role; count[role] = count.get(role, 0) + 1
        self.build_zones(obs, s, owned)

    def crop_fits(self, crop, day):
        c = CROPS[crop]
        last = c["fyd"] + c["interval"] * (c["my"] - 1) + 1 if c["ongoing"] else c["myd"] + 1
        return day + last <= 29

    def plant_until(self, crop):
        return {"MELON": 3, "STRAWBERRY": 14, "TOMATO": 18, "CARROT": 26, "WHEAT": 25}[crop]

    def targets(self, day, dem):
        milk, wool, egg = dem.get("MILK", 0) > 0, dem.get("WOOL", 0) > 0, dem.get("EGG", 0) > 0
        tomato, carrot = dem.get("TOMATO", 0) > 0, dem.get("CARROT", 0) > 0
        t = {}
        t["COW"] = 2 if day < 6 else (7 if day < 9 else (9 if day < 12 else 11))
        t["SHEEP"] = 3 if day < 6 else (6 if day < 9 else (8 if day < 12 else 10))
        if wool and day >= 6:
            t["SHEEP"] += 2
        if milk and day >= 6:
            t["COW"] += 1
        t["GOOSE"] = 0 if day < 9 else ((4 if egg else 2) + (3 if day >= 12 else 0))
        t["MELON"] = 10
        t["STRAWBERRY"] = 0 if day < 2 else (10 if day < 9 else 20)
        t["TOMATO"] = 10 if (tomato and day >= 9) else 0
        t["WHEAT"] = 9 if day < 6 else (18 if day < 9 else (26 if day < 12 else 34))
        t["CARROT"] = 12 if (carrot and day >= 12) else (4 if day >= 16 else 0)
        herd = t["COW"] + t["SHEEP"] + t["GOOSE"]
        t["WHEAT"] = max(t["WHEAT"], int(herd * P["WHEAT_PER_ANIMAL"]) + 4)
        return t

    # ------------------------------------------------------------------ zones
    def tile_ops(self, role):
        if role in ANIMALS:
            return P["ANIMAL_OPS"]
        if role in CROPS:
            return P["CROP_OPS"]
        return 0.0

    def build_zones(self, obs, s, owned):
        """Split every quadrant's live tiles into circuits that fit a unit's day. A tile
        is live if it holds something or is about to (seed in hand / animal to place)."""
        me = int(obs["player"]); farm = obs["farms"][me]; priv = obs["private"]
        zones = []
        for q in owned:
            tiles = []
            for p in QUAD_TILES[q]:
                r = s["design"].get(p)
                if not r:
                    continue
                t = farm["tiles"][p[1]][p[0]]
                live = isinstance(t, dict) or (r in CROPS and priv["seeds"].get(r, 0) > 0) or (r in ANIMALS)
                if live:
                    tiles.append(p)
            # greedy nearest-neighbour tours from the corner, closed when the day is full
            left = sorted(tiles, key=lambda p: (dist(p, ACCESS[q]), p))
            while left:
                cur, load, last = [], 2.0, ACCESS[q]      # 2: pickup at the corner
                while left:
                    nxt = min(left, key=lambda p: (dist(last, p), p))
                    add = self.tile_ops(s["design"][nxt]) + dist(last, nxt)
                    if cur and load + add > P["TURNS"]:
                        break
                    cur.append(nxt); load += add; last = nxt; left.remove(nxt)
                zones.append({"quad": q, "tiles": cur})
        # zones holding animals are staffed first: an animal unfed for two days escapes
        zones.sort(key=lambda z: -sum(1 for p in z["tiles"] if s["design"].get(p) in ANIMALS))
        s["zones"] = zones

    # ------------------------------------------------------------- execution
    def tile_job(self, obs, s, p, inv, day, hour, seeds):
        """Next operation this unit should do on tile p, or None."""
        me = int(obs["player"]); farm = obs["farms"][me]
        t = farm["tiles"][p[1]][p[0]]
        role = s["design"].get(p)
        if t == "LOCKED" or role is None:
            return None
        if role in ANIMALS:
            a = ANIMALS[role]
            if t is None:
                return [a["build"]]
            if isinstance(t, dict) and t.get("kind") == "WEED":
                return ["DIG"]
            if isinstance(t, dict) and t.get("kind") == a["struct"] and "animal" not in t:
                return ["PLACE", role] if inv.get(role, 0) > 0 else None
            if isinstance(t, dict) and t.get("animal") == role:
                if not t.get("fed_today") and inv.get("WHEAT", 0) > 0:
                    return ["FEED"]
                if not t.get("cared_today"):
                    return ["CARE"]
                if t.get("fertilizer_available"):
                    return ["COLLECT_FERTILIZER"]
                if int(t.get("yield_units", 0)) > 0:
                    return ["HARVEST"]
            return None
        c = CROPS[role]
        if t is None:
            if seeds.get(role, 0) > 0 and self.crop_fits(role, day):
                return ["PLANT", role]
            return None
        if isinstance(t, dict) and t.get("kind") == "WEED":
            return ["DIG"]
        if isinstance(t, dict) and t.get("kind") == "PLANT":
            age = day - int(t.get("planted_day", day))
            y = int(t.get("yield_units", 0))
            if not t.get("watered_today"):
                return ["WATER"]
            if not c["ongoing"]:
                if age >= c["myd"] and y > 0:
                    return ["HARVEST"]
            else:
                done = age > c["fyd"] + c["interval"] * (c["my"] - 1)
                if y >= 3 or (y > 0 and (done or day >= 29)):
                    return ["HARVEST"]
                if done and y == 0:
                    return ["DIG"]
                if inv.get("FERTILIZER", 0) > 0 and c["fyd"] - 1 <= age and int(t.get("fertilized_until_day", -1)) < day:
                    return ["FERTILIZE"]
            return None
        return None

    def zone_needs(self, obs, s, zone):
        me = int(obs["player"]); farm = obs["farms"][me]
        feed = sum(1 for p in zone["tiles"] if isinstance(farm["tiles"][p[1]][p[0]], dict)
                   and "animal" in farm["tiles"][p[1]][p[0]] and not farm["tiles"][p[1]][p[0]].get("fed_today"))
        fert = sum(1 for p in zone["tiles"] if s["design"].get(p) in ("STRAWBERRY", "TOMATO"))
        place = {a: sum(1 for p in zone["tiles"] if s["design"].get(p) == a and isinstance(farm["tiles"][p[1]][p[0]], dict)
                        and farm["tiles"][p[1]][p[0]].get("kind") == ANIMALS[a]["struct"] and "animal" not in farm["tiles"][p[1]][p[0]])
                 for a in ANIMALS}
        return feed, fert, place

    def unit_command(self, obs, s, idx, zone, day, hour, seeds, shed_left):
        me = int(obs["player"]); farm = obs["farms"][me]
        pos = tuple(farm["farmer"] if idx == 0 else farm["hands"][idx - 1])
        inv = obs["private"]["inventories"][idx] if idx < len(obs["private"]["inventories"]) else {}
        home = ACCESS[zone["quad"]]
        st = s["assign"].setdefault(idx, {"loaded": False})
        if not st["loaded"]:
            # stock up at the corner: wheat for feeding, animals to place, fertilizer
            if pos in ACCESS_TILES:
                feed, fert, place = self.zone_needs(obs, s, zone)
                for a, n in place.items():
                    want = min(n, shed_left.get(a, 0)) - inv.get(a, 0)
                    if want > 0:
                        shed_left[a] -= want
                        return ["PICKUP", a, want]
                want = min(feed, shed_left.get("WHEAT", 0)) - inv.get("WHEAT", 0)
                if want > 0:
                    shed_left["WHEAT"] -= want
                    return ["PICKUP", "WHEAT", want]
                want = min(fert, shed_left.get("FERTILIZER", 0)) - inv.get("FERTILIZER", 0)
                if want > 0:
                    shed_left["FERTILIZER"] -= want
                    return ["PICKUP", "FERTILIZER", want]
                st["loaded"] = True
            else:
                mv = step_toward(pos, home)
                return [mv] if mv else ["PASS"]
        jobs = []
        for p in zone["tiles"]:
            job = self.tile_job(obs, s, p, inv, day, hour, seeds)
            if job:
                if job[0] == "PLANT":
                    if seeds.get(job[1], 0) <= 0:
                        continue
                jobs.append((dist(pos, p), p, job))
        if not jobs:
            carried = sum(v for k, v in inv.items() if k not in ("WHEAT", "FERTILIZER") and v > 0)
            if carried and hour >= 12:
                if pos in ACCESS_TILES:
                    return ["DROP"]
                mv = step_toward(pos, home)
                return [mv] if mv else ["PASS"]
            return ["PASS"]
        jobs.sort()
        _, p, job = jobs[0]
        if pos != p:
            return [step_toward(pos, p)]
        if job[0] == "PLANT":
            seeds[job[1]] -= 1
        return job

    def dispatch(self, obs, s, day, hour):
        me = int(obs["player"]); farm = obs["farms"][me]
        n_units = 1 + len(farm["hands"])
        if s["day"] != day:
            s["day"] = day; s["assign"] = {}
        zones = s["zones"]
        seeds = dict(obs["private"]["seeds"])
        shed_left = dict(obs["private"]["shed"])
        cmds = []
        for idx in range(n_units):
            if idx < len(zones):
                cmds.append(self.unit_command(obs, s, idx, zones[idx], day, hour, seeds, shed_left))
            else:
                cmds.append(["PASS"])
        return cmds

    # ----------------------------------------------------------------- market
    def market(self, obs, s, day, hour, step):
        me = int(obs["player"]); farm = obs["farms"][me]; priv = obs["private"]
        prices = obs["market"]["prices"]
        money = float(farm["money"]); spend = 0.0
        orders = []
        room = lambda: len(orders) < MAXORD
        # sells first (they fund the day)
        final = step >= LAST - 2
        shed = priv["shed"]
        herd = sum(1 for row in farm["tiles"] for t in row if isinstance(t, dict) and "animal" in t)
        income = 0.0
        for item in SELL_ITEMS:
            q = int(shed.get(item, 0))
            if item == "WHEAT" and not final:
                q -= int(herd * P["FEED_BUFFER"]) + 2
            if item == "FERTILIZER" and not final:
                q -= sum(1 for r in s["design"].values() if r in ("STRAWBERRY", "TOMATO"))
            if q <= 0 or not room():
                continue
            if not final and prices.get(item, 0) < P["SELL_FRAC"] * BASE[item] and sum(shed.values()) < 70 and day < 28:
                continue
            orders.append(["SELL", item, q]); income += q * prices.get(item, 0) * 0.8
        avail = money + income * 0.5
        wages = sum(fib(k) for k in range(min(P["MAX_HANDS"], max(0, len(s["zones"]) - 1))))
        keep = wages + herd * (prices.get("WHEAT", 30) + 2) * 0.5 + 60
        # hires at the start of the day: one per zone beyond the farmer
        if hour == 0:
            need = min(P["MAX_HANDS"], max(0, len(s["zones"]) - 1))
            k, cost = 0, 0
            while k < need and cost + fib(k) <= avail - 20 and room():
                cost += fib(k); k += 1
            orders += [["HIRE"] for _ in range(k)]
            spend += cost
        # feed
        wheat = shed.get("WHEAT", 0) + sum(i.get("WHEAT", 0) for i in priv["inventories"])
        need = int(herd * P["FEED_BUFFER"]) + 2 - wheat
        if need > 0 and room() and day < 29:
            q = min(need, int(max(0, avail - spend - 30) // max(1, prices["WHEAT"] + 2)))
            if q > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", q]); spend += q * (prices["WHEAT"] + 2)
        # land: the next quadrant once cash allows and the season has time left
        n_extra = len(farm["unlocked_quadrants"]) - 1
        if n_extra < 3 and P["LAND_DAYS"][n_extra] <= day <= 14 and room():
            price = LAND_PRICES[n_extra]
            if avail - spend - keep >= price + P["LAND_BUFFER"]:
                orders.append(["BUY_LAND"]); spend += price
        # animals for empty structures
        for a in ("SHEEP", "COW", "GOOSE"):
            empty = sum(1 for p, r in s["design"].items() if r == a
                        and isinstance(farm["tiles"][p[1]][p[0]], dict)
                        and farm["tiles"][p[1]][p[0]].get("kind") == ANIMALS[a]["struct"]
                        and "animal" not in farm["tiles"][p[1]][p[0]])
            q = empty - shed.get(a, 0) - sum(i.get(a, 0) for i in priv["inventories"])
            q = min(q, int(max(0, avail - spend - keep - P["RESERVE"]) // ANIMALS[a]["cost"]))
            if q > 0 and room() and day <= 20:
                orders.append(["BUY_ANIMAL", a, q]); spend += q * ANIMALS[a]["cost"]
        # seeds for empty crop tiles
        want = {}
        for p, r in s["design"].items():
            if r in CROPS and farm["tiles"][p[1]][p[0]] is None and self.crop_fits(r, day):
                want[r] = want.get(r, 0) + 1
        for crop in sorted(want, key=lambda c: -CROPS[c]["seed"]):
            q = want[crop] - priv["seeds"].get(crop, 0)
            q = min(q, int(max(0, avail - spend - keep * 0.5) // CROPS[crop]["seed"]))
            if q > 0 and room():
                orders.append(["BUY_SEED", crop, q]); spend += q * CROPS[crop]["seed"]
        return orders

    # -------------------------------------------------------------------- act
    def act(self, obs, config=None):
        step = int(obs["step"]); day, hour = step // 24, step % 24
        s = self.state(int(obs["player"]), step)
        if hour == 0 or not s["zones"]:
            self.plan_design(obs, s, day)
        cmds = self.dispatch(obs, s, day, hour)
        orders = self.market(obs, s, day, hour, step)
        return {"farmer": cmds[0], "hands": cmds[1:], "market": orders}


_PLANNER = Planner()


def agent(observation, configuration=None):
    try:
        return _PLANNER.act(observation, configuration)
    except Exception:
        return {"farmer": ["PASS"], "hands": [], "market": []}
