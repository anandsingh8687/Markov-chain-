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


def _serpentine():
    order = []
    for q, (ax, ay) in (("NW", (4, 4)), ("NE", (5, 4)), ("SW", (4, 5)), ("SE", (5, 5))):
        xs = list(range(4, -1, -1)) if q[1] == "W" else list(range(5, 10))
        ys = list(range(4, -1, -1)) if q[0] == "N" else list(range(5, 10))
        for k, y in enumerate(ys):
            row = xs if k % 2 == 0 else list(reversed(xs))
            order.extend((x, y) for x in row)
    return order


SERP = _serpentine()


def fert_eve(t, day, c, age):
    """Already fertilized through the next production eve (within 3 days)."""
    fu = int(t.get("fertilized_until_day", -1))
    for dd in range(3):
        k = age + dd + 1 - c["fyd"]
        if k >= 0 and k % c["interval"] == 0:
            return fu >= day + dd
    return True


def quad(p):
    return ("N" if p[1] < 5 else "S") + ("W" if p[0] < 5 else "E")


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
        crop = self._design.get(p) or ("WHEAT" if self._owned(p) else None)
        if t is None or (isinstance(t, dict) and t.get("kind") == "WEED"):
            if crop and crop in CROPS and not CROPS[crop]["ongoing"]:
                best = max(("WHEAT", "CARROT"), key=lambda c: self.yield_by_end(c, day) * pr.get(c, 0) - CROPS[c]["seed"])
                if self.yield_by_end(best, day) * pr.get(best, 0) - CROPS[best]["seed"] > \
                        self.yield_by_end(crop, day) * pr.get(crop, 0) - CROPS[crop]["seed"] + 10:
                    crop = best
                gain = self.yield_by_end(crop, day) * pr.get(crop, 0) - CROPS[crop]["seed"]
                if gain > 15 and day <= 27 and self._load + self.CROP_LOAD <= self._capacity:
                    return [(gain * self.DIG_W, "DIG")] if t is not None else [(gain * self.PLANT_W, "PLANT:" + crop)]
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
                # production happens at the refresh ending day D when D+1-planted-fyd is a
                # multiple of interval; the +1 bonus needs watering on D and fertilizer through D
                k0 = age + 1 - c["fyd"]
                eve = k0 >= 0 and k0 % c["interval"] == 0 and k0 // c["interval"] < c["my"] and day < 29
                cover = sum(1 for dd in range(3) if day + dd < 29 and (age + dd + 1 - c["fyd"]) >= 0
                            and (age + dd + 1 - c["fyd"]) % c["interval"] == 0
                            and (age + dd + 1 - c["fyd"]) // c["interval"] < c["my"])
                fprice = self._prices.get("FERTILIZER", 50)
                if cover and not fert_eve(t, day, c, age) and price * cover > fprice and self._fert_ok and not last_day:
                    jobs.append((price * cover - fprice * 0.5, "FERTILIZE"))
                if not watered and not last_day and (cu >= 1 or (eve and fert)) and (prods_left > 0 or y > 0):
                    v = (prods_left + y) * price * self._late if cu >= 1 else price
                    jobs.append((v, "WATER"))
                if y > 0:
                    urgent = last_day or age >= last_prod or y >= 2 or hour >= 16
                    jobs.append((y * price * (1.0 if urgent else 0.4), "HARVEST"))
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
                            jobs.append((future * price * self._late, "WATER"))   # would die tonight
                        elif in_window:
                            jobs.append((price * gain, "WATER"))            # a unit today
                if in_window and not fert and not watered and y + 1 < c["my"] and self._fert_ok and age < c["myd"]:
                    gain_days = min(3, c["myd"] - age + 1, 29 - day + 1)
                    fv = price * min(gain_days, c["my"] - y - 1) - self._prices.get("FERTILIZER", 50) * 0.5
                    if fv > 5:
                        jobs.append((fv, "FERTILIZE"))
        elif "animal" in t:
            a = ANIMALS[t["animal"]]; price = pr.get(a["prod"], 0)
            y = int(t.get("yield_units", 0)); cuf = int(t.get("consecutive_unfed", 0))
            fed, cared = bool(t.get("fed_today")), bool(t.get("cared_today"))
            wheat = pr.get("WHEAT", 40)
            if not last_day:
                worth = price > wheat * 1.05          # the care bonus unit beats the wheat it eats
                if not fed:
                    if cuf >= 1:
                        jobs.append(((a["cost"] + 3 * price) * self._late, "FEED"))
                    elif worth:
                        jobs.append((price - wheat, "FEED"))
                if not cared and (fed or cuf >= 1 or worth):
                    jobs.append((price * 0.9, "CARE"))
            if t.get("fertilizer_available"):
                jobs.append((pr.get("FERTILIZER", 0) * 0.9, "COLLECT_FERTILIZER"))
            if y > 0:
                urgent = last_day or y >= a["held"] - 2 or day >= 28
                jobs.append((y * price * (1.0 if urgent else 0.15), "HARVEST"))
        order = {"FERTILIZE": 0, "DIG": 0, "PLANT": 1, "FEED": 1, "WATER": 2, "CARE": 2, "COLLECT_FERTILIZER": 3, "HARVEST": 4}
        return sorted(jobs, key=lambda j: order.get(j[1].split(":")[0], 5))

    # ---------------------------------------------------------------- dispatch
    ROUTES = True

    def act(self, obs, cfg=None):
        if self.ROUTES:
            return self.act_routes(obs, cfg)
        return self.act_greedy(obs, cfg)

    def _tile_weight(self, farm, p):
        t = farm["tiles"][p[1]][p[0]]
        if isinstance(t, dict) and "animal" in t:
            return 4.0
        if isinstance(t, dict) and t.get("kind") == "PLANT":
            return 1.6
        if self._design.get(p) or (t is None and self._owned(p)) or (isinstance(t, dict) and t.get("kind") == "WEED" and self._owned(p)):
            return 0.6
        return 0.0

    def act_routes(self, obs, cfg=None):
        step = int(obs["step"]); day, hour = divmod(step, 24)
        me = int(obs["player"]); s = self._state(me, step)
        farm = obs["farms"][me]; priv = obs["private"]
        units = [tuple(farm["farmer"])] + [tuple(h) for h in farm["hands"]]
        invs = priv.get("inventories") or []
        shed = dict(priv.get("shed") or {})
        self._prepare(obs, s, farm, shed, invs, day, hour)
        tiles = self._all_jobs(farm, day, hour)
        # (re)cut the serpentine into one stretch per unit when the crew changes
        key = (day, len(units))
        if s.get("seg_key") != key:
            k = len(units)
            qpath = {}
            for p in SERP:
                wgt = self._tile_weight(farm, p)
                if wgt > 0:
                    qpath.setdefault(quad(p), []).append((p, wgt))
            qw = {q: sum(w for _, w in v) for q, v in qpath.items()}
            # units per quadrant: proportional to load, at least one per loaded quadrant if possible
            alloc = {q: 0 for q in qw}
            for _ in range(k):
                q = max(qw, key=lambda q: qw[q] / (alloc[q] + 1)) if qw else None
                if q is None:
                    break
                alloc[q] += 1
            segs = []
            for q, n in alloc.items():
                if n == 0:
                    continue
                path = qpath[q]; tot = sum(w for _, w in path) or 1.0
                parts = [[] for _ in range(n)]; acc = 0.0
                for p, wgt in path:
                    parts[min(n - 1, int(acc / tot * n))].append(p); acc += wgt
                segs.extend(parts)
            while len(segs) < k:
                segs.append([])
            s["segs"] = segs; s["seg_key"] = key; s["ptr"] = [0] * k
        segs, ptr = s["segs"], s["ptr"]
        free = {"WHEAT": int(shed.get("WHEAT", 0)), "FERTILIZER": int(shed.get("FERTILIZER", 0))}
        seeds_free = {k2: int(v) for k2, v in (priv.get("seeds") or {}).items()}
        cmds = []; drop_now = {}; steps_left = LAST - step; helping = set()
        carried_all = sum(int(v) for i in invs if i for v in i.values())
        self._overflow = carried_all + sum(int(v) for v in shed.values()) - (SHED_CAP - 4)
        for i, pos in enumerate(units):
            inv = invs[i] if i < len(invs) else {}
            cargo = sum(int(v) for k2, v in inv.items() if k2 in PRODUCTS and k2 != "WHEAT")
            home = nearest_access(pos); dh = dist(pos, home)
            if cargo and steps_left <= dh + 1:
                w = step_toward(pos, home)
                if w:
                    cmds.append([w]); continue
                cmds.append(["DROP"])
                for k2, v in inv.items():
                    drop_now[k2] = drop_now.get(k2, 0) + int(v)
                continue
            seg = segs[i] if i < len(segs) else []
            feed_left = sum(1 for p in seg if p in tiles and any(o == "FEED" for _, o in tiles[p]))
            fert_left = sum(1 for p in seg if p in tiles and any(o == "FERTILIZE" for _, o in tiles[p]))
            spare = {k2: int(v) - (feed_left if k2 == "WHEAT" else fert_left if k2 == "FERTILIZER" else 0)
                     for k2, v in inv.items() if k2 in PRODUCTS}
            spare = {k2: v for k2, v in spare.items() if v > 0}
            load = sum(spare.values())
            evening = hour >= 20 and self._overflow > 0
            if load and (load >= self.DELIVER_AT or evening or (dh == 0 and load >= 3)):
                w = step_toward(pos, home)
                if w and dh > 0 and (load >= self.DELIVER_AT or evening):
                    cmds.append([w]); continue
                if dh == 0:
                    item = max(spare, key=lambda k2: spare[k2])
                    cmds.append(["PLACE", item, spare[item]])
                    drop_now[item] = drop_now.get(item, 0) + spare[item]
                    continue
            # stock up on wheat / fertilizer for this stretch when at the shed or starting out
            need_w = sum(1 for p in seg if p in tiles and any(o == "FEED" for _, o in tiles[p]))
            need_f = sum(1 for p in seg if p in tiles and any(o == "FERTILIZE" for _, o in tiles[p]))
            if dh == 0 or (dh <= 2 and ptr[i] == 0):
                got = None
                for item, need in (("WHEAT", need_w), ("FERTILIZER", need_f)):
                    have = int(inv.get(item, 0))
                    if need > have and free[item] > 0:
                        n = min(free[item], need - have)
                        w = step_toward(pos, home)
                        if w:
                            got = [w]
                        else:
                            free[item] -= n; got = ["PICKUP", item, n]
                        break
                if got:
                    cmds.append(got); continue
            cmd = None
            n = len(seg)
            for off in range(n):
                j = (ptr[i] + off) % n if n else 0
                p = seg[j]
                jl = tiles.get(p)
                if not jl:
                    continue
                op = None
                for v, o in jl:
                    if o.startswith("PLANT:"):
                        if seeds_free.get(o[6:], 0) > 0:
                            op = o; break
                        continue
                    item = {"FEED": "WHEAT", "FERTILIZE": "FERTILIZER"}.get(o)
                    if item and int(inv.get(item, 0)) <= 0:
                        continue
                    op = o; break
                if op is None:
                    continue
                if steps_left < dist(pos, p) + dist(p, nearest_access(p)) and cargo:
                    continue
                ptr[i] = j
                w = step_toward(pos, p)
                if w:
                    cmd = [w]
                else:
                    if op.startswith("PLANT:"):
                        seeds_free[op[6:]] -= 1; cmd = ["PLANT", op[6:]]
                    else:
                        cmd = [op]
                break
            if cmd is None:
                # nothing left on our stretch: help with the nearest valuable job elsewhere
                bestp = None
                for p, jl in tiles.items():
                    if p in helping:
                        continue
                    for v, o in jl:
                        if o.startswith("PLANT:") or {"FEED": "WHEAT", "FERTILIZE": "FERTILIZER"}.get(o):
                            continue
                        sc = v / (dist(pos, p) + 1) ** 1.5
                        if bestp is None or sc > bestp[0]:
                            bestp = (sc, p, o)
                        break
                if bestp is not None and bestp[0] > 3:
                    helping.add(bestp[1])
                    w = step_toward(pos, bestp[1])
                    cmd = [w] if w else [bestp[2]]
            if cmd is None:
                if cargo and (hour >= 20 or day >= 29):
                    w = step_toward(pos, home)
                    cmd = [w] if w else ["DROP"]
                    if not w:
                        for k2, v in inv.items():
                            drop_now[k2] = drop_now.get(k2, 0) + int(v)
                else:
                    cmd = ["PASS"]
            cmds.append(cmd)
        action = {"farmer": cmds[0] if cmds else ["PASS"], "hands": cmds[1:], "market": []}
        action["market"] = self._orders(obs, s, farm, priv, shed, invs, tiles, day, hour, step, drop_now)
        return action

    def _prepare(self, obs, s, farm, shed, invs, day, hour):
        des = s.setdefault("design", {})
        for y in range(BOARD):
            for x in range(BOARD):
                t = farm["tiles"][y][x]
                if isinstance(t, dict) and t.get("kind") == "PLANT" and not CROPS[t["crop"]]["ongoing"]:
                    des[(x, y)] = t["crop"]
        self._design = des
        self._late = 1.0 + self.LATE_K * hour / 23.0
        self._quads = set(farm.get("unlocked_quadrants") or ["NW"]) | {"NW"}
        n_crop = n_anim = 0
        for row in farm["tiles"]:
            for t in row:
                if isinstance(t, dict) and t.get("kind") == "PLANT":
                    n_crop += 1
                elif isinstance(t, dict) and "animal" in t:
                    n_anim += 1
        self._load = n_crop * self.CROP_LOAD + n_anim * self.ANIMAL_LOAD
        self._capacity = (self.MAX_HANDS + 1) * self.UNIT_TURNS
        self._prices = obs["market"]["prices"]
        self._fert_ok = int(shed.get("FERTILIZER", 0)) + sum(int(i.get("FERTILIZER", 0)) for i in invs if i) > 0 \
            or (day >= 28 and int(obs["market"]["prices"].get("FERTILIZER", 99)) <= 12)

    def _all_jobs(self, farm, day, hour):
        tiles = {}
        for y in range(BOARD):
            for x in range(BOARD):
                j = self.tile_jobs(farm, (x, y), day, hour)
                if j and sum(v for v, _ in j) > 2:
                    tiles[(x, y)] = j
        return tiles

    def _orders(self, obs, s, farm, priv, shed, invs, tiles, day, hour, step, drop_now):
        orders = []
        if hour <= 1 and step < LAST - 4:
            work = sum(self._tile_weight(farm, p) for p in SERP) * 1.6
            need = min(self.MAX_HANDS, max(0, int(-(-work // self.TURNS_PER_HAND)) - 1))
            n = max(0, need - len(farm["hands"]))
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
        return (orders + self.market(obs, s, {"market": []}, drop_now))[:MAXORD]

    def act_greedy(self, obs, cfg=None):
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
        self._late = 1.0 + self.LATE_K * hour / 23.0
        self._quads = set(farm.get("unlocked_quadrants") or ["NW"]) | {"NW"}
        # daily labour load of the farm as it stands, against what the crew can do
        n_crop = n_anim = 0
        for row in farm["tiles"]:
            for t in row:
                if isinstance(t, dict) and t.get("kind") == "PLANT":
                    n_crop += 1
                elif isinstance(t, dict) and "animal" in t:
                    n_anim += 1
        self._load = n_crop * self.CROP_LOAD + n_anim * self.ANIMAL_LOAD
        self._capacity = (self.MAX_HANDS + 1) * self.UNIT_TURNS
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
        # zones: split units over quadrants in proportion to each quadrant's job value
        qval = {}
        for p, jl in tiles.items():
            qval[quad(p)] = qval.get(quad(p), 0) + sum(v for v, _ in jl)
        zone = {}
        if qval:
            tot = sum(qval.values()) or 1
            order = sorted(qval, key=lambda q: -qval[q])
            quota = {q: max(1, round(len(units) * qval[q] / tot)) for q in order}
            k = 0
            for q in order:
                for _ in range(quota[q]):
                    if k < len(units):
                        zone[k] = q; k += 1
        claimed = set()
        # pass 1: units walking to a still-valid target keep it
        prev = s.get("tgt", {})
        for i, pos in enumerate(units):
            p = prev.get(i)
            if p is not None and p in tiles and p != pos and p not in claimed:
                claimed.add(p)
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
            keep = prev.get(i)
            if keep is not None and keep in tiles and keep != pos:
                claimed.discard(keep)          # our own reservation
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
                sc = pr / (d + 1) ** self.DIST_EXP
                if zone.get(i) is not None and quad(p) != zone[i]:
                    sc *= 0.5
                if keep == p:
                    sc *= 3.0          # finish the walk already started
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

    MAX_HANDS = 11
    PLANT_W = 0.8
    FERT_KEEP = 40
    DELIVER_AT = 40
    LATE_K = 3.0
    CROP_LOAD = 2.5
    ANIMAL_LOAD = 5.0
    UNIT_TURNS = 20
    DIG_W = 0.5

    def _owned(self, p):
        return p not in ((4, 4), (5, 4), (4, 5), (5, 5)) and quad(p) in self._quads
    DIST_EXP = 1.5
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
        carried = sum(int(v) for i in (priv.get("inventories") or []) if i for v in i.values())
        # midnight drop must fit: shed + everything carried <= capacity
        must_free = 0
        if hour >= 19:
            must_free = max(0, sum(int(v) for v in shed.values()) + carried - (SHED_CAP - 4))
        for item in PRODUCTS:
            have = int(shed.get(item, 0))
            if item == "FERTILIZER":
                if day >= 28 and step < LAST - 6:
                    continue
                have = max(0, have - (0 if step >= LAST - 6 else self.FERT_KEEP))
                if have <= 0:
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
                must_free -= q
        if must_free > 0:
            # sell the cheapest-to-give-up units first until the drop fits
            sold = {o[1]: o[2] for o in orders}
            cand = sorted((it for it in PRODUCTS if int(shed.get(it, 0)) - sold.get(it, 0) > 0),
                          key=lambda it: price_at(it, int(inv_mkt.get(it, I0))))
            for it in cand:
                if must_free <= 0:
                    break
                avail = int(shed.get(it, 0)) - sold.get(it, 0)
                q = min(avail, must_free)
                if it in sold:
                    for o in orders:
                        if o[1] == it:
                            o[2] += q
                else:
                    orders.append(["SELL", it, q])
                must_free -= q
        return orders[:MAXORD]
