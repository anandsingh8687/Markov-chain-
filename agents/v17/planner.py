"""v17 planner: an adaptive Kaggriculture farm manager (private research agent).

Built from the engine's exact rules:
  * crops: a new plant must be watered on its planting day; non-ongoing crops
    (wheat, carrot, melon) gain +1 (+2 fertilized) per watered day inside the window
    [ (myd+1)//2, myd ] and must be harvested by the end of day planted+myd; ongoing
    crops (tomato, strawberry) produce at the daily refresh on days fyd, fyd+interval,
    ... (max_yield productions), +2 when watered and fertilized that day.
  * animals: FEED (1 wheat) every day or they escape after two unfed days; CARE on a
    fed day adds +1 to the next production; COLLECT_FERTILIZER once a day.
  * market: exact price curve from the observed market inventory; sales raise the
    inventory (except at $1); shops drain it every 4 turns.
  * hires cost fib(n) for the n-th hire of the day; hands vanish at midnight and
    everything they carry drops into the shed (capacity 100, overflow lost).
  * the reward is money only: everything must be sold by turn 718.

v0 scope: maintain whatever farm exists (tend, harvest, deliver, sell), plus the
end game.  Investment/design come in later versions.
"""
import math

BOARD = 10
LAST = 718
MAXORD = 10
SHED_CAP = 100
ACCESS = ((4, 4), (5, 4), (4, 5), (5, 5))
MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}

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
MARKET = {
    "WHEAT":      dict(base=25, T=400, bf="sqrt", bt=0.80, af="log", at=0.20),
    "CARROT":     dict(base=35, T=450, bf="hinge", bt=1.00, af="sqrt", at=0.70),
    "TOMATO":     dict(base=60, T=200, bf="hinge", bt=0.40, af="sqrt", at=0.60),
    "STRAWBERRY": dict(base=120, T=100, bf="sqrt", bt=0.70, af="linear", at=1.60),
    "MELON":      dict(base=250, T=300, bf="log", bt=0.20, af="sq", at=3.60),
    "EGG":        dict(base=50, T=332, bf="hinge", bt=0.40, af="log", at=0.20),
    "MILK":       dict(base=160, T=122, bf="sqrt", bt=0.60, af="linear", at=1.60),
    "WOOL":       dict(base=200, T=105, bf="log", bt=0.20, af="sq", at=3.20),
    "FERTILIZER": dict(base=100, T=200, bf="linear", bt=0.40, af="linear", at=0.40),
}
I0 = 10000
HINGE_GAIN = 8.0
PRODUCTS = tuple(MARKET)
SHOPS = {
    "BAKERY": ("EGG", "WHEAT"), "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
    "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"), "YARN_STORE": ("WOOL",),
    "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"), "PET_CAFE": ("CARROT",),
    "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
    "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
}


def _shape(f, x, T):
    x = max(0.0, x)
    if f == "linear": return x
    if f == "sq": return x * x
    if f == "sqrt": return math.sqrt(x)
    if f == "log": return math.log(1.0 + x)
    if f == "hinge":
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price_at(item, inv):
    p = MARKET[item]
    if inv < I0:
        amp = p["bt"] * p["base"] / _shape(p["bf"], p["T"], p["T"])
        v = p["base"] + amp * _shape(p["bf"], I0 - inv, p["T"])
    else:
        amp = p["at"] * p["base"] / _shape(p["af"], p["T"], p["T"])
        v = p["base"] - amp * _shape(p["af"], inv - I0, p["T"])
    return max(1, int(round(v)))


def drain_per_day(shops):
    """Units of each product the town removes per day (shops every 4 turns + centre)."""
    d = {p: 1 for p in PRODUCTS if p != "FERTILIZER"}
    d["FERTILIZER"] = 0
    for s in shops:
        items = SHOPS.get(s, ())
        mult = 2 if len(items) == 1 else 1
        for it in items:
            d[it] = d.get(it, 0) + 6 * mult
    return d


def fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def step_toward(pos, tgt):
    if pos[0] != tgt[0]:
        return "EAST" if tgt[0] > pos[0] else "WEST"
    if pos[1] != tgt[1]:
        return "SOUTH" if tgt[1] > pos[1] else "NORTH"
    return None


def nearest_access(pos):
    return min(ACCESS, key=lambda a: (dist(pos, a), a))


