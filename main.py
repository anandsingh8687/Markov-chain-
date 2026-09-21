"""Kaggriculture agent.

The season is a 720-turn finite-horizon allocation problem over two genuinely
scarce resources -- tile-days and worker-actions -- priced against the shared
order book.

The single fact that reframes the game: the book is *demand rich*.  The town
centre takes one of every product every 24 turns and each of up to eight shop
instances takes one of each of its products every 4 turns, which is on the
order of 120 units/day.  At the production rates a farm can physically reach,
most products therefore sit BELOW the reference inventory I0 for the whole
season, so the quote sits ABOVE base -- and for the hinge-shaped curves
(carrot, egg, tomato) far above it.  Absorption is not the binding constraint;
throughput is.

So allocation equalises marginal revenue per tile-day, with the marginal price
read off the end-of-horizon book rather than the spot quote:

    end_inv(p) = inv(p) + own_pipeline(p) - drain_rate(p) * turns_left

drain_rate is computed from the shops actually unlocked this episode, so the
plan adapts to the draw (no YARN_STORE means wool is worth little, and the
herd cap for sheep collapses accordingly).  Under that valuation a cared cow
or sheep earns ~$260/tile-day against ~$55 for carrot, so the plan is
livestock-led, funded by an opening melon wave and carried by carrot/wheat.

Three invariants keep the plan from eating itself, each of which cost a
rewrite to learn:

  * labour is funded before capital -- a hand costs fib(n)/day and returns 23
    actions, the cheapest capacity in the game;
  * capital is only spent above an operating runway -- an animal that misses
    two consecutive feeds is gone permanently, and cash starvation kills the
    herd faster than any market move;
  * stock and structures are gated on each other, and a unit holding livestock
    places it before doing anything else, so an animal is never stranded.

Liquidation is hard-armed off the horizon: the episode's last agent action is
at step 718 and the final end-of-day drop (step 719) never runs, so anything a
worker is still carrying on day 29 is forfeited.  From that point the agent
harvests, walks to the shed, drops, and sells.
"""
import math

# ---------------------------------------------------------------- game tables
CROPS = {
    "WHEAT":      {"seed": 10,  "fyd": 2,  "myd": 4,  "interval": 0, "my": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "fyd": 2,  "myd": 3,  "interval": 0, "my": 4, "ongoing": False},
    "TOMATO":     {"seed": 50,  "fyd": 8,  "myd": 8,  "interval": 1, "my": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "fyd": 10, "myd": 10, "interval": 2, "my": 4, "ongoing": True},
    "MELON":      {"seed": 80,  "fyd": 10, "myd": 12, "interval": 0, "my": 6, "ongoing": False},
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
PRODUCTS = ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
            "EGG", "MILK", "WOOL", "FERTILIZER"]
# base, T, below_func, below_target, above_func, above_target
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
HINGE_GAIN = 8.0
SHED_CAP = 100          # defaults; overridden from the runner configuration
MAXORD = 10
LAND_PRICES = [1000, 2000, 4000]
FIBCUM = [0, 1, 2, 4, 7, 12, 20, 33, 54, 88, 143, 232, 376, 609, 986, 1596, 2583]

# ---------------------------------------------------------------- tunables
_P = {
    # labour
    "MAX_HANDS": 14, "HIRE_FRAC": 0.16, "HIRE_OFF": 0, "HIRE_WINDOW": 2,
    "ACT_CROP": 1.15, "ACT_ANIMAL": 2.9, "MOVE": 1.85, "PER_RANCHER": 3.5,
    # money
    "RUNWAY": 4.0, "BUY_RATE": 4, "LAND_OPEN": 8, "LAND_LABOR": 1.0,
    # allocation
    "OVERSUPPLY": 1.35, "ANIM_MARGIN": 1.0, "WEED_W": 6.0,
    # logistics
    "SELL_SLOTS": 9, "CARRY_DROP": 11, "WHEAT_BUF": 2.4,
    "PLACE_FIX": 1, "FERT_USE": 1, "ONGOING_FIT": 1,
    # measured and rejected; kept so they are not re-tried (docs section 7)
    "OPP_PIPE": 0.0,        # price the opponent's visible supply into the book
    "DISC": 0.0,            # discount the allocator to the payoff date
    "OPEN_FAST": 0, "OPEN_TD": 6,   # short-cycle-only opening
}
_STRICT = False
try:                                # cloud tooling only; both unset on Kaggle
    import os as _os
    import json as _json
    if _os.environ.get("KG_PARAMS"):
        _P.update(_json.loads(_os.environ["KG_PARAMS"]))
    _STRICT = bool(_os.environ.get("KG_STRICT"))
