"""Kaggriculture agent.

Finite-horizon allocator over the two genuinely scarce resources -- tile-days
and worker-actions -- priced against a forward model of the shared order book.

The book is *demand rich*.  The town centre plus up to eight shop instances
remove roughly 120 units/day; at the production rates a farm can actually
reach, most products sit BELOW the reference inventory I0 all season, which
puts the quote ABOVE base and, for the hinge-shaped curves, far above it.  So
the question is never "will the market absorb this", it is "which tile-day and
which worker-action earns most", evaluated at the end-of-horizon book:

    end_inv(p) = inv(p) + own_pipeline(p) - drain_rate(p) * turns_left

Under that valuation a cared cow or sheep is worth ~$260/tile-day against
~$55 for carrot and ~$130 for melon, so the plan is livestock-led.  Structures
and stock are gated on each other so an animal is never stranded in the shed,
and a dedicated rancher pool guarantees the daily feed/care cycle.
"""
import math

CROPS = {
    "WHEAT":      {"seed": 10, "fyd": 2,  "myd": 4,  "interval": 0, "my": 6, "ongoing": False},
    "CARROT":     {"seed": 20, "fyd": 2,  "myd": 3,  "interval": 0, "my": 4, "ongoing": False},
    "TOMATO":     {"seed": 50, "fyd": 8,  "myd": 8,  "interval": 1, "my": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "fyd": 10, "myd": 10, "interval": 2, "my": 4, "ongoing": True},
    "MELON":      {"seed": 80, "fyd": 10, "myd": 12, "interval": 0, "my": 6, "ongoing": False},
}
ANIMALS = {
    "GOOSE": {"cost": 300, "struct": "COOP",    "fyd": 4, "interval": 1, "held": 4, "prod": "EGG"},
    "COW":   {"cost": 400, "struct": "PASTURE", "fyd": 8, "interval": 2, "held": 6, "prod": "MILK"},
    "SHEEP": {"cost": 500, "struct": "PASTURE", "fyd": 6, "interval": 3, "held": 6, "prod": "WOOL"},
}
SHOPS = {
    "BAKERY": ["EGG", "WHEAT"],
    "PIZZA_SHOP": ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT": ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE": ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE": ["CARROT"],
    "SMOOTHIE_SHOP": ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}
PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON", "EGG", "MILK", "WOOL", "FERTILIZER"]
MP = {
    "WHEAT":      (25,  400, "sqrt",  0.80, "log",    0.20),
    "CARROT":     (35,  450, "hinge", 1.00, "sqrt",   0.70),
    "TOMATO":     (60,  200, "hinge", 0.40, "sqrt",   0.60),
    "STRAWBERRY": (120, 100, "sqrt",  0.70, "linear", 1.60),
    "MELON":      (250, 300, "log",   0.20, "sq",     3.60),
    "EGG":        (50,  332, "hinge", 0.40, "log",    0.20),
    "MILK":       (160, 122, "sqrt",  0.60, "linear", 1.60),
    "WOOL":       (200, 105, "log",   0.20, "sq",     3.20),
    "FERTILIZER": (100, 200, "linear", 0.40, "linear", 0.40),
}
I0 = 10000
HG = 8.0
LAST_STEP = 718
SHED_CAP = 100
MAXORD = 10
FIBCUM = [0, 1, 2, 4, 7, 12, 20, 33, 54, 88, 143, 232, 376, 609, 986, 1596, 2583]

_P = {
    "MAX_HANDS": 14,
    "HIRE_FRAC": 0.16,
    "HIRE_OFF": 1,
    "HIRE_WINDOW": 0,
    "SELL_SLOTS": 9,
    "MOVE": 1.85,
    "ACT_CROP": 1.15,
    "ACT_ANIMAL": 2.9,
    "PER_RANCHER": 5.5,
    "CARRY_DROP": 11,
    "RUNWAY": 4.0,
    "OVERSUPPLY": 1.35,
    "BUY_RATE": 4,
    "LAND_OPEN": 8,
    "LAND_LABOR": 1.0,
    "ANIM_MARGIN": 1.0,
    "WEED_W": 7.5,
    "MELON_MIN": 0,
}
try:                                     # cloud parameter search only
    import os as _os, json as _json
    if _os.environ.get("KG_PARAMS"):
        _P.update(_json.loads(_os.environ["KG_PARAMS"]))
except Exception:
    pass

