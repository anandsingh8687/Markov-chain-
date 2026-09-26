"""Foreman: an adaptive production planner for Kaggriculture.

Reads the full farm state every turn and decides, from scratch:
  * strategy  -- land, herd and crop investments against demand and cash;
  * labour    -- how many hands to hire, and a global greedy dispatcher that
                 matches units to the most valuable reachable tasks;
  * market    -- seed/animal/feed purchases and a steady sell policy.
"""
import math

BOARD = 10
ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))
LAND_ORDER = ("NE", "SW", "SE")
LAND_PRICES = (1000, 2000, 4000)
MAXORD = 10
LAST = 718                      # last step with an agent action

CROPS = {
    "WHEAT":      dict(seed=10, fyd=2, myd=4, interval=0, my=6, ongoing=False),
    "CARROT":     dict(seed=20, fyd=2, myd=3, interval=0, my=4, ongoing=False),
    "TOMATO":     dict(seed=50, fyd=8, myd=8, interval=1, my=4, ongoing=True),
    "STRAWBERRY": dict(seed=100, fyd=10, myd=10, interval=2, my=4, ongoing=True),
    "MELON":      dict(seed=80, fyd=10, myd=12, interval=0, my=6, ongoing=False),
}
ANIMALS = {
    "GOOSE": dict(cost=300, struct="COOP", fyd=4, interval=1, held=4, prod="EGG"),
    "COW":   dict(cost=400, struct="PASTURE", fyd=8, interval=2, held=6, prod="MILK"),
    "SHEEP": dict(cost=500, struct="PASTURE", fyd=6, interval=3, held=6, prod="WOOL"),
}
PROD_OF = {a: d["prod"] for a, d in ANIMALS.items()}
# base, T, below_func, below_target, above_func, above_target (engine MARKET_PARAMS)
MP = {
    "WHEAT":      (25,  400, "sqrt",   0.80, "log",    0.20),
    "CARROT":     (35,  450, "hinge",  1.00, "sqrt",   0.70),
    "TOMATO":     (60,  200, "hinge",  0.40, "sqrt",   0.60),
    "STRAWBERRY": (120, 100, "sqrt",   0.70, "linear", 1.60),
    "MELON":      (250, 300, "log",    0.20, "sq",     3.60),
    "EGG":        (50,  332, "hinge",  0.40, "log",    0.20),
    "MILK":       (160, 122, "sqrt",   0.60, "linear", 1.60),
    "WOOL":       (200, 105, "log",    0.20, "sq",     3.20),
    "FERTILIZER": (100, 200, "linear", 0.40, "linear", 0.40),
}
I0 = 10000
SHOPS = {
    "BAKERY": ("EGG", "WHEAT"), "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
    "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"), "YARN_STORE": ("WOOL",),
    "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"), "PET_CAFE": ("CARROT",),
    "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
    "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
}

P = {
    "RESERVE": 500,
    "LAND_DAYS": (6, 9, 11),        # earliest day for the 1st/2nd/3rd extra plot
    "LAND_DAY_MAX": 16,
    "LAND_BUFFER": 800,
    "ANIMAL_DAY_MAX": 20,
    "ANIMAL_SHARE": 0.45,           # at most this share of owned tiles holds animals
    "MAX_HANDS": 12,
    "UNIT_CAPACITY": 13.0,          # tasks a unit completes per day, walking included
    "HIRE_VALUE": 240.0,            # hire while the next hand costs less than this
    "SELL_MIN_FRAC": 0.30,
    "FEED_BUFFER": 1.3,
    "OPP_SHARE": 0.5,               # expected rival supply relative to ours
    "CROP_HORIZON_PAD": 0,
}


def fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def step_toward(pos, tgt):
    x, y = pos
    tx, ty = tgt
    if x < tx:
        return "EAST"
    if x > tx:
        return "WEST"
    if y < ty:
        return "SOUTH"
    if y > ty:
        return "NORTH"
    return None