except Exception:
    pass


def _shape(f, x, T):
    x = max(0.0, x)
    if f == "linear": return x
    if f == "sq":     return x * x
    if f == "sqrt":   return math.sqrt(x)
    if f == "log":    return math.log(1.0 + x)
    if f == "hinge":
        if not T or T <= 0: return x
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price_at(item, inv):
    """The interpreter's quote, un-rounded and un-floored below 1."""
    base, T, bf, bt, af, at = MP[item]
    if inv < I0:
        return max(1.0, base + (bt * base / _shape(bf, T, T)) * _shape(bf, I0 - inv, T))
    return max(1.0, base - (at * base / _shape(af, T, T)) * _shape(af, inv - I0, T))


def _cfg(config, key, default):
    """Read a configuration value from the Struct/dict the runner passes."""
    if config is None:
        return default
    try:
        v = config[key]
    except Exception:
        v = getattr(config, key, None)
    return default if v is None else v


def _d(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _mv(pos, tgt):
    x, y = pos
    tx, ty = tgt
    if x < tx: return "EAST"
    if x > tx: return "WEST"
    if y < ty: return "SOUTH"
    if y > ty: return "NORTH"
    return None


def _plan_onetime(c):
    """(harvest_age, yield, tile_days) maximising yield per tile-day.

    Watering inside the bonus window (from ceil(max_yield_day/2)) adds a unit a
    day, so for melon the best exit is age 10 -- six units, already the cap --
    not the age-12 lifespan limit.
    """
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
    return (d["fyd"], d["my"], d["fyd"] + d["interval"] * (d["my"] - 1) + 2)


def _ongoing_fit(c, days_left):
    """(yield, tile_days) for an ongoing crop planted now, truncated to the horizon.

    Tomato and strawberry pay out in instalments -- one unit per production
    day, `interval` days apart -- so a plant that cannot live out its full
    lifespan is still worth its first few harvests. Valuing them all-or-nothing
    hides that, and silently excludes strawberry from the whole second half of
    the season even while the book is paying three times base for it.
    """
    d = CROPS[c]
    n = 0
    last = 0
    for i in range(d["my"]):
        age = d["fyd"] + i * d["interval"]
        if age + 0.5 > days_left:
            break
        n += 1
        last = age
    if n <= 0:
        return None
    return (n, last + 1.0)


PLAN = dict((c, _plan_ongoing(c) if CROPS[c]["ongoing"] else _plan_onetime(c))
            for c in CROPS)
# units/day from a fed-and-cared animal: the care bonus banked on the
# non-production days is paid out in full on the next production day.
RATE = dict((a, (1.0 + ad["interval"]) / float(ad["interval"]))
            for a, ad in ANIMALS.items())


def drain_rates(shops):
    """Units per turn the town removes from the book, from this episode's draw."""
    r = dict((p, 1.0 / 24.0) for p in PRODUCTS)
    r["FERTILIZER"] = 0.0                      # town centre skips fertilizer
    for name in shops:
        prods = SHOPS.get(name)
        if not prods:
            continue
        mult = 2.0 if len(prods) == 1 else 1.0  # single-product shops pull 2x
        for p in prods:
            r[p] += mult / 4.0
    return r


def _decide(obs, config=None):
    P = _P
    # Everything dimensional is read from the runner's configuration rather
    # than assumed, so a non-default horizon, day length, shed or order cap
    # does not silently mis-arm the liquidation gateway.
    tpd = max(1, int(_cfg(config, "turnsPerDay", 24)))
    total = max(2, int(_cfg(config, "episodeSteps", 720)))
    # The interpreter sets DONE at `step >= episodeSteps - 2`, so this is the
    # last step on which an action is ever applied -- and the end-of-day after
    # it never runs, so anything still carried then is forfeited.
    last_step = total - 2
    shed_cap = int(_cfg(config, "shedCapacity", SHED_CAP))
    maxord = max(1, int(_cfg(config, "maxMarketOrdersPerTurn", MAXORD)))
    me = obs["player"]
    farm = obs["farms"][me]
    priv = obs["private"]
    tiles = farm["tiles"]
    n = len(tiles)
    hf = n // 2
    shed_tiles = [(hf - 1, hf - 1), (hf, hf - 1), (hf - 1, hf), (hf, hf)]
    day, hour = obs["day"], obs["hour"]
    try:
        step = int(obs["step"])
    except Exception:
        step = day * tpd + hour
    left = max(0, last_step - step)
    days_left = left / float(tpd)
    final_day = left <= tpd - 1
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

    # ------------------------------------------------------------- survey
    plants, animals, structs, empties, weeds = [], [], [], [], []
    pipe = dict((p, 0.0) for p in PRODUCTS)
    for y in range(n):
        for x in range(n):
            t = tiles[y][x]
            if t == "LOCKED":
                continue
            if t is None:
                empties.append((x, y))
                continue
            k = t.get("kind")
            if k == "PLANT":
                plants.append(((x, y), t))
                c = t["crop"]
                if CROPS[c]["ongoing"]:
                    pipe[c] += max(t.get("yield_units", 0), PLAN[c][1] * 0.6)
                else:
                    age = day - t["planted_day"]
                    pipe[c] += PLAN[c][1] if age < PLAN[c][0] else t.get("yield_units", 0)
            elif "animal" in t:
                animals.append(((x, y), t))
                a = t["animal"]
                ad = ANIMALS[a]
                ramp = max(0.0, ad["fyd"] - (day - t["placed_day"]))
                pipe[ad["prod"]] += (t.get("yield_units", 0)
                                     + RATE[a] * max(0.0, days_left - ramp))
                pipe["FERTILIZER"] += max(0.0, days_left) * 0.8
            elif k in ("COOP", "PASTURE"):
                structs.append(((x, y), k))
            elif k == "WEED":
                weeds.append((x, y))

    # The opponent's tiles are public (their shed and pockets are not), so the
    # supply they will add to the shared book is partly observable. Folding it
    # into the forward book is a best-response: if they are covering carrot, my
    # marginal carrot price drops and the water-fill moves elsewhere on its own.
    opp_pipe = dict((p2, 0.0) for p2 in PRODUCTS)
    w_opp = P["OPP_PIPE"]
    if w_opp > 0 and len(obs["farms"]) > 1:
        for row in obs["farms"][1 - me]["tiles"]:
            for t in row:
                if not isinstance(t, dict):
                    continue
                if t.get("kind") == "PLANT":
                    c = t.get("crop")
                    if c not in CROPS:
                        continue
                    if CROPS[c]["ongoing"]:
                        opp_pipe[c] += max(t.get("yield_units", 0), PLAN[c][1] * 0.6)
                    else:
                        age = day - t.get("planted_day", day)
                        opp_pipe[c] += (PLAN[c][1] if age < PLAN[c][0]
                                        else t.get("yield_units", 0))
                elif "animal" in t:
                    a = t.get("animal")
                    if a not in ANIMALS:
                        continue
                    ad = ANIMALS[a]
                    ramp = max(0.0, ad["fyd"] - (day - t.get("placed_day", day)))
                    # assume they do not CARE: base rate, not the cared rate
                    opp_pipe[ad["prod"]] += (t.get("yield_units", 0)
                                             + max(0.0, days_left - ramp) / ad["interval"])
    for p2 in PRODUCTS:
        opp_pipe[p2] *= w_opp

    carried = {}
    for iv in invs[:nu]:
        for k2, v in iv.items():
            carried[k2] = carried.get(k2, 0) + v
    for p in PRODUCTS:
        pipe[p] += shed.get(p, 0) + carried.get(p, 0)
    n_animals = len(animals)
    pipe["WHEAT"] -= n_animals * days_left          # feed burn is never sold

    def zk(p):
        return min(_d(p, s) for s in shed_tiles)

    empties.sort(key=zk)
    weeds.sort(key=zk)
    structs.sort(key=lambda e: zk(e[0]))
    open_tiles = len(empties) + len(weeds) + len(structs)

    wheat_buy = price_at("WHEAT", mkt["WHEAT"] - 1)
    marg = dict((p, price_at(p, mkt[p] + pipe[p] + opp_pipe[p] - drain[p] * left))
                for p in PRODUCTS)

    # -------------------------------------------------------- valuation
    add = dict((p, 0.0) for p in PRODUCTS)

    def crop_val(c):
        """Marginal revenue per tile-day of committing one more tile to c."""
        first, yld, td = PLAN[c]
        if CROPS[c]["ongoing"] and P["ONGOING_FIT"]:
            fit = _ongoing_fit(c, days_left)
            if fit is None:
                return None
            yld, td = fit
        elif td + 0.4 > days_left:
            return None
        if day < P["OPEN_FAST"] and td > P["OPEN_TD"]:
            # Optional fast opening: while capital is the binding constraint,
            # restrict the board to short-cycle crops so livestock can be
            # funded sooner.
            return None
        px = price_at(c, mkt[c] + pipe[c] + opp_pipe[c] + add[c] + yld * 0.5
                      - drain[c] * left)
        # Discount to the payoff date. Early capital compounds into livestock,
        # so a dollar at harvest is not a dollar now; with DISC = 0 this is the
        # undiscounted marginal revenue per tile-day.
        return ((yld * px - CROPS[c]["seed"]) / float(td)) * math.exp(-P["DISC"] * first)

    ranked = []
    for c in CROPS:
        v = crop_val(c)
        if v is not None:
            ranked.append((v, c))
    ranked.sort(reverse=True)
    best_crop = ranked[0][1] if ranked else None
    crop_best = ranked[0][0] if ranked else 0.0

    animal_val = {}
    sustain = {}
    for a, ad in ANIMALS.items():
        # Producing much past the town's own draw pushes MILK/WOOL above I0,
        # where their curves (linear 1.6 / sq 3.2) collapse fast.
        sustain[a] = int(drain[ad["prod"]] * 24.0 / RATE[a] * P["OVERSUPPLY"]) + 1
        work = days_left - ad["fyd"]
        if work <= 2.0:
            continue
        pr = ad["prod"]
        vol = RATE[a] * work
        px = price_at(pr, mkt[pr] + pipe[pr] + opp_pipe[pr] + vol * 0.5
                      - drain[pr] * left)
        gross = vol * px + days_left * marg["FERTILIZER"] * 0.7
        animal_val[a] = ((gross - ad["cost"] - wheat_buy * days_left)
                         / max(1.0, days_left)) * math.exp(-P["DISC"] * ad["fyd"])
    best_animal = max(animal_val, key=animal_val.get) if animal_val else None
    animal_best = animal_val.get(best_animal, -1e9) if best_animal else -1e9
    want_animal = (best_animal is not None
                   and animal_best > P["ANIM_MARGIN"] * max(crop_best, 0.0)
                   and days_left > ANIMALS[best_animal]["fyd"] + 2.0)

    # ------------------------------------------------------------ tasks
    atasks, ctasks = [], []
    for (p, t) in animals:
        a = t["animal"]
        ad = ANIMALS[a]
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
            atasks.append((60.0 + marg["FERTILIZER"] * 0.6, p,
                           ["COLLECT_FERTILIZER"], None))

    for (p, t) in plants:
        c = t["crop"]
        d = CROPS[c]
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
        in_win = (not d["ongoing"]) and ws <= age <= d["myd"] and not done
        if not t.get("watered_today", False):
            cu = t.get("consecutive_unwatered", 0)
            if cu >= 1 and days_left > 1.2:
                # Two consecutive dry end-of-days turns the tile into a weed.
                # One dry day is survivable, so outside the bonus window we
                # water every other day and spend the action elsewhere.
                ctasks.append((140.0 + 3.0 * uv, p, ["WATER"], None))
            elif in_win:
                ctasks.append((70.0 + 1.5 * uv, p, ["WATER"], None))
        if (P["FERT_USE"] and in_win and carried.get("FERTILIZER", 0) > 0
                and t.get("fertilized_until_day", -1) < day and age <= d["myd"] - 1):
            # Doubles the watering bonus for three days; the fertilizer itself
            # is a free by-product of the herd.
            ctasks.append((50.0 + 2.0 * uv, p, ["FERTILIZE"], "FERTILIZER"))

    if not final_day:
        for (p, k) in structs:
            for a, ad in ANIMALS.items():
                if ad["struct"] == k:
                    atasks.append((450.0, p, ["PLACE", a], a))
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
                                   ["BUILD_COOP" if k == "COOP" else "BUILD_PASTURE"],
                                   None))
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
            if CROPS[pick]["ongoing"] and P["ONGOING_FIT"]:
                fit = _ongoing_fit(pick, days_left)
                add[pick] += fit[0] if fit else PLAN[pick][1]
            else:
                add[pick] += PLAN[pick][1]      # next tile sees the softer price
            ctasks.append((55.0 + 7.0 * pv, p, ["PLANT", pick], None))
        for p in weeds[:24]:
            ctasks.append((60.0 + P["WEED_W"] * max(crop_best, 0.0), p, ["DIG"], None))

    # --------------------------------------------- roles and assignment
    n_ranch = 0
    if n_animals or any(shed.get(a, 0) + carried.get(a, 0) for a in ANIMALS):
        n_ranch = min(nu, max(1, int(math.ceil(n_animals / P["PER_RANCHER"]))))
    acts = [None] * nu
    claimed_a, claimed_c = set(), set()
    planted = {}
    wheat_shed = shed.get("WHEAT", 0)
    an_shed = dict((a, shed.get(a, 0)) for a in ANIMALS)
    free_struct_kinds = set(k for _, k in structs)
    feed_todo = sum(1 for _, t in animals if not t.get("fed_today"))

    def pick_task(pos, pool, claimed, iv):
        best = None
        for ti, (val, tp, op, need) in enumerate(pool):
            if ti in claimed:
                continue
            if need is not None and iv.get(need, 0) <= 0:
                continue
            if op[0] == "PLANT" and planted.get(op[1], 0) >= seeds.get(op[1], 0):
                continue
            sc = val / (1.0 + _d(pos, tp))
            if best is None or sc > best[0]:
                best = (sc, ti, tp, op)
        return best

    for ui in range(nu):
        pos = units[ui]
        iv = invs[ui]
        ranch = ui < n_ranch
        hold = sum(v for k2, v in iv.items() if k2 in PRODUCTS and k2 != "WHEAT")

        # Carrying livestock overrides everything: an animal left in a pocket
        # earns nothing and the purchase is unrecoverable.
        if P["PLACE_FIX"] and not final_day:
            held = None
            for a in ANIMALS:
                if iv.get(a, 0) > 0:
                    held = a
                    break
            if held is not None:
                tgt, tix = None, None
                for ti, (val, tp, op, need) in enumerate(atasks):
                    if ti in claimed_a or op[0] != "PLACE" or op[1] != held:
                        continue
                    if tgt is None or _d(pos, tp) < _d(pos, tgt):
                        tgt, tix = tp, ti
                if tgt is not None:
                    claimed_a.add(tix)
                    if pos == tgt:
                        acts[ui] = ["PLACE", held]
                    else:
                        mv = _mv(pos, tgt)
                        acts[ui] = [mv] if mv else ["PASS"]
                    continue

        if pos in shed_tiles:
            if hold >= P["CARRY_DROP"] or (final_day and hold > 0):
                acts[ui] = ["DROP"]
                continue
            got = False
            for a in ANIMALS:
                if (an_shed[a] > 0 and iv.get(a, 0) == 0
                        and ANIMALS[a]["struct"] in free_struct_kinds):
                    acts[ui] = ["PICKUP", a, 1]
                    an_shed[a] -= 1
                    got = True
                    break
            if got:
                continue
            if (ranch and not final_day and feed_todo > 0
                    and iv.get("WHEAT", 0) < 3 and wheat_shed > 0):
                take = min(wheat_shed, 7)
                acts[ui] = ["PICKUP", "WHEAT", take]
                wheat_shed -= take
                continue

        best = None
        if ranch:
            best = pick_task(pos, atasks, claimed_a, iv)
            if best is not None:
                claimed_a.add(best[1])
            elif (not final_day and iv.get("WHEAT", 0) < 2
                  and feed_todo > 0 and wheat_shed > 0):
                tgt = min(shed_tiles, key=lambda s: _d(pos, s))
                mv = _mv(pos, tgt)
                acts[ui] = [mv] if mv else ["PASS"]
                continue
        if best is None:
            best = pick_task(pos, ctasks, claimed_c, iv)
            if best is not None:
                claimed_c.add(best[1])
        if best is None and not ranch:
            b2 = pick_task(pos, atasks, claimed_a, iv)
            if b2 is not None:
                claimed_a.add(b2[1])
                best = b2
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

    # ----------------------------------------------------------- market
    orders = []
    sellable = []
    for it in PRODUCTS:
        q = shed.get(it, 0)
        if q <= 0:
            continue
        if it == "WHEAT" and not final_day:
            q = max(0, q - int(n_animals * P["WHEAT_BUF"] + 5))     # keep the feed buffer
            if q <= 0:
                continue
        sellable.append((q * spot.get(it, 1), it, q))
    sellable.sort(reverse=True)
    for _, it, q in sellable[:P["SELL_SLOTS"]]:
        if len(orders) < maxord:
            orders.append(["SELL", it, q])

    own_kind = {}
    for _, t in animals:
        own_kind[t["animal"]] = own_kind.get(t["animal"], 0) + 1

    cash = money
    work_tiles = len(plants) + n_animals + min(len(empties) + len(weeds), 34)
    need_act = (len(plants) * P["ACT_CROP"] + n_animals * P["ACT_ANIMAL"]
                + min(len(empties) + len(weeds), 34) * 1.2) * P["MOVE"]
    hire_target = max(1, min(P["MAX_HANDS"],
                             int(math.ceil(need_act / 23.0)) - P["HIRE_OFF"]))
    while hire_target > 1 and FIBCUM[hire_target] > money * P["HIRE_FRAC"]:
        hire_target -= 1
    done_today = int(farm.get("hires_today", 0) or 0)
    if hour <= P["HIRE_WINDOW"] and not final_day and days_left > 1.2:
        for _ in range(max(0, hire_target - done_today)):
            if len(orders) < maxord:
                orders.append(["HIRE"])
        cash -= max(0.0, FIBCUM[hire_target] - FIBCUM[min(done_today, P["MAX_HANDS"])])

    hire_ref = FIBCUM[min(P["MAX_HANDS"],
                          max(hire_target,
                              int(math.ceil(work_tiles * 1.6 * P["MOVE"] / 23.0))))]
    runway = (hire_ref + n_animals * wheat_buy + 20.0) * P["RUNWAY"] + 150.0

    shed_used = sum(shed.values())
    if not final_day and days_left > 1.5:
        # (1) feed -- never optional
        if n_animals > 0 and len(orders) < maxord:
            have = shed.get("WHEAT", 0) + carried.get("WHEAT", 0)
            want = int(n_animals * P["WHEAT_BUF"] + 5) - have
            buy = min(want, shed_cap - shed_used - 4,
                      int(max(0.0, cash - 40) // max(1.0, wheat_buy)), 50)
            if buy > 0:
                orders.append(["BUY_PRODUCT", "WHEAT", buy])
                cash -= wheat_buy * buy
                shed_used += buy
        # (2) seed the free tiles
        if best_crop and len(orders) < maxord:
            free = len(empties) + len(weeds)
            cst = CROPS[best_crop]["seed"]
            want_n = min(free + 6, 40) - seeds.get(best_crop, 0)
            want_n = min(want_n, int(max(0.0, cash - 40) // cst))
            if want_n > 0:
                orders.append(["BUY_SEED", best_crop, want_n])
                cash -= cst * want_n
        invest = max(0.0, cash - runway)
        # (3) land -- only once the farm is saturated and we can staff the
        #     extra 25 tiles; an idle tile just breeds weeds.
        nx = len(farm["unlocked_quadrants"]) - 1
        if (nx < 3 and len(orders) < maxord and days_left > 6
                and open_tiles <= P["LAND_OPEN"]):
            cost = LAND_PRICES[nx]
            staff = FIBCUM[min(P["MAX_HANDS"],
                               int(math.ceil((work_tiles + 25) * 1.6 * P["MOVE"] / 23.0)))]
            if invest >= cost and cash >= cost + staff * P["LAND_LABOR"] * P["RUNWAY"]:
                orders.append(["BUY_LAND"])
                cash -= cost
                invest -= cost
        # (4) livestock -- gated on a free structure, on labour, on feed and on
        #     the town's own draw for the product.
        if want_animal and len(orders) < maxord:
            qd = dict((a, shed.get(a, 0) + carried.get(a, 0)) for a in ANIMALS)
            qtot = sum(qd.values())
            cap_labor = int(((nu + max(hire_target, 1)) * 23
                             - len(plants) * P["ACT_CROP"] * P["MOVE"])
                            / (P["ACT_ANIMAL"] * P["MOVE"]))
            cap_feed = int(max(0.0, invest) / max(1.0, wheat_buy * max(1.0, days_left)))
            cap_feed += int(sum(PLAN["WHEAT"][1] / float(PLAN["WHEAT"][2])
                                for _, t in plants if t["crop"] == "WHEAT"))
            a = best_animal
            room = min(sustain.get(a, 0) - own_kind.get(a, 0) - qd.get(a, 0),
                       cap_labor - n_animals - qtot,
                       cap_feed - n_animals - qtot,
                       len(structs) + len(empties) - qtot)
            cst = ANIMALS[a]["cost"]
            wantn = min(int(invest // cst), max(0, room), P["BUY_RATE"])
            if wantn > 0 and shed_used + wantn <= shed_cap - 6:
                orders.append(["BUY_ANIMAL", a, wantn])
                cash -= cst * wantn
                shed_used += wantn

    return {"farmer": acts[0] if acts else ["PASS"],
            "hands": [a if a else ["PASS"] for a in acts[1:]],
            "market": orders[:maxord]}


def _safe_action(obs):
    """Whatever else happens, return a well-formed action.

    A raised exception forfeits the episode on the ladder, so the planner is
    never the last line of defence.
    """
    hands = 0
    try:
        hands = len(obs["farms"][obs["player"]]["hands"])
    except Exception:
        hands = 0
    return {"farmer": ["PASS"], "hands": [["PASS"]] * hands, "market": []}


def agent(obs, config=None):
    # `agent` is deliberately the LAST callable defined in this module:
    # kaggle_environments loads a file submission by taking the last callable
    # in the module namespace, so a helper defined below here would silently
    # become the submitted agent.
    if _STRICT:                     # verification: never hide a planner bug
        return _decide(obs, config)
    try:
        return _decide(obs, config)
    except Exception:
        return _safe_action(obs)