P_MAX_HANDS = int(_P["MAX_HANDS"])
P_HIRE_FRAC = _P["HIRE_FRAC"]
P_HIRE_OFF = int(_P["HIRE_OFF"])
P_HIRE_WINDOW = int(_P["HIRE_WINDOW"])
P_SELL_SLOTS = int(_P["SELL_SLOTS"])
P_MOVE = _P["MOVE"]
P_ACT_CROP = _P["ACT_CROP"]
P_ACT_ANIMAL = _P["ACT_ANIMAL"]
P_PER_RANCHER = _P["PER_RANCHER"]
P_CARRY_DROP = int(_P["CARRY_DROP"])
P_RUNWAY = _P["RUNWAY"]
P_OVERSUPPLY = _P["OVERSUPPLY"]
P_BUY_RATE = int(_P["BUY_RATE"])
P_LAND_OPEN = int(_P["LAND_OPEN"])
P_LAND_LABOR = _P["LAND_LABOR"]
P_ANIM_MARGIN = _P["ANIM_MARGIN"]
P_WEED_W = _P["WEED_W"]
P_RESERVE = 700


def _shape(f, x, T):
    x = max(0.0, x)
    if f == "linear": return x
    if f == "sq":     return x * x
    if f == "sqrt":   return math.sqrt(x)
    if f == "log":    return math.log(1.0 + x)
    if f == "hinge":
        if not T or T <= 0: return x
        u = x / T
        return u + HG * max(0.0, u - 1.0) ** 2
    return x


def price_at(item, inv):
    base, T, bf, bt, af, at = MP[item]
    if inv < I0:
        return max(1.0, base + (bt * base / _shape(bf, T, T)) * _shape(bf, I0 - inv, T))
    return max(1.0, base - (at * base / _shape(af, T, T)) * _shape(af, inv - I0, T))


def _d(a, b): return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _mv(pos, tgt):
    x, y = pos; tx, ty = tgt
    if x < tx: return "EAST"
    if x > tx: return "WEST"
    if y < ty: return "SOUTH"
    if y > ty: return "NORTH"
    return None


def _plan_onetime(c):
    d = CROPS[c]
    ws = (d["myd"] + 1) // 2
    best = None
    for age in range(d["fyd"], d["myd"] + 1):
        y = min(d["my"], 1 + max(0, min(age, d["myd"]) - ws + 1))
        td = age + 1
        if best is None or y / float(td) > best[1] / float(best[2]):
            best = (age, y, td)
    return best


def _plan_ongoing(c):
    d = CROPS[c]
    last = d["fyd"] + d["interval"] * (d["my"] - 1)
    return (d["fyd"], d["my"], last + 2)


PLAN = dict((_c, (_plan_ongoing(_c) if CROPS[_c]["ongoing"] else _plan_onetime(_c)))
            for _c in CROPS)
RATE = dict((a, (1.0 + ad["interval"]) / float(ad["interval"])) for a, ad in ANIMALS.items())


def drain_rates(shops):
    r = dict((p, 1.0 / 24.0) for p in PRODUCTS)
    r["FERTILIZER"] = 0.0
    for name in shops:
        prods = SHOPS.get(name)
        if not prods:
            continue
        mult = 2.0 if len(prods) == 1 else 1.0
        for p in prods:
            r[p] += mult / 4.0
    return r