def _shape(f, x, T):
    x = max(0.0, x)
    if f == "linear":
        return x
    if f == "sq":
        return x * x
    if f == "sqrt":
        return math.sqrt(x)
    if f == "log":
        return math.log(1.0 + x)
    if f == "hinge":
        u = x / T
        return u + 8.0 * max(0.0, u - 1.0) ** 2
    return x


def price_at(item, inv):
    base, T, bf, bt, af, at = MP[item]
    if inv < I0:
        return max(1.0, base + (bt * base / _shape(bf, T, T)) * _shape(bf, I0 - inv, T))
    return max(1.0, base - (at * base / _shape(af, T, T)) * _shape(af, inv - I0, T))


def demand_per_day(shops):
    d = {p: 1.0 for p in MP}
    d["FERTILIZER"] = 0.0
    for s in shops:
        items = SHOPS.get(s, ())
        m = 2.0 if len(items) == 1 else 1.0
        for p in items:
            d[p] += 6.0 * m
    return d


def crop_plan(crop, days_left):
    """(harvest_age, units, tile_days) for a crop planted today, or None if it does not fit."""
    c = CROPS[crop]
    if c["ongoing"]:
        n, last = 0, 0
        for i in range(c["my"]):
            age = c["fyd"] + i * c["interval"]
            if age >= days_left:
                break
            n, last = n + 1, age
        return (c["fyd"], n, last + 1) if n else None
    ws = (c["myd"] + 1) // 2
    best = None
    for age in range(c["fyd"], c["myd"] + 1):
        if age >= days_left:
            break
        units = min(c["my"], 1 + max(0, age - ws + 1))
        if best is None or units / float(age + 1) > best[1] / float(best[2]):
            best = (age, units, age + 1)
    return best


TARGET_AGE = {c: crop_plan(c, 99)[0] for c in CROPS if not CROPS[c]["ongoing"]}