class Planner:
    def __init__(self):
        self.S = {}

    # ------------------------------------------------------------------ state
    def _state(self, player, step):
        s = self.S.get(player)
        if s is None or step < s["step"]:
            s = self.S[player] = {"step": -1}
        s["step"] = step
        return s

    def takeover(self, obs):
        pass

    # ------------------------------------------------------------------- jobs
    @staticmethod
    def yield_by_end(crop, day, last=29):
        """Units a non-ongoing crop planted today yields if harvested by the last day."""
        c = CROPS[crop]
        h = min(day + c["myd"], last)
        ws = day + (c["myd"] + 1) // 2
        n = max(0, h - ws + 1)
        return min(c["my"], 1 + n)

    def tile_jobs(self, farm, p, day, hour):
        """[(dollar value, op)] for tile p right now, best first.

        Values are what the action earns or saves at current prices.  Engine facts:
        non-ongoing crops gain a unit per watered day inside their window and must be
        harvested by day planted+myd; ongoing crops produce whether watered or not
        (watering only prevents death at 2 dry days, and enables the fertilizer
        bonus); animals produce their base unit unfed (FEED prevents escape at 2
        unfed days; FEED+CARE on the same day banks +1 for the next production)."""
        t = farm["tiles"][p[1]][p[0]]
        pr = self._prices
        last_day = day >= 29
        crop = self._design.get(p)
        if t is None or (isinstance(t, dict) and t.get("kind") == "WEED"):
            if crop and crop in CROPS and not CROPS[crop]["ongoing"]:
                gain = self.yield_by_end(crop, day) * pr.get(crop, 0) - CROPS[crop]["seed"]
                if gain > 15 and day <= 27:
                    return [(gain * 0.35, "DIG")] if t is not None else [(gain * 0.5, "PLANT:" + crop)]
            return []
        if not isinstance(t, dict):
            return []
        jobs = []
        if t.get("kind") == "PLANT":
            c = CROPS[t["crop"]]; price = pr.get(t["crop"], 0)
            age = day - int(t.get("planted_day", day))
            y = int(t.get("yield_units", 0)); cu = int(t.get("consecutive_unwatered", 0))
            watered = bool(t.get("watered_today"))
            fert = int(t.get("fertilized_until_day", -1)) >= day
            if c["ongoing"]:
                last_prod = c["fyd"] + c["interval"] * (c["my"] - 1)
                prods_left = 0 if age > last_prod else (c["my"] if age < c["fyd"] else (last_prod - age) // c["interval"] + (0 if (age - c["fyd"]) % c["interval"] == 0 else 1))
                prods_left = max(0, min(prods_left, 29 - day))
                if y > 0:
                    urgent = last_day or age > last_prod or y >= c["my"] - 1
                    jobs.append((y * price * (1.0 if urgent else 0.3), "HARVEST"))
                if not watered and not last_day and cu >= 1 and (prods_left > 0 or y > 0):
                    jobs.append(((prods_left + y) * price, "WATER"))
            else:
                ws = (c["myd"] + 1) // 2
                in_window = ws <= age <= c["myd"]
                gain = 2 if fert else 1
                if last_day:
                    if in_window and not watered and y < c["my"]:
                        if not fert and y + 1 < c["my"] and self._fert_ok:
                            jobs.append((price * 2 - self._prices.get("FERTILIZER", 0), "FERTILIZE"))
                        jobs.append((price * gain, "WATER"))
                    if y > 0 or jobs:
                        jobs.append((y * price + 1, "HARVEST"))
                    return jobs
                if age >= c["myd"]:
                    # ready: water once more (window gain) then harvest today or lose it
                    if in_window and not watered and y < c["my"]:
                        jobs.append((price * gain + y * price, "WATER"))
                    if y > 0 and (watered or hour >= 18 or y >= c["my"]):
                        jobs.append((y * price + 1, "HARVEST"))
                else:
                    if not watered:
                        future = min(c["my"], y + max(0, min(c["myd"], 29 - day + age) - max(age, ws) + 1))
                        if cu >= 1:
                            jobs.append((future * price, "WATER"))          # would die tonight
                        elif in_window:
                            jobs.append((price * gain, "WATER"))            # a unit today
                    if in_window and not fert and not watered and y + 1 < c["my"] and self._fert_ok \
                            and self._prices.get("FERTILIZER", 999) < price * 0.8:
                        jobs.append((price * min(3, c["myd"] - age + 1) - self._prices.get("FERTILIZER", 0), "FERTILIZE"))
        elif "animal" in t:
            a = ANIMALS[t["animal"]]; price = pr.get(a["prod"], 0)
            y = int(t.get("yield_units", 0)); cuf = int(t.get("consecutive_unfed", 0))
            fed, cared = bool(t.get("fed_today")), bool(t.get("cared_today"))
            wheat = pr.get("WHEAT", 40)
            if not last_day:
                if not fed:
                    v = (a["cost"] + 3 * price) if cuf >= 1 else max(0, price - wheat)
                    jobs.append((v, "FEED"))
                if not cared and (fed or cuf >= 0):
                    jobs.append((price * 0.9, "CARE"))
            if t.get("fertilizer_available"):
                jobs.append((pr.get("FERTILIZER", 0) * 0.9, "COLLECT_FERTILIZER"))
            if y > 0:
                urgent = last_day or y >= a["held"] - 1
                jobs.append((y * price * (1.0 if urgent else 0.15), "HARVEST"))
        order = {"FERTILIZE": 0, "DIG": 0, "PLANT": 1, "FEED": 1, "WATER": 2, "CARE": 2, "COLLECT_FERTILIZER": 3, "HARVEST": 4}
        return sorted(jobs, key=lambda j: order.get(j[1].split(":")[0], 5))

    # ---------------------------------------------------------------- dispatch
    def act(self, obs, cfg=None):
        step = int(obs["step"]); day, hour = divmod(step, 24)
        me = int(obs["player"]); s = self._state(me, step)
        farm = obs["farms"][me]; priv = obs["private"]
        units = [tuple(farm["farmer"])] + [tuple(h) for h in farm["hands"]]
        invs = priv.get("inventories") or []
        shed = dict(priv.get("shed") or {})
        self._fert_ok = int(shed.get("FERTILIZER", 0)) + sum(int(i.get("FERTILIZER", 0)) for i in invs if i) > 0 \
            or (day >= 28 and int(obs["market"]["prices"].get("FERTILIZER", 99)) <= 12)
        des = s.setdefault("design", {})
        for y in range(BOARD):
            for x in range(BOARD):
                t = farm["tiles"][y][x]
                if isinstance(t, dict) and t.get("kind") == "PLANT" and not CROPS[t["crop"]]["ongoing"]:
                    des[(x, y)] = t["crop"]
        self._design = des
        self._prices = obs["market"]["prices"]
        # every tile's pending ops
        tiles = {}
        for y in range(BOARD):
            for x in range(BOARD):
                j = self.tile_jobs(farm, (x, y), day, hour)
                if j and sum(v for v, _ in j) > 2:
                    tiles[(x, y)] = j
        free = {"WHEAT": int(shed.get("WHEAT", 0)), "FERTILIZER": int(shed.get("FERTILIZER", 0))}
        seeds_free = {k: int(v) for k, v in (priv.get("seeds") or {}).items()}
        claimed = set()
        cmds = []
        drop_now = {}
        steps_left = LAST - step
        for i, pos in enumerate(units):
            inv = invs[i] if i < len(invs) else {}
            cargo = sum(int(v) for k, v in inv.items() if k in PRODUCTS and k != "WHEAT")
            home = nearest_access(pos); dh = dist(pos, home)
            # deliver before the end of the game / before midnight when the shed may overflow
            must_deliver = cargo and steps_left <= dh + 1
            if must_deliver:
                w = step_toward(pos, home)
                if w:
                    cmds.append([w]); continue
                cmds.append(["DROP"])
                for k, v in inv.items():
                    drop_now[k] = drop_now.get(k, 0) + int(v)
                continue
            # choose a job: value / (distance + 1)
            best = None
            for p, jl in tiles.items():
                if p in claimed:
                    continue
                total = sum(v for v, _ in jl)
                pick = None
                for pr, op in jl:
                    if pr <= 1 and op != "HARVEST":
                        continue
                    if op.startswith("PLANT:"):
                        if seeds_free.get(op[6:], 0) <= 0:
                            continue
                        pick = (pr, op); break
                    need_item = {"FEED": "WHEAT", "FERTILIZE": "FERTILIZER"}.get(op)
                    if need_item and int(inv.get(need_item, 0)) <= 0:
                        if free.get(need_item, 0) > 0:
                            pick = (pr, "PICKUP_" + need_item); break
                        continue
                    pick = (pr, op); break
                if pick is None:
                    continue
                _, op = pick; pr = total
                if op.startswith("PICKUP_"):
                    d = dist(pos, home) + dist(home, p) + 1
                    sc = pr / (d + 1)
                    if best is None or sc > best[0]:
                        best = (sc, p, op)
                    continue
                d = dist(pos, p)
                if steps_left < d + dist(p, nearest_access(p)):
                    continue
                sc = pr / (d + 1)
                if s.get("tgt", {}).get(i) == p:
                    sc *= 1.5          # keep yesterday's-turn target: no oscillation
                if best is None or sc > best[0]:
                    best = (sc, p, op)
            if best is None:
                if cargo and day >= 29:
                    w = step_toward(pos, home)
                    cmds.append([w] if w else ["DROP"])
                    if not w:
                        for k, v in inv.items():
                            drop_now[k] = drop_now.get(k, 0) + int(v)
                else:
                    cmds.append(["PASS"])
                continue
            _, p, op = best
            s.setdefault("tgt", {})[i] = p
            if op.startswith("PLANT:") and not step_toward(pos, p):
                seeds_free[op[6:]] -= 1
                claimed.add(p)
                cmds.append(["PLANT", op[6:]]); continue
            if op.startswith("PICKUP_"):
                item = op[7:]; use = {"WHEAT": "FEED", "FERTILIZER": "FERTILIZE"}[item]
                w = step_toward(pos, home)
                if w:
                    cmds.append([w]); continue
                need = sum(1 for q, jl in tiles.items() if any(o == use for _, o in jl))
                n = max(1, min(free[item], need, 8))
                free[item] -= n
                cmds.append(["PICKUP", item, n]); continue
            claimed.add(p)
            w = step_toward(pos, p)
            cmds.append([w] if w else [op])
        action = {"farmer": cmds[0] if cmds else ["PASS"], "hands": cmds[1:], "market": []}
        orders = []
        # labour: hire at dawn for the day's workload (hands vanish at midnight)
        if hour <= 1 and step < LAST - 4:
            work = sum(len(jl) + 2 for jl in tiles.values())
            need = min(self.MAX_HANDS, max(0, -(-work // self.TURNS_PER_HAND) - 1))
            have = len(farm["hands"])
            n = max(0, need - have)
            money = float(farm["money"]); k = int(farm.get("hires_today", 0))
            while n > 0 and money > fib(k) + 200:
                orders.append(["HIRE"]); money -= fib(k); k += 1; n -= 1
        want_seed = {}
        for jl in tiles.values():
            for _, o in jl:
                if o.startswith("PLANT:"):
                    want_seed[o[6:]] = want_seed.get(o[6:], 0) + 1
        for crop, n in want_seed.items():
            short = n - int((priv.get("seeds") or {}).get(crop, 0))
            if short > 0 and float(farm["money"]) > CROPS[crop]["seed"] * short + 300 and day <= 27:
                orders.append(["BUY_SEED", crop, short])
        if day >= 28 and hour in (0, 1, 2, 12):
            want = sum(1 for jl in tiles.values() if any(o == "FERTILIZE" for _, o in jl))
            have_f = int(shed.get("FERTILIZER", 0)) + sum(int(i.get("FERTILIZER", 0)) for i in invs if i)
            fp = int(obs["market"]["prices"].get("FERTILIZER", 99))
            if want > have_f and fp <= 12 and float(farm["money"]) > 500:
                orders.append(["BUY_PRODUCT", "FERTILIZER", want - have_f])
        action["market"] = (orders + self.market(obs, s, action, drop_now))[:MAXORD]
        return action

    MAX_HANDS = 13
    TURNS_PER_HAND = 14

    # ------------------------------------------------------------------ market
    def market(self, obs, s, action, drop_now):
        step = int(obs["step"]); day, hour = divmod(step, 24)
        me = int(obs["player"]); farm = obs["farms"][me]; priv = obs["private"]
        m = obs["market"]; inv_mkt = dict(m.get("inventory") or {})
        shed = dict(priv.get("shed") or {})
        for k, v in drop_now.items():
            shed[k] = shed.get(k, 0) + v
        orders = []
        steps_left = LAST - step
        drain = drain_per_day(obs["town"]["unlocked_shops"])
        for item in PRODUCTS:
            have = int(shed.get(item, 0))
            if item == "FERTILIZER" and day >= 28 and step < LAST - 6:
                continue
            if item == "WHEAT":
                # keep feed for the herd until the last day
                animals = sum(1 for row in farm["tiles"] for t in row if isinstance(t, dict) and "animal" in t)
                keep = 0 if day >= 29 else animals * 2 + 5
                have = max(0, have - keep)
            if have <= 0:
                continue
            if step >= LAST:
                q = have
            else:
                # reservation price: what the unit would fetch later.  The book recovers by
                # drain/day; spread sales over the remaining time, never below a floor.
                inv0 = int(inv_mkt.get(item, I0))
                hours_left = max(1, steps_left)
                future = price_at(item, inv0 - drain.get(item, 0) * hours_left / 24.0 / 2)
                floor = 0.8 * future if steps_left > 24 else 0.5 * future
                q = 0; cur = inv0
                while q < have and price_at(item, cur) >= max(2, floor):
                    q += 1; cur += 1
            if q > 0:
                orders.append(["SELL", item, q])
        return orders[:MAXORD]