def agent(obs, config=None):
    me = obs["player"]
    farm = obs["farms"][me]
    priv = obs["private"]
    tiles = farm["tiles"]
    n = len(tiles)
    hlf = n // 2
    shed_tiles = [(hlf - 1, hlf - 1), (hlf, hlf - 1), (hlf - 1, hlf), (hlf, hlf)]
    day, hour = obs["day"], obs["hour"]
    step = day * 24 + hour
    left = max(0, LAST_STEP - step)
    days_left = left / 24.0
    final_day = left <= 23
    money = farm["money"]
    shed = dict(priv["shed"])
    mkt = dict(obs["market"]["inventory"])
    spot = dict(obs["market"]["prices"])
    seeds = dict(priv["seeds"])
    drain = drain_rates(obs["town"].get("unlocked_shops", []))

    units = [tuple(farm["farmer"])] + [tuple(p) for p in farm["hands"]]
    nu = len(units)
    invs = [dict(x) for x in priv["inventories"]]
    while len(invs) < nu:
        invs.append({})

    # ---------------- survey -------------------------------------------
    plants, animals, structs, empties, weeds = [], [], [], [], []
    pipe = dict((p, 0.0) for p in PRODUCTS)
    for y in range(n):
        for x in range(n):
            t = tiles[y][x]
            if t == "LOCKED":
                continue
            if t is None:
                empties.append((x, y)); continue
            k = t.get("kind")
            if k == "PLANT":
                plants.append(((x, y), t))
                c = t["crop"]
                age = day - t["planted_day"]
                if CROPS[c]["ongoing"]:
                    pipe[c] += max(t.get("yield_units", 0), PLAN[c][1] * 0.6)
                else:
                    pipe[c] += PLAN[c][1] if age < PLAN[c][0] else t.get("yield_units", 0)
            elif "animal" in t:
                animals.append(((x, y), t))
                a = t["animal"]; ad = ANIMALS[a]
                ramp = max(0.0, ad["fyd"] - (day - t["placed_day"]))
                pipe[ad["prod"]] += t.get("yield_units", 0) + RATE[a] * max(0.0, days_left - ramp)
                pipe["FERTILIZER"] += max(0.0, days_left) * 0.8
            elif k in ("COOP", "PASTURE"):
                structs.append(((x, y), k))
            elif k == "WEED":
                weeds.append((x, y))
    carried = {}
    for iv in invs[:nu]:
        for k2, v in iv.items():
            carried[k2] = carried.get(k2, 0) + v
    for p in PRODUCTS:
        pipe[p] += shed.get(p, 0) + carried.get(p, 0)
    n_animals = len(animals)
    pipe["WHEAT"] -= n_animals * days_left

    def zk(p): return min(_d(p, s) for s in shed_tiles)
    empties.sort(key=zk); weeds.sort(key=zk)
    structs.sort(key=lambda e: zk(e[0]))
    open_tiles = len(empties) + len(weeds) + len(structs)

    wheat_buy = price_at("WHEAT", mkt["WHEAT"] - 1)
    marg = dict((p, price_at(p, mkt[p] + pipe[p] - drain[p] * left)) for p in PRODUCTS)

    # ---------------- valuation ----------------------------------------
    add = dict((p, 0.0) for p in PRODUCTS)

    def crop_val(c):
        d = CROPS[c]
        first, yld, td = PLAN[c]
        if td + 0.4 > days_left:
            return None
        px = price_at(c, mkt[c] + pipe[c] + add[c] + yld * 0.5 - drain[c] * left)
        return (yld * px - d["seed"]) / float(td)

    crop_rank = []
    for c in CROPS:
        v = crop_val(c)
        if v is not None:
            crop_rank.append((v, c))
    crop_rank.sort(reverse=True)
    best_crop = crop_rank[0][1] if crop_rank else None
    crop_best = crop_rank[0][0] if crop_rank else 0.0

    animal_val = {}
    for a, ad in ANIMALS.items():
        work = days_left - ad["fyd"]
        if work <= 2.0:
            continue
        pr = ad["prod"]
        vol = RATE[a] * work
        px = price_at(pr, mkt[pr] + pipe[pr] + vol * 0.5 - drain[pr] * left)
        gross = vol * px + days_left * marg["FERTILIZER"] * 0.7
        animal_val[a] = (gross - ad["cost"] - wheat_buy * days_left) / max(1.0, days_left)
    # A cared animal of type a adds RATE[a] units/day to the book.  Producing
    # much past the town's own draw pushes MILK/WOOL over I0, where their
    # curves (linear 1.6 / sq 3.2) collapse, so cap the herd near that draw.
    sustain = {}
    for a, ad in ANIMALS.items():
        sustain[a] = int(drain[ad["prod"]] * 24.0 / RATE[a] * P_OVERSUPPLY) + 1
    best_animal = max(animal_val, key=animal_val.get) if animal_val else None
    animal_best = animal_val.get(best_animal, -1e9) if best_animal else -1e9
    want_animal = (best_animal is not None
                   and animal_best > P_ANIM_MARGIN * max(crop_best, 0.0)
                   and days_left > ANIMALS[best_animal]["fyd"] + 2.0)

    # ---------------- tasks --------------------------------------------
    atasks, ctasks = [], []
    for (p, t) in animals:
        a = t["animal"]; ad = ANIMALS[a]
        pv = marg[ad["prod"]]
        yu = t.get("yield_units", 0)
        if not t.get("fed_today") and not final_day and days_left > 1.0:
            atasks.append((400.0, p, ["FEED"], "WHEAT"))
        if yu > 0 and final_day:
            atasks.append((500.0, p, ["HARVEST"], None))
        elif yu >= ad["held"]:
            atasks.append((200.0 + pv, p, ["HARVEST"], None))
        elif yu >= ad["held"] - RATE[a] - 0.4:
            atasks.append((120.0 + pv * 0.5, p, ["HARVEST"], None))
        if not t.get("cared_today") and not final_day and days_left > 1.2:
            atasks.append((150.0 + 2.0 * pv, p, ["CARE"], None))
        if t.get("fertilizer_available") and not final_day and days_left > 1.0:
            atasks.append((60.0 + marg["FERTILIZER"] * 0.6, p, ["COLLECT_FERTILIZER"], None))

    for (p, t) in plants:
        c = t["crop"]; d = CROPS[c]
        age = day - t["planted_day"]
        ws = (d["myd"] + 1) // 2
        uv = marg[c]
        ready = t.get("yield_units", 0) > 0 and age >= d["fyd"]
        done = (not d["ongoing"]) and age >= PLAN[c][0]
        if ready and (done or d["ongoing"] or final_day):
            ctasks.append((80.0 + 6.0 * uv * t["yield_units"] / 4.0, p, ["HARVEST"], None))
            if done:
                continue
        if final_day:
            continue
        if not t.get("watered_today", False):
            cu = t.get("consecutive_unwatered", 0)
            in_win = (not d["ongoing"]) and ws <= age <= d["myd"] and not done
            if cu >= 1 and days_left > 1.2:
                ctasks.append((140.0 + 3.0 * uv, p, ["WATER"], None))
            elif in_win:
                ctasks.append((70.0 + 1.5 * uv, p, ["WATER"], None))

    if not final_day:
        for (p, k) in structs:
            for a, ad in ANIMALS.items():
                if ad["struct"] == k:
                    atasks.append((450.0, p, ["PLACE", a], a))
        # structures: only as many as we intend to stock, newest tiles first
        queued = dict((a, shed.get(a, 0) + carried.get(a, 0)) for a in ANIMALS)
        free_kind = {}
        for _, k in structs:
            free_kind[k] = free_kind.get(k, 0) + 1
        need_struct = {}
        for a, q in queued.items():
            if q <= 0:
                continue
            k = ANIMALS[a]["struct"]
            use = min(q, free_kind.get(k, 0))
            free_kind[k] = free_kind.get(k, 0) - use
            if q - use > 0:
                need_struct[k] = need_struct.get(k, 0) + (q - use)
        if want_animal:
            k = ANIMALS[best_animal]["struct"]
            if free_kind.get(k, 0) + need_struct.get(k, 0) < 2:
                need_struct[k] = need_struct.get(k, 0) + 2
        budget = dict(seeds)
        for p in empties:
            built = False
            for k in list(need_struct):
                if need_struct[k] > 0:
                    need_struct[k] -= 1
                    ctasks.append((190.0, p,
                                   ["BUILD_COOP" if k == "COOP" else "BUILD_PASTURE"], None))
                    built = True
                    break
            if built:
                continue
            pick, pv = None, 0.0
            for c in CROPS:
                if budget.get(c, 0) <= 0:
                    continue
                v = crop_val(c)
                if v is not None and v > pv:
                    pick, pv = c, v
            if pick is None:
                continue
            budget[pick] -= 1
            add[pick] += PLAN[pick][1]
            ctasks.append((55.0 + 7.0 * pv, p, ["PLANT", pick], None))
        for p in weeds[:24]:
            ctasks.append((60.0 + P_WEED_W * max(crop_best, 0.0), p, ["DIG"], None))

    # ---------------- roles + assignment --------------------------------
    n_ranch = 0
    if n_animals or any(shed.get(a, 0) + carried.get(a, 0) for a in ANIMALS):
        n_ranch = min(nu, max(1, int(math.ceil(n_animals / P_PER_RANCHER))))
    acts = [None] * nu
    claimed_a, claimed_c = set(), set()
    planted = {}
    wheat_shed = shed.get("WHEAT", 0)
    an_shed = dict((a, shed.get(a, 0)) for a in ANIMALS)
    free_struct_kinds = set(k for _, k in structs)
    feed_todo = sum(1 for _, t in animals if not t.get("fed_today"))

    def pick(pos, pool, claimed, iv):
        best = None
        for ti, (val, tp, op, need) in enumerate(pool):
            if ti in claimed:
                continue
            if need == "WHEAT" and iv.get("WHEAT", 0) <= 0:
                continue
            if need in ANIMALS and iv.get(need, 0) <= 0:
                continue
            if op[0] == "PLANT" and planted.get(op[1], 0) >= seeds.get(op[1], 0):
                continue
            sc = val / (1.0 + _d(pos, tp))
            if best is None or sc > best[0]:
                best = (sc, ti, tp, op)
        return best

    for ui in range(nu):
        pos = units[ui]; iv = invs[ui]
        ranch = ui < n_ranch
        hold = sum(v for k2, v in iv.items() if k2 in PRODUCTS and k2 != "WHEAT")
        # Carrying livestock overrides everything: an animal left in a pocket
        # earns nothing and the purchase is unrecoverable.
        held_animal = None
        for a in ANIMALS:
            if iv.get(a, 0) > 0:
                held_animal = a; break
        if held_animal is not None and not final_day:
            tgt, tix = None, None
            for ti, (val, tp, op, need) in enumerate(atasks):
                if ti in claimed_a or op[0] != "PLACE" or op[1] != held_animal:
                    continue
                if tgt is None or _d(pos, tp) < _d(pos, tgt):
                    tgt, tix = tp, ti
            if tgt is not None:
                claimed_a.add(tix)
                if pos == tgt:
                    acts[ui] = ["PLACE", held_animal]
                else:
                    mv = _mv(pos, tgt)
                    acts[ui] = [mv] if mv else ["PASS"]
                continue
        if pos in shed_tiles:
            if hold >= P_CARRY_DROP or (final_day and hold > 0):
                acts[ui] = ["DROP"]; continue
            got = False
            for a in ANIMALS:
                if an_shed[a] > 0 and iv.get(a, 0) == 0 and ANIMALS[a]["struct"] in free_struct_kinds:
                    acts[ui] = ["PICKUP", a, 1]; an_shed[a] -= 1; got = True; break
            if got:
                continue
            if ranch and not final_day and feed_todo > 0 and iv.get("WHEAT", 0) < 3 and wheat_shed > 0:
                take = min(wheat_shed, 7)
                acts[ui] = ["PICKUP", "WHEAT", take]; wheat_shed -= take; continue
        best = None
        if ranch:
            best = pick(pos, atasks, claimed_a, iv)
            if best is not None:
                claimed_a.add(best[1])
            elif not final_day and iv.get("WHEAT", 0) < 2 and feed_todo > 0 and wheat_shed > 0:
                tgt = min(shed_tiles, key=lambda s: _d(pos, s))
                mv = _mv(pos, tgt)
                acts[ui] = [mv] if mv else ["PASS"]
                continue
        if best is None:
            best = pick(pos, ctasks, claimed_c, iv)
            if best is not None:
                claimed_c.add(best[1])
        if best is None and not ranch:
            b2 = pick(pos, atasks, claimed_a, iv)
            if b2 is not None:
                claimed_a.add(b2[1]); best = b2
        if best is None:
            tgt = min(shed_tiles, key=lambda s: _d(pos, s))
            if pos == tgt:
                acts[ui] = ["DROP"] if hold > 0 else ["PASS"]
            else:
                mv = _mv(pos, tgt)
                acts[ui] = [mv] if mv else ["PASS"]
            continue
        _, ti, tp, op = best
        if pos == tp:
            acts[ui] = list(op)
            if op[0] == "PLANT":
                planted[op[1]] = planted.get(op[1], 0) + 1
            elif op[0] == "FEED":
                feed_todo -= 1
        else:
            mv = _mv(pos, tp)
            acts[ui] = [mv] if mv else ["PASS"]

    # ---------------- market --------------------------------------------
    orders = []
    # ---- labour first: a hand costs fib(n)/day and returns ~23 actions,
    # which is the cheapest capacity in the game, so it is funded before any
    # capital spend.  Everything else comes out of cash above an operating
    # runway, because an animal that misses two feeds is gone for good.
    own_kind = {}
    for _, t in animals:
        own_kind[t["animal"]] = own_kind.get(t["animal"], 0) + 1
    cash = money
    work_tiles = len(plants) + n_animals + min(len(empties) + len(weeds), 34)
    need_act = (len(plants) * P_ACT_CROP + n_animals * P_ACT_ANIMAL
                + min(len(empties) + len(weeds), 34) * 1.2) * P_MOVE
    hire_target = max(1, min(P_MAX_HANDS, int(math.ceil(need_act / 23.0)) - P_HIRE_OFF))
    while hire_target > 1 and FIBCUM[hire_target] > money * P_HIRE_FRAC:
        hire_target -= 1
    done_today = int(farm.get("hires_today", 0) or 0)
    if hour <= P_HIRE_WINDOW and not final_day and days_left > 1.2:
        for _ in range(max(0, hire_target - done_today)):
            if len(orders) < MAXORD:
                orders.append(["HIRE"])
        cash -= max(0.0, FIBCUM[hire_target] - FIBCUM[min(done_today, P_MAX_HANDS)])
    hire_ref = FIBCUM[min(P_MAX_HANDS,
                          max(hire_target, int(math.ceil(work_tiles * 1.6 * P_MOVE / 23.0))))]
    daily_burn = hire_ref + n_animals * wheat_buy + 20.0
    runway = daily_burn * P_RUNWAY + 150.0

    shed_used = sum(shed.values())
    if not final_day and days_left > 1.5:
        # (1) feed -- never optional
        if n_animals > 0 and len(orders) < MAXORD:
            have = shed.get("WHEAT", 0) + carried.get("WHEAT", 0)
            want = int(n_animals * 2.4 + 5) - have
            buy = min(want, SHED_CAP - shed_used - 4,
                      int(max(0.0, cash - 40) // max(1.0, wheat_buy)), 50)
            if buy > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", buy])
                cash -= wheat_buy * buy; shed_used += buy
        # (2) seed the free tiles
        if best_crop and len(orders) < MAXORD:
            free = len(empties) + len(weeds)
            want_n = min(free + 6, 40) - seeds.get(best_crop, 0)
            cst = CROPS[best_crop]["seed"]
            want_n = min(want_n, int(max(0.0, cash - 40) // cst))
            if want_n > 0:
                orders.append(["BUY_SEED", best_crop, want_n]); cash -= cst * want_n
        invest = max(0.0, cash - runway)
        # (3) land -- only once the present farm is saturated AND we can staff
        #     the extra 25 tiles; idle tiles just breed weeds.
        nx = len(farm["unlocked_quadrants"]) - 1
        if nx < 3 and len(orders) < MAXORD and days_left > 6 and open_tiles <= 8:
            cost = [1000, 2000, 4000][nx]
            staff = FIBCUM[min(P_MAX_HANDS,
                               int(math.ceil((work_tiles + 25) * 1.6 * P_MOVE / 23.0)))]
            if invest >= cost and cash >= cost + staff * P_LAND_LABOR * P_RUNWAY:
                orders.append(["BUY_LAND"]); cash -= cost; invest -= cost
        # (4) livestock -- gated on a free structure, on labour, on feed, and
        #     on the town's own draw for the product.
        if want_animal and len(orders) < MAXORD:
            qd = dict((a, shed.get(a, 0) + carried.get(a, 0)) for a in ANIMALS)
            qtot = sum(qd.values())
            free_slots = len(structs) + len(empties)
            cap_labor = int(((nu + max(hire_target, 1)) * 23
                             - len(plants) * P_ACT_CROP * P_MOVE) / (P_ACT_ANIMAL * P_MOVE))
            cap_feed = int(max(0.0, invest) / max(1.0, wheat_buy * max(1.0, days_left)))
            cap_feed += int(sum(PLAN["WHEAT"][1] / float(PLAN["WHEAT"][2])
                                for _, t in plants if t["crop"] == "WHEAT"))
            a = best_animal
            room = min(sustain.get(a, 0) - own_kind.get(a, 0) - qd.get(a, 0),
                       cap_labor - n_animals - qtot,
                       cap_feed - n_animals - qtot,
                       free_slots - qtot)
            cst = ANIMALS[a]["cost"]
            wantn = min(int(invest // cst), max(0, room), P_BUY_RATE)
            if wantn > 0 and shed_used + wantn <= SHED_CAP - 6:
                orders.append(["BUY_ANIMAL", a, wantn])
                cash -= cst * wantn; shed_used += wantn

    return {"farmer": acts[0] if acts else ["PASS"],
            "hands": [a if a else ["PASS"] for a in acts[1:]],
            "market": orders[:MAXORD]}