class Foreman:
    def __init__(self):
        self.st = {}

    def _state(self, player, step):
        s = self.st.get(player)
        if s is None or step < s["last"]:
            s = self.st[player] = dict(last=-1, design={}, planned={}, targets={}, supply={})
        s["last"] = step
        return s

    # --------------------------------------------------------------- economics
    def future_price(self, obs, prod, our_units, days):
        """Price after `days` of town drain against our (and a mirrored rival's) supply."""
        inv = float(obs["market"]["inventory"].get(prod, I0))
        dem = demand_per_day(obs["town"]["unlocked_shops"])[prod]
        future = inv - dem * days + our_units * (1.0 + P["OPP_SHARE"])
        return price_at(prod, future)

    def choose_crop(self, obs, s, day):
        days_left = 29 - day
        best, bestv = None, 0.0
        for crop in CROPS:
            plan = crop_plan(crop, days_left)
            if not plan:
                continue
            age, units, tdays = plan
            sup = s["supply"].get(crop, 0.0) + units
            price = self.future_price(obs, crop, sup, age + 0.5)
            v = (units * price - CROPS[crop]["seed"]) / float(tdays)
            if v > bestv:
                best, bestv = crop, v
        return best, bestv

    def animal_value(self, obs, s, a, day):
        ad = ANIMALS[a]
        days_left = 29 - day
        prod_days = days_left - ad["fyd"]
        if prod_days <= 1:
            return -1.0
        rate = (1.0 + ad["interval"]) / ad["interval"]
        units = rate * prod_days
        sup = s["supply"].get(ad["prod"], 0.0) + units
        price = self.future_price(obs, ad["prod"], sup, days_left / 2.0)
        feed = float(obs["market"]["prices"].get("WHEAT", 30)) + 3
        fert = 0.35 * float(obs["market"]["prices"].get("FERTILIZER", 40))
        return (units * price + days_left * (fert - feed) - ad["cost"]) / float(days_left)

    # ---------------------------------------------------------------- planning
    def plan(self, obs, s, day):
        me = int(obs["player"])
        tiles = obs["farms"][me]["tiles"]
        # projected supply from what is already growing / grazing
        sup = {}
        herd = {a: 0 for a in ANIMALS}
        for y in range(BOARD):
            for x in range(BOARD):
                t = tiles[y][x]
                if not isinstance(t, dict):
                    continue
                if t.get("kind") == "PLANT":
                    c = t["crop"]
                    plan = crop_plan(c, 99)
                    sup[c] = sup.get(c, 0.0) + (plan[1] if plan else 1)
                elif "animal" in t:
                    a = t["animal"]
                    herd[a] += 1
                    ad = ANIMALS[a]
                    sup[ad["prod"]] = sup.get(ad["prod"], 0.0) + (1.0 + ad["interval"]) / ad["interval"] * max(0, 29 - day)
        for xy, role in s["design"].items():
            t = tiles[xy[1]][xy[0]]
            if role in ANIMALS and not (isinstance(t, dict) and "animal" in t):
                herd[role] += 1
        s["supply"] = sup
        owned = [(x, y) for y in range(BOARD) for x in range(BOARD) if tiles[y][x] != "LOCKED"]
        # drop design entries for tiles that became something else
        for xy in list(s["design"]):
            t = tiles[xy[1]][xy[0]]
            if isinstance(t, dict) and t.get("kind") == "PLANT":
                s["design"].pop(xy)
        free = [xy for xy in owned if tiles[xy[1]][xy[0]] is None and xy not in s["design"]]
        free.sort(key=lambda xy: (min(dist(xy, q) for q in ACCESS), xy))
        # animals, most valuable first, on the tiles nearest the shed
        n_animals = sum(herd.values())
        cap = int(P["ANIMAL_SHARE"] * len(owned))
        if day <= P["ANIMAL_DAY_MAX"]:
            while free and n_animals < cap:
                vals = [(self.animal_value(obs, s, a, day), a) for a in ANIMALS]
                v, a = max(vals)
                crop, cv = self.choose_crop(obs, s, day)
                if v <= max(cv, 0.0) * 1.0 or v <= 0:
                    break
                xy = free.pop(0)
                s["design"][xy] = a
                n_animals += 1
                ad = ANIMALS[a]
                s["supply"][ad["prod"]] = s["supply"].get(ad["prod"], 0.0) + (1.0 + ad["interval"]) / ad["interval"] * max(0, 29 - day - ad["fyd"])
        # crops for everything else
        for xy in list(s["planned"]):
            if tiles[xy[1]][xy[0]] is not None or xy in s["design"]:
                s["planned"].pop(xy)
        for xy in free:
            if xy in s["planned"]:
                continue
            crop, v = self.choose_crop(obs, s, day)
            if not crop:
                continue
            s["planned"][xy] = crop
            plan = crop_plan(crop, 29 - day)
            s["supply"][crop] = s["supply"].get(crop, 0.0) + plan[1]

    # ---------------------------------------------------------------- dispatch
    def tasks(self, obs, s, day, hour, step):
        me = int(obs["player"])
        tiles = obs["farms"][me]["tiles"]
        priv = obs["private"]
        prices = obs["market"]["prices"]
        can_plant = hour <= 20 and day <= 28
        T = []
        for y in range(BOARD):
            for x in range(BOARD):
                t = tiles[y][x]
                if t == "LOCKED":
                    continue
                xy = (x, y)
                if t is None:
                    role = s["design"].get(xy)
                    if role in ANIMALS:
                        T.append([xy, ["BUILD_" + ANIMALS[role]["struct"]], 60.0, None])
                    elif can_plant and xy in s["planned"]:
                        crop = s["planned"][xy]
                        T.append([xy, ["PLANT", crop], 80.0, "SEED:" + crop])
                    continue
                kind = t.get("kind")
                if kind == "WEED":
                    T.append([xy, ["DIG"], 35.0, None])
                elif kind == "PLANT":
                    crop = t["crop"]
                    c = CROPS[crop]
                    age = day - int(t["planted_day"])
                    y_units = int(t.get("yield_units", 0))
                    if not t.get("watered_today") and day < 29:
                        urgent = int(t.get("consecutive_unwatered", 0))
                        T.append([xy, ["WATER"], 120.0 + 200.0 * urgent, None])
                    if y_units > 0:
                        if c["ongoing"]:
                            if age >= c["fyd"]:
                                T.append([xy, ["HARVEST"], 25.0 + prices.get(crop, 30) * y_units, None])
                            done = age >= c["fyd"] + c["interval"] * (c["my"] - 1)
                            if done and y_units == 0:
                                pass
                        else:
                            ta = TARGET_AGE[crop]
                            ripe = (age >= ta and (t.get("watered_today") or age >= c["myd"])) or age > ta or day == 29
                            if ripe and age >= c["fyd"]:
                                T.append([xy, ["HARVEST"], 25.0 + prices.get(crop, 30) * y_units, None])
                    elif c["ongoing"] and age > c["fyd"] + c["interval"] * (c["my"] - 1):
                        # spent ongoing plant: clear it for replanting
                        if day <= 26:
                            T.append([xy, ["DIG"], 30.0, None])
                elif "animal" in t:
                    a = t["animal"]
                    if not t.get("fed_today") and day < 29:
                        T.append([xy, ["FEED"], 160.0 + 200.0 * int(t.get("consecutive_unfed", 0)), "WHEAT"])
                    elif not t.get("cared_today") and day < 28:
                        T.append([xy, ["CARE"], 70.0, None])
                    if int(t.get("yield_units", 0)) > 0:
                        T.append([xy, ["HARVEST"], 25.0 + prices.get(PROD_OF[a], 50) * int(t["yield_units"]), None])
                    if t.get("fertilizer_available"):
                        T.append([xy, ["COLLECT_FERTILIZER"], 8.0 + 0.4 * prices.get("FERTILIZER", 40), None])
                elif kind in ("COOP", "PASTURE"):
                    role = s["design"].get(xy)
                    if role in ANIMALS and ANIMALS[role]["struct"] == kind:
                        T.append([xy, ["PLACE", role], 100.0, "ANIMAL:" + role])
        return T

    # ----------------------------------------------------------- visit routing
    def next_action(self, obs, s, xy, day, hour, inv, seeds):
        """The action a unit standing on xy should take now, or None when the tile is done."""
        me = int(obs["player"])
        t = obs["farms"][me]["tiles"][xy[1]][xy[0]]
        if t == "LOCKED":
            return None
        if t is None:
            role = s["design"].get(xy)
            if role in ANIMALS:
                return ["BUILD_" + ANIMALS[role]["struct"]]
            crop = s["planned"].get(xy)
            if crop and hour <= 21 and day <= 28 and seeds.get(crop, 0) > 0:
                return ["PLANT", crop]
            return None
        kind = t.get("kind")
        if kind == "WEED":
            return ["DIG"]
        if kind == "PLANT":
            crop = t["crop"]
            c = CROPS[crop]
            age = day - int(t["planted_day"])
            yu = int(t.get("yield_units", 0))
            if not t.get("watered_today") and day < 29:
                return ["WATER"]
            if yu > 0 and age >= c["fyd"]:
                if c["ongoing"]:
                    return ["HARVEST"]
                if age >= TARGET_AGE[crop] or day == 29:
                    return ["HARVEST"]
            if c["ongoing"] and yu == 0 and age > c["fyd"] + c["interval"] * (c["my"] - 1) and day <= 26:
                return ["DIG"]
            return None
        if "animal" in t:
            if not t.get("fed_today") and day < 29 and inv.get("WHEAT", 0) > 0:
                return ["FEED"]
            if not t.get("cared_today") and day < 28 and t.get("fed_today"):
                return ["CARE"]
            if int(t.get("yield_units", 0)) > 0:
                return ["HARVEST"]
            if t.get("fertilizer_available"):
                return ["COLLECT_FERTILIZER"]
            return None
        if kind in ("COOP", "PASTURE"):
            role = s["design"].get(xy)
            if role in ANIMALS and ANIMALS[role]["struct"] == kind and inv.get(role, 0) > 0:
                return ["PLACE", role]
        return None

    def workload(self, obs, s, xy, day):
        me = int(obs["player"])
        t = obs["farms"][me]["tiles"][xy[1]][xy[0]]
        if t == "LOCKED":
            return 0
        if t is None:
            if xy in s["design"]:
                return 1
            return 2 if (xy in s["planned"] and day <= 28) else 0
        kind = t.get("kind")
        if kind == "WEED":
            return 1 + (2 if xy in s["planned"] else 0)
        if kind == "PLANT":
            c = CROPS[t["crop"]]
            age = day - int(t["planted_day"])
            w = 0 if t.get("watered_today") or day == 29 else 1
            if not c["ongoing"] and age >= TARGET_AGE[t["crop"]]:
                w += 1 + (2 if day <= 28 else 0)
            elif c["ongoing"] and int(t.get("yield_units", 0)) > 0:
                w += 1
            return w
        if "animal" in t:
            w = 0 if t.get("fed_today") or day >= 29 else 1
            w += 0 if t.get("cared_today") or day >= 28 else 1
            w += 1 if int(t.get("yield_units", 0)) > 0 else 0
            w += 1 if t.get("fertilizer_available") else 0
            return w
        if kind in ("COOP", "PASTURE") and xy in s["design"]:
            return 1
        return 0

    def plan_routes(self, obs, s, day, hour, positions):
        order = []
        for y in range(BOARD):
            xs = range(BOARD) if y % 2 == 0 else range(BOARD - 1, -1, -1)
            for x in xs:
                w = self.workload(obs, s, (x, y), day)
                if w > 0:
                    order.append(((x, y), w))
        n = len(positions)
        routes = [[] for _ in range(n)]
        if not order or not n:
            s["routes"] = routes
            return
        total = sum(w + 1 for _, w in order)
        target = total / float(n)
        chunks, cur, acc = [], [], 0.0
        for xy, w in order:
            cur.append(xy)
            acc += w + 1
            if acc >= target and len(chunks) < n - 1:
                chunks.append(cur)
                cur, acc = [], 0.0
        chunks.append(cur)
        # assign chunks to the nearest free unit
        free = list(range(n))
        for ch in sorted(chunks, key=len, reverse=True):
            if not ch or not free:
                continue
            i = min(free, key=lambda u: dist(positions[u], ch[0]) + dist(positions[u], ch[-1]))
            free.remove(i)
            path = ch if dist(positions[i], ch[0]) <= dist(positions[i], ch[-1]) else ch[::-1]
            routes[i] = list(path)
        s["routes"] = routes

    def dispatch(self, obs, s, day, hour, step):
        me = int(obs["player"])
        farm = obs["farms"][me]
        priv = obs["private"]
        tiles = farm["tiles"]
        positions = [tuple(farm["farmer"])] + [tuple(h) for h in farm["hands"]]
        invs = list(priv["inventories"]) + [{}] * len(positions)
        n = len(positions)
        if s.get("route_day") != (day, n) or hour in (1,):
            if s.get("route_key") != (day, hour, n):
                self.plan_routes(obs, s, day, hour, positions)
                s["route_key"] = (day, hour, n)
                s["route_day"] = (day, n)
        routes = s.get("routes") or [[] for _ in range(n)]
        while len(routes) < n:
            routes.append([])
        shed = dict(priv["shed"])
        seeds = dict(priv["seeds"])
        final_day = day == 29
        commands = [None] * n
        for i, pos in enumerate(positions):
            inv = invs[i]
            home = min(ACCESS, key=lambda a: dist(pos, a))
            cargo = sum(v for k, v in inv.items() if k not in ANIMALS and v > 0)
            if final_day and cargo and step >= LAST - dist(pos, home) - 2:
                mv = step_toward(pos, home)
                commands[i] = [mv] if mv else ["DROP"]
                continue
            route = routes[i]
            # animals this route must feed / place
            need_wheat = sum(1 for xy in route if isinstance(tiles[xy[1]][xy[0]], dict)
                             and "animal" in tiles[xy[1]][xy[0]] and not tiles[xy[1]][xy[0]].get("fed_today")) if day < 29 else 0
            need_animal = {}
            for xy in route:
                t = tiles[xy[1]][xy[0]]
                if isinstance(t, dict) and t.get("kind") in ("COOP", "PASTURE") and "animal" not in t:
                    role = s["design"].get(xy)
                    if role in ANIMALS and ANIMALS[role]["struct"] == t["kind"]:
                        need_animal[role] = need_animal.get(role, 0) + 1
            if need_wheat > inv.get("WHEAT", 0) and shed.get("WHEAT", 0) > 0 and pos in ACCESS:
                q = min(need_wheat - inv.get("WHEAT", 0), shed["WHEAT"])
                shed["WHEAT"] -= q
                commands[i] = ["PICKUP", "WHEAT", q]
                continue
            fetched = False
            for a, k in need_animal.items():
                if inv.get(a, 0) < k and shed.get(a, 0) > 0 and pos in ACCESS:
                    q = min(k - inv.get(a, 0), shed[a])
                    shed[a] -= q
                    commands[i] = ["PICKUP", a, q]
                    fetched = True
                    break
            if fetched:
                continue
            if (need_wheat > inv.get("WHEAT", 0) and shed.get("WHEAT", 0) > 0 and not inv.get("WHEAT", 0)) or \
               any(inv.get(a, 0) < k and shed.get(a, 0) > 0 for a, k in need_animal.items()):
                if dist(pos, home) <= 3:
                    commands[i] = [step_toward(pos, home)]
                    continue
            # work the route
            while route:
                xy = route[0]
                if pos == xy:
                    act = self.next_action(obs, s, xy, day, hour, inv, seeds)
                    if act is None:
                        route.pop(0)
                        continue
                    if act[0] == "PLANT":
                        seeds[act[1]] -= 1
                    commands[i] = act
                    break
                # skip tiles with nothing left to do
                if self.next_action(obs, s, xy, day, hour, inv, seeds) is None and self.workload(obs, s, xy, day) == 0:
                    route.pop(0)
                    continue
                commands[i] = [step_toward(pos, xy)]
                break
            if commands[i] is None:
                commands[i] = ["PASS"]
        s["routes"] = routes
        return commands

    # ------------------------------------------------------------------ labour
    def hires_needed(self, obs, s, day):
        me = int(obs["player"])
        tiles = obs["farms"][me]["tiles"]
        work = 0.0
        for y in range(BOARD):
            for x in range(BOARD):
                t = tiles[y][x]
                if t == "LOCKED":
                    continue
                if t is None:
                    work += 2.0 if ((x, y) in s["design"] or (x, y) in s["planned"]) else 0.0
                elif t.get("kind") == "PLANT":
                    work += 1.3
                elif "animal" in t:
                    work += 3.3
                elif t.get("kind") in ("COOP", "PASTURE"):
                    work += 2.0
                elif t.get("kind") == "WEED":
                    work += 1.0
        units = int(math.ceil(work / P["UNIT_CAPACITY"]))
        k = 0
        while k < min(units - 1, P["MAX_HANDS"]) and fib(k) <= P["HIRE_VALUE"]:
            k += 1
        return k

    # ------------------------------------------------------------------ market
    def market(self, obs, s, day, hour, step):
        me = int(obs["player"])
        farm = obs["farms"][me]
        priv = obs["private"]
        prices = obs["market"]["prices"]
        money = float(farm["money"])
        orders = []
        spend = 0.0

        def room():
            return len(orders) < MAXORD

        herd_now = sum(1 for y in range(BOARD) for x in range(BOARD)
                       if isinstance(farm["tiles"][y][x], dict) and "animal" in farm["tiles"][y][x])
        herd = herd_now + sum(priv["shed"].get(a, 0) for a in ANIMALS)
        if hour == 0 and step < LAST - 12:
            n = self.hires_needed(obs, s, day)
            cost, k = 0, 0
            while k < n and cost + fib(k) <= money - 30:
                cost += fib(k)
                k += 1
            orders += [["HIRE"] for _ in range(k)]
            spend += cost
        wheat = priv["shed"].get("WHEAT", 0) + sum(i.get("WHEAT", 0) for i in priv["inventories"])
        need = int(herd * P["FEED_BUFFER"]) + 2 - wheat
        if need > 0 and day < 29 and room():
            q = min(need, int(max(0, money - spend - 50) // max(1, prices["WHEAT"] + 3)))
            if q > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", q])
                spend += q * (prices["WHEAT"] + 3)
        # seeds for everything planned
        want = {}
        for xy, crop in s["planned"].items():
            want[crop] = want.get(crop, 0) + 1
        for crop in sorted(want, key=lambda c: -want[c]):
            q = want[crop] - priv["seeds"].get(crop, 0)
            cost = CROPS[crop]["seed"]
            q = min(q, int(max(0, money - spend - P["RESERVE"]) // cost))
            if q > 0 and day <= 28 and room():
                orders.append(["BUY_SEED", crop, q])
                spend += q * cost
        # animals for built, empty structures
        if day <= P["ANIMAL_DAY_MAX"] + 2:
            for a in ANIMALS:
                empty = sum(1 for xy, r in s["design"].items() if r == a
                            and isinstance(farm["tiles"][xy[1]][xy[0]], dict)
                            and farm["tiles"][xy[1]][xy[0]].get("kind") == ANIMALS[a]["struct"]
                            and "animal" not in farm["tiles"][xy[1]][xy[0]])
                q = empty - priv["shed"].get(a, 0) - sum(i.get(a, 0) for i in priv["inventories"])
                q = min(q, int(max(0, money - spend - P["RESERVE"]) // ANIMALS[a]["cost"]))
                if q > 0 and room():
                    orders.append(["BUY_ANIMAL", a, q])
                    spend += q * ANIMALS[a]["cost"]
        # land on schedule
        n_extra = len(farm["unlocked_quadrants"]) - 1
        if n_extra < 3 and room() and 1 <= hour <= 18:
            price = LAND_PRICES[n_extra]
            if P["LAND_DAYS"][n_extra] <= day <= P["LAND_DAY_MAX"] and money - spend >= price + P["LAND_BUFFER"]:
                orders.append(["BUY_LAND"])
                spend += price
        # sells: everything above the feed reserve, never below a floor until the end
        final = step >= LAST - 1
        for prod in sorted(MP, key=lambda p: -prices.get(p, 0) * priv["shed"].get(p, 0)):
            if not room():
                break
            q = priv["shed"].get(prod, 0)
            if prod == "WHEAT" and not final:
                q -= int(herd * P["FEED_BUFFER"]) + 2
            if q <= 0:
                continue
            if not final and step < LAST - 24 and prices.get(prod, 0) < P["SELL_MIN_FRAC"] * MP[prod][0]:
                continue
            orders.append(["SELL", prod, int(q)])
        return orders

    # -------------------------------------------------------------------- act
    def act(self, obs, config=None):
        step = int(obs["step"])
        day, hour = step // 24, step % 24
        me = int(obs["player"])
        s = self._state(me, step)
        if hour in (0, 6, 12, 18) or not s.get("planned_once"):
            self.plan(obs, s, day)
            s["planned_once"] = True
        cmds = self.dispatch(obs, s, day, hour, step)
        orders = self.market(obs, s, day, hour, step)
        return {"farmer": cmds[0], "hands": cmds[1:], "market": orders}
