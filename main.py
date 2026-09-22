"""Kaggriculture finite-horizon MDP agent.

Self-contained, stdlib-only. The evaluator exec()s archive-root main.py and
calls agent(obs). An exception or a turn over 1s forfeits the episode.

Derived from the official kaggle-environments interpreter
(kaggle_environments/envs/kaggriculture/kaggriculture.py) and the published
rule tables. No public leaderboard agent was used.

Engine facts this file is built around:
  * FEED consumes WHEAT from the acting worker's inventory, not the shed.
  * FERTILIZE consumes FERTILIZER from the acting worker's inventory.
  * SELL / BUY_ANIMAL / BUY_PRODUCT touch the shed only.
  * PLANT consumes private.seeds; if N workers plant crop C and seeds[C] < N,
    EVERY plant of C that turn is a no-op.
  * Market resolves AFTER farm actions, so seeds bought this turn cannot be
    planted until the next turn.
  * Hired hands appear during the market phase and act from the next turn.
  * NORTH = (0, -1), y grows downward.
  * Melon max_yield_day is 12; first harvest is age 10; cap is 6.
  * Unsold shed/carried goods score zero. Score is bank coins only.
  * Ladder scoring is win/loss/tie; the coin margin is discarded.
"""

from __future__ import annotations

import math
import time

TURNS_PER_DAY = 24
DAYS = 30
HORIZON = TURNS_PER_DAY * DAYS
LIQUIDATION_TURN = 650
BOARD = 10
QUADRANT = 5
SHED_CAPACITY = 100
MAX_MARKET_ORDERS = 10
START_MONEY = 3000
TURN_BUDGET_S = 0.55
CRITICAL = 1.0e6
PRICE_FLOOR = 1.0
MARKET_I0 = 10000

# Engine CROPS / ANIMALS / MARKET_PARAMS / SHOPS / LAND_PRICES verbatim.
CROPS = {
    "WHEAT":      {"seed": 10,  "first": 2,  "max_day": 4,  "interval": 0, "max_yield": 6, "ongoing": False},
    "CARROT":     {"seed": 20,  "first": 2,  "max_day": 3,  "interval": 0, "max_yield": 4, "ongoing": False},
    "TOMATO":     {"seed": 50,  "first": 8,  "max_day": 8,  "interval": 1, "max_yield": 4, "ongoing": True},
    "STRAWBERRY": {"seed": 100, "first": 10, "max_day": 10, "interval": 2, "max_yield": 4, "ongoing": True},
    "MELON":      {"seed": 80,  "first": 10, "max_day": 12, "interval": 0, "max_yield": 6, "ongoing": False},
}

ANIMALS = {
    "GOOSE": {"cost": 300, "structure": "COOP",    "first": 4, "interval": 1, "max_held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "structure": "PASTURE", "first": 8, "interval": 2, "max_held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "structure": "PASTURE", "first": 6, "interval": 3, "max_held": 6, "product": "WOOL"},
}

# Unfertilized one-time caps (engine starts yield_units at 1 and adds the
# watering bonus up to max_yield; without fertilizer wheat peaks at 4, carrot 3).
PLAIN_CAP = {"WHEAT": 4, "CARROT": 3, "MELON": 6, "TOMATO": 4, "STRAWBERRY": 4}

MARKET_PARAMS = {
    "WHEAT":      {"base": 25,  "I0": MARKET_I0, "T": 400, "below": "sqrt",  "bt": 0.80, "above": "log",    "at": 0.20},
    "CARROT":     {"base": 35,  "I0": MARKET_I0, "T": 450, "below": "hinge", "bt": 1.00, "above": "sqrt",   "at": 0.70},
    "TOMATO":     {"base": 60,  "I0": MARKET_I0, "T": 200, "below": "hinge", "bt": 0.40, "above": "sqrt",   "at": 0.60},
    "STRAWBERRY": {"base": 120, "I0": MARKET_I0, "T": 100, "below": "sqrt",  "bt": 0.70, "above": "linear", "at": 1.60},
    "MELON":      {"base": 250, "I0": MARKET_I0, "T": 300, "below": "log",   "bt": 0.20, "above": "sq",     "at": 3.60},
    "EGG":        {"base": 50,  "I0": MARKET_I0, "T": 332, "below": "hinge", "bt": 0.40, "above": "log",    "at": 0.20},
    "MILK":       {"base": 160, "I0": MARKET_I0, "T": 122, "below": "sqrt",  "bt": 0.60, "above": "linear", "at": 1.60},
    "WOOL":       {"base": 200, "I0": MARKET_I0, "T": 105, "below": "log",   "bt": 0.20, "above": "sq",     "at": 3.20},
    "FERTILIZER": {"base": 100, "I0": MARKET_I0, "T": 200, "below": "linear","bt": 0.40, "above": "linear", "at": 0.40},
}

SHOPS = {
    "BAKERY":         ["EGG", "WHEAT"],
    "PIZZA_SHOP":     ["MILK", "TOMATO", "WHEAT"],
    "BRUNCH_SPOT":    ["EGG", "WHEAT", "STRAWBERRY"],
    "YARN_STORE":     ["WOOL"],
    "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"],
    "PET_CAFE":       ["CARROT"],
    "SMOOTHIE_SHOP":  ["STRAWBERRY", "MILK"],
    "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"],
}

LAND_ORDER = ["NE", "SW", "SE"]
LAND_PRICES = (1000, 2000, 4000)
PRODUCTS = tuple(MARKET_PARAMS)
SEED_COST = {c: CROPS[c]["seed"] for c in CROPS}
ANIMAL_COST = {a: ANIMALS[a]["cost"] for a in ANIMALS}
ANIMAL_PRODUCT = {a: ANIMALS[a]["product"] for a in ANIMALS}
ANIMAL_STRUCTURE = {a: ANIMALS[a]["structure"] for a in ANIMALS}

# Tile-days consumed per harvested unit at the planned harvest age.
# Animals assume CARE (base 1 + interval bonus per cycle).
TDPU = {
    "WHEAT": 5.0 / 4.0,
    "CARROT": 4.0 / 3.0,
    "TOMATO": 12.0 / 4.0,
    "STRAWBERRY": 17.0 / 4.0,
    "MELON": 11.0 / 6.0,
    "EGG": 1.0 / 2.0,          # cared goose: ~2 eggs / tile-day in steady state
    "MILK": 2.0 / 3.0,          # cared cow: 1+2=3 / 2 days
    "WOOL": 3.0 / 4.0,          # cared sheep: 1+3=4 / 3 days
    "FERTILIZER": 0.2,
}

# Units a competent opponent puts on the book per tile per remaining day
# if they keep that tile on the same product (replant / ongoing yield).
# Standing stock is already counted; this is the extra FLOW after this cycle.
FLOW_PER_TILE_DAY = {
    "WHEAT": 4.0 / 5.0,
    "CARROT": 3.0 / 4.0,
    "TOMATO": 4.0 / 12.0,
    "STRAWBERRY": 4.0 / 17.0,
    "MELON": 6.0 / 11.0,
    "EGG": 1.4,
    "MILK": 1.5 / 2.0,
    "WOOL": 4.0 / 3.0,
}

SAFE_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}
PREMIUM = frozenset(("MELON", "STRAWBERRY", "MILK", "WOOL"))
STAPLES = frozenset(("WHEAT", "CARROT", "EGG", "FERTILIZER", "TOMATO"))


def remaining_plant_units(tile, day, days_left):
    """Units this public plant will still put on the book before the season ends.

    Counted from plant day 0, not from first_yield-2. A day-0 melon field is
    6 units of future supply even though it is eight days from harvest.
    """
    crop = tile.get("crop")
    spec = CROPS.get(crop)
    if spec is None:
        return 0.0, 0.0
    age = day - int(tile.get("planted_day", day))
    held = float(tile.get("yield_units", 0) or 0)
    if spec["ongoing"]:
        left = 0.0
        interval = max(1, spec["interval"])
        for k in range(spec["max_yield"]):
            prod_age = spec["first"] + k * interval
            if prod_age <= age:
                continue
            if prod_age > age + days_left:
                continue
            left += 1.0
        imminent = held if held > 0 else (1.0 if 0 <= spec["first"] - age <= 2 else 0.0)
        return left + held, imminent
    harvest_age = 10 if crop == "MELON" else spec["max_day"]
    if harvest_age - age > days_left:
        return 0.0, 0.0
    units = held if (held > 0 and age >= spec["first"]) else float(Econ.planned_units(crop))
    imminent = units if age >= spec["first"] - 2 else 0.0
    return units, imminent


def remaining_animal_units(tile, day, days_left):
    animal = tile.get("animal")
    spec = ANIMALS.get(animal)
    if spec is None:
        return 0.0, 0.0, None
    placed = int(tile.get("placed_day", day))
    held = float(tile.get("yield_units", 0) or 0)
    interval = max(1, spec["interval"])
    cycles = 0
    for d in range(max(0, days_left)):
        nxt = day + d + 1
        since = nxt - placed - spec["first"]
        if since >= 0 and since % interval == 0:
            cycles += 1
    # CARE is public as cared_today; assume a competent opponent banks it.
    per = 1.5 if tile.get("cared_today") or tile.get("fed_today") else 1.2
    future = cycles * per
    imminent = held + (per if cycles and days_left <= spec["interval"] + 1 else 0.0)
    return future + held, imminent, spec["product"]


def scan_pipeline(tiles, day):
    """Remaining and imminent book occupancy of a public farm."""
    days_left = max(0, DAYS - day)
    remain = {p: 0.0 for p in PRODUCTS}
    imminent = {p: 0.0 for p in PRODUCTS}
    tiles_of = {p: 0 for p in PRODUCTS}
    if not tiles:
        return remain, imminent, tiles_of
    for row in tiles:
        for t in row:
            if not isinstance(t, dict):
                continue
            if t.get("kind") == "PLANT":
                crop = t.get("crop")
                if crop not in CROPS:
                    continue
                u, im = remaining_plant_units(t, day, days_left)
                remain[crop] = remain.get(crop, 0.0) + u
                imminent[crop] = imminent.get(crop, 0.0) + im
                tiles_of[crop] = tiles_of.get(crop, 0) + 1
            elif t.get("animal") in ANIMALS:
                u, im, prod = remaining_animal_units(t, day, days_left)
                if prod is None:
                    continue
                remain[prod] = remain.get(prod, 0.0) + u
                imminent[prod] = imminent.get(prod, 0.0) + im
                tiles_of[prod] = tiles_of.get(prod, 0) + 1
    return remain, imminent, tiles_of


def pipeline_mark(pipe, inventory):
    """Conservative execution value of a future pipeline against the live book."""
    total = 0.0
    for prod, units in pipe.items():
        if units <= 0 or prod not in MARKET_PARAMS:
            continue
        n = int(min(max(units, 1.0), 40))
        inv = inventory.get(prod, MARKET_I0)
        total += Econ.marginal_revenue(prod, inv, n) * (units / float(n))
    return total


def add_replant_flow(remain, tiles_of, days_left):
    """Standing stock plus expected extra cycles if they keep the tiles.

    A 25-tile carrot farm is not 75 units of current plants. It is a flow:
    ~0.75 carrot / tile-day for the rest of the season. Counting only the
    standing field is how a peer parks on the same book and prints 6k.
    """
    out = {p: float(remain.get(p, 0.0) or 0.0) for p in PRODUCTS}
    extra_days = max(0.0, float(days_left) - 3.0)
    if extra_days <= 0:
        return out
    for prod, n in (tiles_of or {}).items():
        n = int(n or 0)
        if n <= 0:
            continue
        rate = FLOW_PER_TILE_DAY.get(prod)
        if not rate:
            continue
        out[prod] = out.get(prod, 0.0) + n * rate * extra_days
    return out


def intended_crew(st):
    """Farmer + hands we re-hire every morning (engine wipes them at EOD)."""
    usable = int(getattr(st, "usable_tiles", QUADRANT * QUADRANT) or QUADRANT * QUADRANT)
    return 1 + min(12, max(8, (usable + 8) // 5))


def effective_labor(st):
    """Workers the morning mix may assume.

    Hands are wiped at EOD, so at hour 0 the arrived count is the farmer
    alone even though 8-12 HIREs are about to land. Planning the dawn
    mix off that 1 is how the herd reset to four geese every morning
    (when overnight cash is sitting there) and crop_mix collapsed to
    four tiles. Use the crew that will act from hour 1.
    """
    arrived = 1 + len(getattr(st, "hands", []) or [])
    hour = int(getattr(st, "hour", 0) or 0)
    intended = intended_crew(st)
    if hour <= 3 and arrived < intended:
        return intended
    return max(1, arrived)


def goose_cap(st):
    """Eggs absorb, so unconstrained KKT wants every tile as a goose.

    Town drain plus the log glut curve support ~25-30 geese on a
    four-quadrant board. Cap at labour that can FEED them, not at 16
    and not at the hour-0 arrived count of 1.
    """
    usable = int(getattr(st, "usable_tiles", QUADRANT * QUADRANT) or QUADRANT * QUADRANT)
    labor = effective_labor(st)
    by_labor = max(4, labor * 2 - 2)
    by_land = max(4, usable - 8)
    return min(28, by_labor, by_land)


def goose_buy_cap(st, plan=None):
    """Geese must not consume the pasture slots a healthy milk/wool book needs.

    Town draw is ~13 cows / 9 sheep / 7 geese, not 12 geese and nothing
    else. Once cows or sheep are on the plan, stop buying geese at 8.
    """
    cap = goose_cap(st)
    pasture = False
    if plan is not None:
        pasture = (
            int(plan.animal_targets.get("COW", 0) or 0)
            + int(plan.animal_targets.get("SHEEP", 0) or 0)
        ) > 0
    return min(6 if pasture else 12, cap)


def book_tiles(st, prod, frac=0.50):
    """How many tiles the live book can still take at `frac * base`.

    Melon has no shop. Town-centre drain is 1/day, so a 12-tile melon
    block walks the quote to $7. Size the field from remaining headroom,
    not from base price.
    """
    params = MARKET_PARAMS.get(prod)
    if not params:
        return 0
    inv = (getattr(st, "inventory", None) or {}).get(prod, MARKET_I0)
    floor = max(1.0, float(frac) * params["base"])
    if Econ.price(prod, inv) < floor:
        return 0
    head = Econ.units_until(prod, inv, floor)
    days = max(1, DAYS - int(getattr(st, "day", 0) or 0))
    rate = FLOW_PER_TILE_DAY.get(prod, 1.0)
    return max(0, int(math.floor(head / max(1.0, rate * float(days)))))


def pasture_cap(st, product):
    """Milk and wool crash. Size cows/sheep to headroom PLUS town/shop drain.

    An I0 fill at 0.55×base is ~2-3 cows because it ignores regen. Town-centre
    drain is 1/day even with zero shops; pizza/ice-cream/smoothie and the
    yarn store multiply that. Subtract opponent flow so we do not walk a
    contested book. Cap at labour that can FEED, not at a flat 6.
    """
    params = MARKET_PARAMS.get(product)
    if not params:
        return 0
    inv = (getattr(st, "inventory", None) or {}).get(product, MARKET_I0)
    floor = max(1.0, 0.55 * params["base"])
    if Econ.price(product, inv) < floor:
        return 0
    head = Econ.units_until(product, inv, floor)
    days = max(1, DAYS - int(getattr(st, "day", 0) or 0))
    shops = getattr(st, "shops", None) or []
    drain_turn = TownDemand.drain_per_turn(shops).get(product, 1.0 / float(TURNS_PER_DAY))
    regen = drain_turn * float(TURNS_PER_DAY) * float(days)
    opp = float((getattr(st, "opp_flow", None) or {}).get(product, 0.0) or 0.0)
    rate = FLOW_PER_TILE_DAY.get(product, 1.0)
    n = int((head + regen - opp) / max(1.0, rate * float(days)))
    labor = effective_labor(st)
    hard = 14 if product == "MILK" else 10
    # 12 cows produced less milk than 10 when wheat tiles vanished.
    # 12 workers can FEED 14 cows if the wheat field actually exists.
    return min(hard, max(0, n), max(0, labor + 2))


def plant_slots(st):
    """Standing plants the intended crew can water after feeding the herd.

    labor×4 froze a 50-tile plant block on a 100-tile board. A worker
    has 24 actions/day; after FEED/CARE the rest is watering. Cap by
    the crew that will land this morning, not the EOD-wiped count.
    """
    labor = effective_labor(st)
    herd = int(getattr(st, "n_animals", 0) or 0)
    usable = int(getattr(st, "usable_tiles", QUADRANT * QUADRANT) or QUADRANT * QUADRANT)
    water_budget = max(4, labor * 8 - herd)
    return max(4, min(max(0, usable - herd), water_budget))


def product_contested(st, prod):
    """True when their flow would crash a book that is already weak.

    Vacating a healthy book (price still near base) is how we parked on
    eggs above I0 while carrot sat 244 units scarce. Subtract their flow
    from demand either way; only leave the crop when the quote is dying.

    Melon is the exception: no shop, town-centre drain 1/day. PR #1
    farming it with us walked the quote to $46 (crush gate 0.25× base).
    """
    params = MARKET_PARAMS.get(prod)
    if not params:
        return False
    inv = st.inventory.get(prod, MARKET_I0)
    price = float(st.prices.get(prod) or Econ.price(prod, inv))
    tiles = int((getattr(st, "opp_peak_tiles", None) or st.opp_tiles_of).get(prod, 0) or 0)
    flow = float(st.opp_flow.get(prod, 0.0) or 0.0)
    if prod == "MELON" and (tiles >= 1 or flow > 0):
        return True
    if price >= 0.90 * params["base"]:
        return False
    if tiles >= 10:
        return True
    if flow <= 0:
        return False
    head = Econ.units_until(prod, inv, max(1.0, 0.45 * params["base"]))
    return flow > 0.40 * max(float(head), 1.0)


def live_buy_land(st, plan=None):
    """Issue BUY_LAND from the live board, not an 8-turn cached plan.

    After NE lands, REPLAN_EVERY leaves plan.buy_land True and the market
    spends $2000 on SW into 22 empty tiles ($49k). Occupancy-gated SW
    still bought the hour NE filled, then sat empty. Buy SW at dawn
    (hour<=4) so leftover wheat has the rest of the day to fill the
    new 25 tiles. empty<=2 never fired by day 12.
    """
    cost = getattr(st, "next_land_cost", None)
    if cost is None:
        return False
    weeds = int(getattr(st, "n_weeds", 0) or 0)
    hour = int(getattr(st, "hour", 99) or 99)
    arrived = len(getattr(st, "hands", []) or [])
    # Hands are wiped at EOD. Dawn arrived-count is the farmer alone,
    # so hands>=10 made SW impossible at hour 0–2 (8390986: every
    # seed stayed locked=50). Use the crew the morning HIREs will land.
    hands = max(arrived, intended_crew(st) - 1) if hour <= 3 else arrived
    money = float(getattr(st, "money", 0) or 0)
    empty = int(getattr(st, "n_empty", 99) or 0)
    animals = int(getattr(st, "n_animals", 0) or 0)
    days_left = max(0, DAYS - int(getattr(st, "day", 0) or 0))
    if cost <= 1000:
        flagged = True if plan is None else bool(getattr(plan, "buy_land", False))
        return flagged and hands >= 4 and weeds <= 10 and money > cost + 400
    if cost <= 2000:
        # Dawn/pack SW vs starter never fired (four CI runs locked=50).
        # Vs scaler it bought and sat empty: 58 empties, $40k→$37k.
        # Occupancy SW (0de5859) cut the median to $45k. Stay on NE.
        return False
    return False


def _get(obj, key, default=None):
    try:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
    except Exception:
        return default


def _as_dict(obj):
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    try:
        return dict(obj)
    except Exception:
        return {}


def _shape(func, x, T):
    x = max(0.0, float(x))
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log1p(x)
    if func == "log10":
        return math.log10(1.0 + x)
    if func == "hinge":
        if not T or T <= 0:
            return x
        u = x / float(T)
        return u + 8.0 * (max(0.0, u - 1.0) ** 2)
    return x


def fib(n):
    a, b = 1, 1
    for _ in range(max(0, int(n))):
        a, b = b, a + b
    return a


class Econ:
    """Closed-form price and yield model matching the official interpreter."""

    @staticmethod
    def price(resource, inventory):
        p = MARKET_PARAMS.get(resource)
        if p is None:
            return PRICE_FLOOR
        base, i0, T = p["base"], p["I0"], p["T"]
        if inventory < i0:
            func, target, sign = p["below"], p["bt"], 1.0
            x = i0 - inventory
        else:
            func, target, sign = p["above"], p["at"], -1.0
            x = inventory - i0
        denom = _shape(func, T, T)
        if denom <= 0:
            return float(base)
        val = base + sign * (target * base / denom) * _shape(func, x, T)
        return max(PRICE_FLOOR, float(int(round(val))))

    @staticmethod
    def marginal_revenue(resource, inventory, units):
        if units <= 0:
            return 0.0
        total = 0.0
        inv = float(inventory)
        n = int(units)
        # Cap the loop; huge dumps are dominated by the $1 floor anyway.
        n = min(n, 400)
        for _ in range(n):
            q = Econ.price(resource, inv)
            total += q
            if q > 1:
                inv += 1.0
        if int(units) > n:
            total += PRICE_FLOOR * (int(units) - n)
        return total

    @staticmethod
    def units_until(resource, inventory, floor_price):
        if Econ.price(resource, inventory) < floor_price:
            return 0
        lo, hi = 0, 4096
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if Econ.price(resource, inventory + mid - 1) >= floor_price:
                lo = mid
            else:
                hi = mid - 1
        return lo

    @staticmethod
    def bonus_start(crop):
        return (CROPS[crop]["max_day"] + 1) // 2

    @staticmethod
    def planned_units(crop, fertilized=False):
        spec = CROPS[crop]
        if spec["ongoing"]:
            return spec["max_yield"] * (2 if fertilized else 1)
        start = Econ.bonus_start(crop)
        watered = max(0, spec["max_day"] - start + 1)
        # Engine: one-time plants start at 1, then +1/+2 per watered bonus day.
        bonus = 2 if fertilized else 1
        raw = 1 + watered * bonus
        cap = spec["max_yield"] if fertilized else PLAIN_CAP.get(crop, spec["max_yield"])
        return int(min(cap, raw))

    @staticmethod
    def crop_tile_days(crop):
        spec = CROPS[crop]
        if spec["ongoing"]:
            # Last scheduled production is first + (max_yield-1)*interval.
            last = spec["first"] + (spec["max_yield"] - 1) * max(1, spec["interval"])
            return last + 1
        # Melon is harvestable at first=10 even though the window runs to 12.
        if crop == "MELON":
            return 11
        return spec["max_day"] + 1


class TownDemand:
    """Exact drain prior from the official shop / town-center tables."""

    @staticmethod
    def drain_per_turn(shops):
        rate = {p: 1.0 / float(TURNS_PER_DAY) for p in PRODUCTS if p != "FERTILIZER"}
        rate["FERTILIZER"] = 0.0
        for name in shops or []:
            products = SHOPS.get(name)
            if not products:
                continue
            mult = 2.0 if len(products) == 1 else 1.0
            for item in products:
                rate[item] = rate.get(item, 0.0) + mult / 4.0
        return rate

    @staticmethod
    def shop_weight(shops):
        w = {p: 0 for p in PRODUCTS}
        for name in shops or []:
            products = SHOPS.get(name)
            if not products:
                continue
            mult = 2 if len(products) == 1 else 1
            for item in products:
                w[item] = w.get(item, 0) + mult
        return w


class BayesianElasticityFilter:
    """Normal-Gamma posterior over realised dPrice = -beta * dInv + noise.

    Collapse: a >15% drop across a 12-turn window pivots the farm vector.
    """

    WINDOW = 12
    COLLAPSE_FRAC = 0.15

    def __init__(self):
        self.mu = {p: 0.0 for p in PRODUCTS}
        self.lam = {p: 1.0 for p in PRODUCTS}
        self.alpha = {p: 2.0 for p in PRODUCTS}
        self.beta_ng = {p: 1.0 for p in PRODUCTS}
        self.price_hist = {p: [] for p in PRODUCTS}
        self.drain_rate = {p: 0.0 for p in PRODUCTS}
        self.collapsed = {p: False for p in PRODUCTS}
        self.collapse_depth = {p: 0.0 for p in PRODUCTS}
        self._prev_inv = None
        self._prev_price = None

    def observe(self, inventory, prices, our_sales, shops):
        prior = TownDemand.drain_per_turn(shops)
        for p in PRODUCTS:
            pr = float(prices.get(p, MARKET_PARAMS[p]["base"]))
            h = self.price_hist[p]
            h.append(pr)
            if len(h) > self.WINDOW * 3:
                del h[0]
            # Keep a rules-based floor under the empirical drain so the first
            # 12 turns are not planned as if the town does not exist.
            self.drain_rate[p] = max(self.drain_rate[p], prior.get(p, 0.0) * 0.5)

        if self._prev_inv is not None:
            for p in PRODUCTS:
                d_inv = float(inventory.get(p, 0)) - float(self._prev_inv.get(p, 0))
                d_pr = float(prices.get(p, 0)) - float(self._prev_price.get(p, 0))
                if abs(d_inv) > 1e-9:
                    x = -d_inv
                    lam0, mu0 = self.lam[p], self.mu[p]
                    lam1 = lam0 + x * x
                    mu1 = (lam0 * mu0 + x * d_pr) / lam1
                    self.alpha[p] += 0.5
                    self.beta_ng[p] += 0.5 * (
                        d_pr * d_pr + lam0 * mu0 * mu0 - lam1 * mu1 * mu1)
                    self.beta_ng[p] = max(1e-6, self.beta_ng[p])
                    self.lam[p], self.mu[p] = lam1, mu1
                ours = float(our_sales.get(p, 0))
                exogenous = d_inv - ours
                emp = max(0.0, -exogenous)
                self.drain_rate[p] = 0.85 * self.drain_rate[p] + 0.15 * emp
                self.drain_rate[p] = max(self.drain_rate[p], prior.get(p, 0.0) * 0.4)

        self._prev_inv = dict(inventory)
        self._prev_price = dict(prices)
        self._update_collapse()

    def _update_collapse(self):
        for p in PRODUCTS:
            h = self.price_hist[p]
            if len(h) <= self.WINDOW:
                self.collapsed[p] = False
                self.collapse_depth[p] = 0.0
                continue
            ref, now = h[-(self.WINDOW + 1)], h[-1]
            drop = (ref - now) / ref if ref > 1e-9 else 0.0
            self.collapse_depth[p] = drop
            self.collapsed[p] = drop > self.COLLAPSE_FRAC

    def posterior_slope(self, product):
        return max(0.0, self.mu.get(product, 0.0))

    def slope_sd(self, product):
        a, b, lam = self.alpha[product], self.beta_ng[product], self.lam[product]
        if a <= 1.0 or lam <= 0:
            return 1.0
        return math.sqrt(max(1e-9, b / ((a - 1.0) * lam)))

    def effective_price(self, product, inventory, units, risk_lambda=0.0):
        if units <= 0:
            return 0.0
        analytic = Econ.marginal_revenue(product, inventory, units) / float(units)
        emp = Econ.price(product, inventory) - 0.5 * self.posterior_slope(product) * (units - 1)
        sd = self.slope_sd(product)
        w = 1.0 / (1.0 + 4.0 * sd)
        blended = (1.0 - w) * analytic + w * max(1.0, emp)
        return max(1.0, blended - risk_lambda * sd * units)


class LiquidationGateway:
    """Hard-armed at turn 650. Unsold stock at 720 is worth zero, so V(T, q>0) = -inf."""

    STAGES = 10
    BUCKETS = 20
    NEG = -1e12

    def __init__(self):
        self.armed = False
        self._cache = {}

    def arm(self, turn):
        if turn >= LIQUIDATION_TURN:
            self.armed = True
        return self.armed

    def units_this_turn(self, product, held, inventory, drain, turn,
                        opp_remain=0.0, opp_imminent=0.0):
        """Flatten `held` by 720, reserving against the opponent's visible dump.

        Town drain makes later stages cheaper. Opponent supply does the
        opposite: it fills the book, so a second-mover premium dump is $1.
        Imminent opponent units are added to inventory *now*; remaining
        opponent units arrive as a negative drain (the book fills).
        """
        turns_left = max(1, HORIZON - turn)
        if held <= 0:
            return 0
        if turns_left <= 4:
            return int(held)
        # Race an imminent premium dump: sell a third now, do not wait.
        race = 0
        if product in PREMIUM and opp_imminent > 0:
            race = int(math.ceil(held * 0.35))
        inv0 = float(inventory) + max(0.0, float(opp_imminent))
        net_drain = float(drain) - max(0.0, float(opp_remain)) / float(turns_left)
        try:
            plan, tps = self._solve(product, int(held), inv0, net_drain, int(turns_left))
        except Exception:
            return int(min(held, max(race, math.ceil(held / float(turns_left)))))
        if not plan:
            return int(min(held, max(race, math.ceil(held / float(turns_left)))))
        n = int(min(held, max(1, math.ceil(plan[0] / max(1.0, tps)))))
        return int(min(held, max(n, race)))

    def _solve(self, product, total_units, inv0, drain, turns_left):
        key = (product, int(total_units), int(inv0 // 25), int(turns_left // 8),
               int(drain * 10))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        stages = max(1, min(self.STAGES, turns_left))
        tps = turns_left / float(stages)
        bucket = max(1, int(math.ceil(total_units / float(self.BUCKETS))))
        nq = int(math.ceil(total_units / float(bucket)))
        # drain > 0: town empties the book (later stages cheaper).
        # drain < 0: opponent fills the book (later stages worse).
        inv_min = inv0 - max(0.0, drain) * tps * max(0, stages - 1)
        inv_max = inv0 + max(0.0, -drain) * tps * max(0, stages - 1) + total_units
        inv_lo = max(1.0, inv_min)
        span = int(inv_max - inv_lo) + total_units + 2
        span = max(2, min(span, 4000))
        C = [0.0] * (span + 1)
        acc = 0.0
        for m in range(span):
            acc += Econ.price(product, inv_lo + m)
            C[m + 1] = acc

        def rev(inv, units):
            if units <= 0:
                return 0.0
            off = max(0, int(inv - inv_lo))
            a = off if off < span else span
            b = off + units
            b = b if b < span else span
            return C[b] - C[a]

        V_next = [self.NEG] * (nq + 1)
        V_next[0] = 0.0
        choice = [[0] * (nq + 1) for _ in range(stages)]
        for i in range(stages - 1, -1, -1):
            V_cur = [self.NEG] * (nq + 1)
            drained = drain * tps * i
            for q in range(nq + 1):
                sold_before = (nq - q) * bucket
                inv_i = max(1.0, inv0 - drained + sold_before)
                best, best_k = self.NEG, 0
                for k in range(q + 1):
                    nxt = V_next[q - k]
                    if nxt <= self.NEG / 2:
                        continue
                    val = rev(inv_i, k * bucket) + nxt
                    if val > best:
                        best, best_k = val, k
                V_cur[q] = best
                choice[i][q] = best_k
            V_next = V_cur
        plan, q = [], nq
        for i in range(stages):
            k = choice[i][q]
            plan.append(k * bucket)
            q -= k
        self._cache[key] = (plan, tps)
        if len(self._cache) > 128:
            self._cache.clear()
        return plan, tps


class DirectionCalibrator:
    """NORTH/SOUTH are defined in the engine; we still lock them from motion."""

    DEFAULT = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}

    def __init__(self):
        self.map = dict(self.DEFAULT)
        self.locked = set()
        self._pending = None

    def note_issued(self, verb, pos):
        self._pending = (verb, tuple(pos)) if verb in self.DEFAULT else None

    def observe(self, pos):
        if not self._pending:
            return
        verb, old = self._pending
        self._pending = None
        if verb in self.locked:
            return
        dx, dy = pos[0] - old[0], pos[1] - old[1]
        if abs(dx) + abs(dy) != 1:
            return
        self.map[verb] = (dx, dy)
        self.locked.add(verb)
        opp = {"NORTH": "SOUTH", "SOUTH": "NORTH", "EAST": "WEST", "WEST": "EAST"}[verb]
        if opp not in self.locked:
            self.map[opp] = (-dx, -dy)

    def step_toward(self, src, dst):
        sx, sy = src
        tx, ty = dst
        ddx, ddy = tx - sx, ty - sy
        if ddx == 0 and ddy == 0:
            return None
        prefer_x = abs(ddx) > abs(ddy) or (abs(ddx) == abs(ddy) and ddx != 0)
        order = [(ddx, 0), (0, ddy)] if prefer_x else [(0, ddy), (ddx, 0)]
        for want_dx, want_dy in order:
            if want_dx == 0 and want_dy == 0:
                continue
            sign = (1 if want_dx > 0 else -1, 0) if want_dx else (0, 1 if want_dy > 0 else -1)
            for verb, vec in self.map.items():
                if vec == sign:
                    return verb
        return None


def linear_assignment(cost, n, m):
    """Jonker–Volgenant min-cost assignment, n rows to m columns, n <= m."""
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta, j1 = INF, -1
            row = cost[i0 - 1]
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = row[j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            if j1 < 0:
                break
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    result = [-1] * n
    for j in range(1, m + 1):
        if p[j] > 0:
            result[p[j] - 1] = j - 1
    return result


class LaborAssigner:
    GAMMA = 0.72
    LOOKAHEAD = 3

    def assign(self, workers, tasks):
        n = len(workers)
        if n == 0:
            return []
        if not tasks:
            return [None] * n
        m = max(len(tasks), n)
        cost = []
        for (wx, wy) in workers:
            row = []
            for t in tasks:
                tx, ty = t["pos"]
                dist = abs(tx - wx) + abs(ty - wy)
                row.append(-t["value"] * (self.GAMMA ** min(dist, self.LOOKAHEAD * 4)))
            row.extend([0.0] * (m - len(tasks)))
            cost.append(row)
        try:
            sol = linear_assignment(cost, n, m)
        except Exception:
            return self._greedy(workers, tasks)
        return [tasks[j] if 0 <= j < len(tasks) else None for j in sol]

    def _greedy(self, workers, tasks):
        taken, out = set(), []
        for (wx, wy) in workers:
            best, best_i = None, -1
            for i, t in enumerate(tasks):
                if i in taken:
                    continue
                d = abs(t["pos"][0] - wx) + abs(t["pos"][1] - wy)
                score = t["value"] * (self.GAMMA ** min(d, 12))
                if best is None or score > best:
                    best, best_i = score, i
            if best_i >= 0:
                taken.add(best_i)
                out.append(tasks[best_i])
            else:
                out.append(None)
        return out


class Plan(object):
    __slots__ = ("phase", "stance", "crop_mix", "animal_targets", "buy_land",
                 "target_hands", "price_hint", "capacity", "reserve",
                 "shadow_td", "action_value", "wheat_reserve")

    def __init__(self):
        self.phase = "BOOTSTRAP"
        self.stance = "NEUTRAL"
        self.crop_mix = {}
        self.animal_targets = {}
        self.buy_land = False
        self.target_hands = 4
        self.price_hint = {}
        self.capacity = {}
        self.reserve = {}
        self.shadow_td = 1.0
        self.action_value = 8.0
        self.wheat_reserve = 0


class MPCRevenueEngine:
    """Rolling-horizon MPC. Early capital is a multiplier, not a cash pile.

    Turns 0-72  BOOTSTRAP  : 100% carrot (0-48 if the opponent is a carrot farm).
    Turns 72-240 EXPAND    : buy land, stand up geese, plant uncontested melon.
    Turns 240-500 COMPOUND : KKT water-fill — equalise revenue per tile-day
                             subject to remaining book capacity minus opponent
                             pipeline plus town regeneration.
    Turns 500-650 HARVEST  : no new long-cycle assets.
    Turn 650+    LIQUIDATE : gateway owns the book; field work is harvest/drop.
    """

    REPLAN_EVERY = 8
    MU_LO, MU_HI = 0.5, 4000.0
    BISECT = 26

    def __init__(self, elasticity):
        self.el = elasticity
        self.plan = Plan()
        self._last = -999

    def phase_of(self, turn, st=None):
        if turn >= LIQUIDATION_TURN:
            return "LIQUIDATE"
        if turn >= 500:
            return "HARVEST"
        if turn >= 240:
            return "COMPOUND"
        carrot_opp = 0
        if st is not None:
            peak = getattr(st, "opp_peak_tiles", None) or st.opp_tiles_of
            carrot_opp = int(peak.get("CARROT", 0) or 0)
        # A carrot-only opponent occupies that book from day 0. Leave
        # bootstrap as soon as the first carrot cycle has printed cash.
        expand_from = 48 if carrot_opp >= 12 else 72
        if turn >= expand_from:
            return "EXPAND"
        return "BOOTSTRAP"

    def maybe_replan(self, st):
        phase = self.phase_of(st.turn, st)
        due = (st.turn - self._last >= self.REPLAN_EVERY
               or not self.plan.crop_mix
               or phase != self.plan.phase
               or st.stance != self.plan.stance
               or st.hour == 0
               or len(st.hands) != getattr(self, "_hands", -1)
               or st.usable_tiles != getattr(self, "_usable", -1))
        if not due:
            return self.plan
        self._last = st.turn
        self._hands = len(st.hands)
        self._usable = st.usable_tiles
        try:
            self.plan = self._replan(st)
        except Exception:
            if not self.plan.crop_mix:
                self.plan.crop_mix = {"CARROT": max(1, st.usable_tiles)}
            self.plan.phase = phase
            self.plan.stance = st.stance
        return self.plan

    def _eligible(self, st, phase, days_left, shops_w):
        """Which products may receive new tiles this phase.

        LOCK does not mean "stop premium". It means "do not take variance
        that can flip a win": vacate books the opponent already occupies.
        Eggs absorb and geese stay eligible. Uncontested melon is how a
        lead against a carrot farm is locked in, not given back.
        """
        allow = set()
        if phase == "LIQUIDATE":
            return allow
        if phase == "BOOTSTRAP":
            if days_left >= 4:
                allow.add("CARROT")
            return allow
        if phase == "HARVEST":
            if days_left >= 4 and not product_contested(st, "CARROT"):
                allow.add("CARROT")
            if days_left >= 5:
                allow.add("WHEAT")
            return allow
        # EXPAND / COMPOUND
        candidates = []
        if days_left >= 4:
            candidates.append("CARROT")
        if days_left >= 5:
            candidates.append("WHEAT")
        if days_left >= 8:
            candidates.append("EGG")
        # Melon has no shop — only town-centre drain. Do not floor it; KKT
        # plus book_tiles is the cap. A 12-tile melon block finishes at $7.
        if days_left >= 12:
            inv_m = st.inventory.get("MELON", MARKET_I0)
            if Econ.price("MELON", inv_m) >= 0.55 * MARKET_PARAMS["MELON"]["base"]:
                candidates.append("MELON")
        if phase in ("EXPAND", "COMPOUND"):
            # Town-centre drain is 1/day with zero shops. Requiring a
            # milk/wool shop to even list them froze the herd on geese
            # while those books sat 200-500 units scarce at 1.5-2× base.
            if days_left >= 12:
                candidates.append("MILK")
            if days_left >= 10:
                candidates.append("WOOL")
            if days_left >= 14:
                quote_s = Econ.price(
                    "STRAWBERRY", st.inventory.get("STRAWBERRY", MARKET_I0))
                # Town drain is 1/day even before shops. Green CI left
                # strawberry −400 to −800 at $290–$350 with 0 tiles on
                # most starter seeds.
                if shops_w.get("STRAWBERRY", 0) >= 1 or quote_s >= 0.85 * MARKET_PARAMS["STRAWBERRY"]["base"]:
                    candidates.append("STRAWBERRY")
                if phase == "COMPOUND" and shops_w.get("TOMATO", 0) >= 2 and days_left >= 13:
                    candidates.append("TOMATO")
        for prod in candidates:
            if prod in ("WHEAT", "EGG"):
                allow.add(prod)
                continue
            if product_contested(st, prod):
                continue
            allow.add(prod)
        return allow

    def _demand(self, st, mu, eligible, turns_to_gate):
        total = 0.0
        units = {}
        for prod in eligible:
            cost = TDPU.get(prod, 2.0)
            if self.el.collapsed.get(prod) and prod not in ("WHEAT", "EGG"):
                cost *= 1.0 + 2.0 * max(0.0, self.el.collapse_depth.get(prod, 0.0))
            inv = st.inventory.get(prod, MARKET_I0)
            # Glut derate: eggs absorb so KKT keeps printing them above I0
            # while carrot sits scarce. Scarce books must win the water-fill.
            if inv > MARKET_I0:
                cost *= 1.0 + (inv - MARKET_I0) / 80.0
            else:
                cost *= max(0.45, 1.0 - (MARKET_I0 - inv) / 400.0)
            # Melon is the only crop no shop ever buys. Town-centre drain
            # is 1/day; a base-price fill saturates it. Make the KKT cost
            # pay for that missing drain.
            if prod == "MELON":
                cost *= 3.0
            floor = max(1.0, mu * cost)
            if Econ.price(prod, inv) < floor:
                units[prod] = 0
                continue
            headroom = Econ.units_until(prod, inv, floor)
            regen = self.el.drain_rate.get(prod, 0.0) * turns_to_gate
            # Flow occupancy: standing plants PLUS replant rate × days left.
            opp = float(st.opp_flow.get(prod, 0.0) or 0.0)
            X = max(0.0, headroom + regen - opp)
            if st.stance == "CONTEST" and prod in PREMIUM:
                X *= 1.15
            units[prod] = X
            total += X * cost
        return total, units

    def _replan(self, st):
        p = Plan()
        p.phase = self.phase_of(st.turn, st)
        p.stance = st.stance
        days_left = max(0, DAYS - st.day)
        turns_to_gate = max(1, LIQUIDATION_TURN - st.turn)
        shops_w = TownDemand.shop_weight(st.shops)
        eligible = self._eligible(st, p.phase, days_left, shops_w)

        for prod in PRODUCTS:
            inv = st.inventory.get(prod, MARKET_I0)
            take = 6
            p.price_hint[prod] = self.el.effective_price(prod, inv, take, st.risk_lambda)

        tile_days = max(1.0, st.usable_tiles * float(max(1, days_left)))
        tdpu_e = {prod: TDPU[prod] for prod in eligible if prod in TDPU}

        if p.phase == "BOOTSTRAP":
            p.crop_mix = {"CARROT": st.usable_tiles}
            p.animal_targets = {}
            p.shadow_td = 20.0
            p.action_value = 8.0
            p.target_hands = 8
            p.wheat_reserve = 0
            p.buy_land = False
            p.stance = "NEUTRAL"
            for prod in PRODUCTS:
                p.reserve[prod] = 0.55 * MARKET_PARAMS[prod]["base"]
                p.capacity[prod] = 10 ** 6
            return p

        lo, hi = self.MU_LO, self.MU_HI
        if tdpu_e:
            for _ in range(self.BISECT):
                mid = 0.5 * (lo + hi)
                demand, _ = self._demand(st, mid, tdpu_e, turns_to_gate)
                if demand > tile_days:
                    lo = mid
                else:
                    hi = mid
        mu = hi
        p.shadow_td = mu
        _tot, unit_targets = self._demand(st, mu, tdpu_e, turns_to_gate)

        # Staples absorb; a mu*tdpu floor on eggs/carrots/wheat is how a
        # local-optima agent starves itself of cash and never buys land.
        # Premium goods keep the KKT reserve so we do not walk them to $1.
        staple_frac = {
            "WHEAT": 0.40, "CARROT": 0.40, "EGG": 0.40, "FERTILIZER": 0.45,
            "TOMATO": 0.50,
        }
        for prod in PRODUCTS:
            cost = TDPU.get(prod)
            kkt = max(1.0, mu * cost) if cost else 1.0
            if prod in staple_frac:
                p.reserve[prod] = max(1.0, staple_frac[prod] * MARKET_PARAMS[prod]["base"])
            else:
                p.reserve[prod] = kkt
            p.capacity[prod] = int(unit_targets.get(prod, 0))

        dl = float(max(1, days_left))
        for prod, X in unit_targets.items():
            if X <= 0 or prod == "FERTILIZER":
                continue
            tiles = int(math.floor(X * TDPU[prod] / dl))
            if tiles <= 0:
                continue
            if prod in CROPS:
                p.crop_mix[prod] = tiles
            else:
                for animal, produced in ANIMAL_PRODUCT.items():
                    if produced == prod:
                        if animal == "GOOSE":
                            cap = goose_cap(st)
                        else:
                            cap = pasture_cap(st, produced)
                        p.animal_targets[animal] = min(tiles, cap)

        # Feed wheat: market wheat absorbs and is cheap. Planting 1.25 tiles
        # per animal crowds out geese and land on a 25-tile farm. Plant a
        # thin wheat block; buy the rest.
        geese = p.animal_targets.get("GOOSE", 0)
        cows = p.animal_targets.get("COW", 0)
        sheep = p.animal_targets.get("SHEEP", 0)
        herd = geese + cows + sheep + st.n_animals
        def _feed_tiles(h):
            if not h or days_left < 5:
                return 0
            # usable//5 is 10 on NE. 9017/9051 mid wheat is 4–6 against
            # 14 cows; leftover carrot takes the rest. Cap 12 (//4) so
            # wheat-first sow fills feed before carrot. Do not add mouths.
            return min(max(2, int(math.ceil(h * 0.50))), max(2, st.usable_tiles // 4))
        ft = _feed_tiles(herd)
        if ft:
            p.crop_mix["WHEAT"] = max(p.crop_mix.get("WHEAT", 0), ft)

        # Collapse / contested pivot: drop the crashed or occupied crop.
        for crop, prod in (("MELON", "MELON"), ("STRAWBERRY", "STRAWBERRY"),
                           ("TOMATO", "TOMATO"), ("CARROT", "CARROT")):
            if crop not in p.crop_mix:
                continue
            if self.el.collapsed.get(prod) and self.el.collapse_depth.get(prod, 0.0) > 0.25:
                p.crop_mix.pop(crop, None)
            elif product_contested(st, prod):
                p.crop_mix.pop(crop, None)

        # EXPAND must stand up the herd even if the water-fill rounded to
        # zero tiles. Eggs absorb, but milk/wool at 1.5-2× base are the
        # books the goose floor has been crowding out.
        if p.phase in ("EXPAND", "COMPOUND") and days_left >= 10:
            cap_g = goose_cap(st)
            cap_c = pasture_cap(st, "MILK")
            cap_sh = pasture_cap(st, "WOOL")
            quote_m = Econ.price("MILK", st.inventory.get("MILK", MARKET_I0))
            quote_wo = Econ.price("WOOL", st.inventory.get("WOOL", MARKET_I0))
            milk_ok = (
                cap_c > 0
                and quote_m >= 0.85 * MARKET_PARAMS["MILK"]["base"]
                and not product_contested(st, "MILK")
            )
            wool_ok = (
                cap_sh > 0
                and quote_wo >= 0.85 * MARKET_PARAMS["WOOL"]["base"]
                and not product_contested(st, "WOOL")
            )
            if milk_ok:
                # 14 cows at $364 printed $78k; 15 cows walked milk to $154.
                if quote_m >= 1.20 * MARKET_PARAMS["MILK"]["base"]:
                    cow_floor = min(14, cap_c, max(4, st.usable_tiles // 3))
                else:
                    cow_floor = min(12, cap_c, max(4, st.usable_tiles // 4))
                p.animal_targets["COW"] = min(
                    14,
                    max(int(p.animal_targets.get("COW", 0) or 0), cow_floor),
                    cap_c,
                )
            elif cap_c <= 0:
                p.animal_targets.pop("COW", None)
            if wool_ok:
                sh_floor = min(3, cap_sh)
                sh_hi = cap_sh
                # Wool often printed +oversupply at $116–$189 while strawberry
                # sat −400 at $300. Cap sheep at 4 unless the quote is still
                # 1.25× base; those tiles go to strawberry/wheat leftovers.
                if quote_wo < 1.25 * MARKET_PARAMS["WOOL"]["base"]:
                    sh_hi = min(4, cap_sh)
                p.animal_targets["SHEEP"] = min(
                    max(int(p.animal_targets.get("SHEEP", 0) or 0), sh_floor), sh_hi)
            elif cap_sh <= 0:
                p.animal_targets.pop("SHEEP", None)
            pasture_on = (
                int(p.animal_targets.get("COW", 0) or 0)
                + int(p.animal_targets.get("SHEEP", 0) or 0)
            )
            g_lo = min(4 if pasture_on else 8, cap_g)
            g_hi = min(6 if pasture_on else 12, cap_g)
            p.animal_targets["GOOSE"] = min(
                max(int(p.animal_targets.get("GOOSE", 0) or 0), g_lo), g_hi)
            # Melon is shop-less. 12 tiles finish at $7; 0 tiles drop the
            # score to 13k. Floor at remaining headroom, at most 4, and
            # drop it the moment the quote is dying.
            cap_m = min(4, book_tiles(st, "MELON", 0.55))
            # 9034 $73.9k sold melon 2 at $250 with milk $369. 1.50×
            # would fire on every seed (9051 floor is $241). 1.80×
            # keeps 4 melon on the floor and frees 2 tiles on hot milk.
            if quote_m >= 1.80 * MARKET_PARAMS["MILK"]["base"]:
                cap_m = min(2, cap_m)
            if cap_m > 0 and not product_contested(st, "MELON"):
                # max(kkt, cap) kept 12 melon when KKT over-assigned.
                # Floor the shop-less book at remaining headroom, at most 4.
                p.crop_mix["MELON"] = cap_m
            elif p.crop_mix.get("MELON", 0):
                p.crop_mix.pop("MELON", None)
            quote_s = Econ.price("STRAWBERRY", st.inventory.get("STRAWBERRY", MARKET_I0))
            # 12 straw tiles crashed seed 9000 to $118 (at I0). The $64k
            # farm had 3 tiles at $347. Cap 6; leftover is not a dump.
            # max(kkt, 4) kept the KKT dump: scaler 9051 stood 25 straw.
            cap_s = min(6, book_tiles(st, "STRAWBERRY", 0.70))
            if (cap_s > 0 and days_left >= 14 and quote_s >= 0.85 * MARKET_PARAMS["STRAWBERRY"]["base"]
                    and not product_contested(st, "STRAWBERRY")):
                have_s = int(p.crop_mix.get("STRAWBERRY", 0) or 0)
                p.crop_mix["STRAWBERRY"] = min(cap_s, max(have_s, min(4, cap_s)))
            elif p.crop_mix.get("STRAWBERRY", 0):
                if cap_s <= 0:
                    p.crop_mix.pop("STRAWBERRY", None)
                else:
                    p.crop_mix["STRAWBERRY"] = min(int(p.crop_mix["STRAWBERRY"]), cap_s)
            herd = (p.animal_targets.get("GOOSE", 0) + p.animal_targets.get("COW", 0)
                    + p.animal_targets.get("SHEEP", 0) + st.n_animals)
            ft = _feed_tiles(herd)
            if ft:
                p.crop_mix["WHEAT"] = max(int(p.crop_mix.get("WHEAT", 0) or 0), ft)
            used_now = sum(p.crop_mix.values()) + sum(p.animal_targets.values())
            left = max(0, min(
                st.usable_tiles - used_now,
                plant_slots(st) - sum(p.crop_mix.values()),
            ))
            if left > 0 and cap_s > 0 and days_left >= 14 and not product_contested(st, "STRAWBERRY"):
                have_s = int(p.crop_mix.get("STRAWBERRY", 0) or 0)
                extra = min(left, max(0, cap_s - have_s))
                if extra:
                    p.crop_mix["STRAWBERRY"] = have_s + extra
                    left -= extra
            if left > 0 and days_left >= 5 and st.usable_tiles >= 75:
                # SW's new 25 tiles must be wheat, not leftover carrot.
                # Occupancy SW (0de5859) sat empty and cut the median to $45k.
                have_w = int(p.crop_mix.get("WHEAT", 0) or 0)
                p.crop_mix["WHEAT"] = have_w + left
                left = 0
            if left > 0 and days_left >= 4 and not product_contested(st, "CARROT"):
                have_c = int(p.crop_mix.get("CARROT", 0) or 0)
                extra = left
                p.crop_mix["CARROT"] = have_c + extra
                left = 0
            if left > 0 and days_left >= 5:
                # $52k seeds left 7–10 empty because leftover wheat was
                # capped at ft+4 and carrot was contested. Wheat absorbs.
                have_w = int(p.crop_mix.get("WHEAT", 0) or 0)
                p.crop_mix["WHEAT"] = have_w + left

        if not p.crop_mix and not p.animal_targets and days_left >= 4:
            fallback = "WHEAT" if product_contested(st, "CARROT") else "CARROT"
            p.crop_mix[fallback] = max(1, st.usable_tiles // 2)

        # Never over-allocate tiles. Shrink carrot first, then extra wheat,
        # then extra geese. Keep the melon floor and the cow/sheep floor;
        # restoring a 12-goose target here is how pastures vanished.
        used = sum(p.crop_mix.values()) + sum(p.animal_targets.values())
        if used > st.usable_tiles > 0:
            overflow = used - st.usable_tiles
            feed_keep = min(
                int(p.crop_mix.get("WHEAT", 0) or 0),
                max(4, st.usable_tiles // 8),
            )
            melon_keep = min(int(p.crop_mix.get("MELON", 0) or 0), min(4, book_tiles(st, "MELON", 0.55)))
            straw_keep = min(int(p.crop_mix.get("STRAWBERRY", 0) or 0), min(4, book_tiles(st, "STRAWBERRY", 0.70)))
            for crop in ("CARROT", "TOMATO", "WHEAT", "STRAWBERRY", "MELON"):
                if overflow <= 0:
                    break
                have = int(p.crop_mix.get(crop, 0) or 0)
                if have <= 0:
                    continue
                keep = 0
                if crop == "WHEAT":
                    keep = feed_keep
                elif crop == "MELON":
                    keep = melon_keep
                elif crop == "STRAWBERRY":
                    keep = straw_keep
                take = min(overflow, max(0, have - keep))
                if take > 0:
                    p.crop_mix[crop] = have - take
                    overflow -= take
            pasture_on = (
                int(p.animal_targets.get("COW", 0) or 0)
                + int(p.animal_targets.get("SHEEP", 0) or 0)
            )
            cap_g = goose_cap(st)
            g_lo = min(4 if pasture_on else 8, cap_g)
            if overflow > 0:
                have_g = int(p.animal_targets.get("GOOSE", 0) or 0)
                take = min(overflow, max(0, have_g - g_lo))
                if take > 0:
                    p.animal_targets["GOOSE"] = have_g - take
                    overflow -= take
            if overflow > 0:
                scale = st.usable_tiles / float(
                    max(1, sum(p.crop_mix.values()) + sum(p.animal_targets.values())))
                p.crop_mix = {k: max(0, int(v * scale)) for k, v in p.crop_mix.items()}
                p.animal_targets = {k: max(0, int(v * scale)) for k, v in p.animal_targets.items()}
            if p.phase in ("EXPAND", "COMPOUND") and days_left >= 10:
                g_hi = min(6 if pasture_on else 12, cap_g)
                p.animal_targets["GOOSE"] = min(
                    max(int(p.animal_targets.get("GOOSE", 0) or 0), g_lo), g_hi)
                cap_c = pasture_cap(st, "MILK")
                if cap_c > 0 and not product_contested(st, "MILK"):
                    p.animal_targets["COW"] = min(
                        14,
                        max(int(p.animal_targets.get("COW", 0) or 0), min(2, cap_c)),
                        cap_c,
                    )
                extra = (
                    sum(p.crop_mix.values()) + sum(p.animal_targets.values())
                    - st.usable_tiles
                )
                have_c = int(p.crop_mix.get("CARROT", 0) or 0)
                if extra > 0 and have_c > 0:
                    take = min(extra, have_c)
                    p.crop_mix["CARROT"] = have_c - take

        p.action_value = max(2.0, mu / 4.0)
        herd = (
            int(p.animal_targets.get("GOOSE", 0) or 0)
            + int(p.animal_targets.get("COW", 0) or 0)
            + int(p.animal_targets.get("SHEEP", 0) or 0)
            + int(st.n_animals or 0)
        )
        p.wheat_reserve = max(herd * 2, st.n_animals * 3)

        # Cap crop mix to plants we can actually water.
        slots = plant_slots(st)
        used_c = sum(p.crop_mix.values())
        if used_c > slots:
            scale = slots / float(used_c)
            p.crop_mix = {k: max(0, int(v * scale)) for k, v in p.crop_mix.items()}
            if "WHEAT" in p.crop_mix or (p.animal_targets and days_left >= 5):
                p.crop_mix["WHEAT"] = max(p.crop_mix.get("WHEAT", 0), min(2, slots))

        next_cost = st.next_land_cost
        p.buy_land = False
        if next_cost is not None and days_left >= 6 and p.phase in ("EXPAND", "COMPOUND"):
            # Hire first, then expand. Weeds were dropped HIREs, not a 75-tile
            # board. Hour 0 arrived-hands is zero after the EOD wipe — use the
            # crew we are about to hire.
            hands = max(len(st.hands), intended_crew(st) - 1) if st.hour <= 3 else len(st.hands)
            cashish = st.money + 0.5 * sum(
                st.shed.get(s, 0) * Econ.price(s, st.inventory.get(s, MARKET_I0))
                for s in ("CARROT", "EGG", "WHEAT")
            )
            # Live next_land_cost, not a cached plan.buy_land. SW is off
            # until leftover mix fills the extra 25 tiles.
            if next_cost <= 1000:
                p.buy_land = (
                    hands >= 4
                    and getattr(st, "n_weeds", 0) <= 10
                    and cashish > next_cost + 400
                )
            elif next_cost <= 2000:
                p.buy_land = False
            else:
                p.buy_land = False

        # Hands are wiped at EOD (engine fact). Fib resets with them.
        # 12 hires/day costs fib(0..11) ≈ 376. 18/day costs ≈ 6765.
        # Full intended crew (a7d18c0) cut 9034 $73.9k → $57.5k (cows 14→9).
        p.target_hands = intended_crew(st) - 1
        return p


class State(object):
    """Defensive flattened view of one observation."""

    def __init__(self, obs):
        self.player = int(_get(obs, "player", 0) or 0)
        self.day = int(_get(obs, "day", 0) or 0)
        self.hour = int(_get(obs, "hour", 0) or 0)
        step = _get(obs, "step", None)
        self.turn = self.day * TURNS_PER_DAY + self.hour
        if isinstance(step, int) and step > self.turn:
            self.turn = step
        self.turn = max(0, min(HORIZON, self.turn))

        farms = _get(obs, "farms", []) or []
        self.me = farms[self.player] if self.player < len(farms) else {}
        self.opp = farms[1 - self.player] if len(farms) > 1 else {}

        priv = _get(obs, "private", {}) or {}
        self.shed = _as_dict(_get(priv, "shed", {}))
        self.seeds = _as_dict(_get(priv, "seeds", {}))
        raw_inv = _get(priv, "inventories", []) or []
        self.inventories = [_as_dict(x) for x in raw_inv]

        market = _get(obs, "market", {}) or {}
        self.inventory = _as_dict(_get(market, "inventory", {}))
        self.prices = _as_dict(_get(market, "prices", {}))
        for p in PRODUCTS:
            self.inventory.setdefault(p, MARKET_PARAMS[p]["I0"])
            self.prices.setdefault(p, MARKET_PARAMS[p]["base"])

        town = _get(obs, "town", {}) or {}
        self.shops = list(_get(town, "unlocked_shops", []) or [])

        self.money = float(_get(self.me, "money", 0.0) or 0.0)
        self.opp_money = float(_get(self.opp, "money", 0.0) or 0.0)
        self.tiles = _get(self.me, "tiles", []) or []
        self.opp_tiles = _get(self.opp, "tiles", []) or []
        self.farmer = list(_get(self.me, "farmer", [4, 4]) or [4, 4])
        self.hands = [list(h) for h in (_get(self.me, "hands", []) or [])]
        self.hires_today = int(_get(self.me, "hires_today", 0) or 0)
        self.quadrants = set(_get(self.me, "unlocked_quadrants", ["NW"]) or ["NW"])

        self.shed_total = sum(int(v or 0) for v in self.shed.values())
        self.n_empty = 0
        self.usable_tiles = self._count_usable()
        self.next_land_cost = self._next_land_cost()
        self.n_animals = 0
        self.animals_alive = {"GOOSE": 0, "COW": 0, "SHEEP": 0}
        self.empty_structs = []
        self.n_coops = 0
        self.n_pastures = 0
        self.n_weeds = 0
        self.n_plants = 0
        self.n_unwatered = 0
        self.crops_alive = {c: 0 for c in CROPS}
        self.my_pipeline = {}
        self.my_imminent = {}
        self.opp_pipeline = {}
        self.opp_imminent = {}
        self.opp_tiles_of = {}
        self.opp_peak_tiles = {}
        self.opp_flow = {}
        self.my_nav = 0.0
        self.opp_nav = 0.0
        self.edge = 0.0
        self.stance = "NEUTRAL"
        self.risk_lambda = 0.0
        self._scan_board()
        self._pipelines()
        self.compute_nav()

    def _count_usable(self):
        n = 0
        empty = 0
        for row in self.tiles:
            for t in row:
                if t == "LOCKED":
                    continue
                n += 1
                if t is None:
                    empty += 1
        self.n_empty = empty
        return n if n else QUADRANT * QUADRANT

    def _next_land_cost(self):
        # Count unlocked area, not the observation list: a stale quadrants
        # set after BUY_LAND is how the next price stayed $1000 and SW landed.
        u = int(self.usable_tiles or 0)
        if u < 50:
            return LAND_PRICES[0]
        if u < 75:
            return LAND_PRICES[1]
        if u < 100:
            return LAND_PRICES[2]
        return None

    def _scan_board(self):
        for y, row in enumerate(self.tiles):
            for x, tile in enumerate(row):
                if not isinstance(tile, dict):
                    continue
                kind = tile.get("kind")
                animal = tile.get("animal")
                if kind == "WEED":
                    self.n_weeds += 1
                if kind == "PLANT":
                    self.n_plants += 1
                    crop = tile.get("crop")
                    if crop in self.crops_alive:
                        self.crops_alive[crop] += 1
                    if not tile.get("watered_today"):
                        self.n_unwatered += 1
                if animal in self.animals_alive:
                    self.animals_alive[animal] += 1
                    self.n_animals += 1
                if animal == "GOOSE" or kind == "COOP":
                    self.n_coops += 1
                    if animal not in ANIMALS:
                        self.empty_structs.append(((x, y), "COOP"))
                elif animal in ("COW", "SHEEP") or kind == "PASTURE":
                    self.n_pastures += 1
                    if animal not in ANIMALS:
                        self.empty_structs.append(((x, y), "PASTURE"))

    def _pipelines(self):
        """Day-0 occupancy of both public farms. Opponent shed is hidden, so
        their field pipeline is a lower bound on what they will sell."""
        self.my_pipeline, self.my_imminent, _mine = scan_pipeline(self.tiles, self.day)
        self.opp_pipeline, self.opp_imminent, self.opp_tiles_of = scan_pipeline(
            self.opp_tiles, self.day)
        self.opp_peak_tiles = dict(self.opp_tiles_of)
        self.opp_flow = add_replant_flow(
            self.opp_pipeline, self.opp_peak_tiles, max(0, DAYS - self.day))

    def refresh_book(self, peak_tiles=None):
        """Recompute flow + NAV after the agent updates peak opponent tiles."""
        if peak_tiles:
            self.opp_peak_tiles = dict(peak_tiles)
        self.opp_flow = add_replant_flow(
            self.opp_pipeline, self.opp_peak_tiles, max(0, DAYS - self.day))
        self.compute_nav()

    def tile_at(self, x, y):
        try:
            return self.tiles[y][x]
        except Exception:
            return "LOCKED"

    def shed_access(self):
        c = BOARD // 2
        return [(c - 1, c - 1), (c, c - 1), (c - 1, c), (c, c)]

    def wheat_held(self):
        n = int(self.shed.get("WHEAT", 0) or 0)
        for inv in self.inventories:
            n += int(inv.get("WHEAT", 0) or 0)
        return n

    def compute_nav(self):
        """Liquidatable NAV on both sides. Opponent shed is invisible, so
        their number is a lower bound (cash + public field). That is enough
        to lock a real lead and to contest a real deficit.

        stance:
          LOCK    — ahead enough that extra premium variance can flip a win
          CONTEST — behind; take remaining book before they do
          NEUTRAL — race the capacity forecast
        """
        shed_val = 0.0
        for p in PRODUCTS:
            n = int(self.shed.get(p, 0) or 0)
            if n:
                shed_val += Econ.marginal_revenue(p, self.inventory.get(p, MARKET_I0), n)
        my_field = pipeline_mark(self.my_pipeline, self.inventory)
        # Opponent NAV includes replant flow. Counting only the standing
        # field overstates the lead vs a 25-tile carrot farm and LOCK fires
        # while we are still on their book.
        opp_field = pipeline_mark(self.opp_flow or self.opp_pipeline, self.inventory)
        self.my_nav = self.money + shed_val + my_field
        self.opp_nav = self.opp_money + opp_field
        self.edge = self.my_nav - self.opp_nav
        # EXPAND (and the first days of COMPOUND) must still stand up geese
        # and take uncontested melon. LOCK is a late-horizon stance.
        if self.turn < 300:
            self.stance = "NEUTRAL"
            self.risk_lambda = 0.0
            return
        scale = max(10000.0, 0.22 * max(self.opp_nav, self.my_nav, 1.0))
        if self.edge > scale:
            self.stance = "LOCK"
        elif self.edge < -0.70 * scale:
            self.stance = "CONTEST"
        else:
            self.stance = "NEUTRAL"
        self.risk_lambda = max(-0.6, min(0.6, self.edge / 25000.0))


def _age(st, tile):
    return st.day - int(tile.get("planted_day", st.day))


def build_tasks(st, plan):
    """Legal field actions this turn, valued in expected coins.

    Survival (plant one missed watering from a weed; animal one missed feed
    from escaping) is priced at CRITICAL. FEED tasks are only emitted when
    some worker already carries wheat — pickup is handled as its own duty.
    """
    tasks = []
    add = tasks.append
    days_left = max(0, DAYS - st.day)
    empties = []
    animals_unfed = 0
    on_board = {c: 0 for c in CROPS}

    for y, row in enumerate(st.tiles):
        for x, tile in enumerate(row):
            if tile == "LOCKED":
                continue
            pos = (x, y)
            if tile is None:
                empties.append(pos)
                continue
            if not isinstance(tile, dict):
                continue
            kind = tile.get("kind")

            if kind == "WEED":
                # DIG at 4 weeds cut median $68k → $63k: seed 9000 lost
                # $12k because diggers stole morning sow (wheat 11 → 4).
                # 9017's 6–7 weeds still lose to FEED/missed WATER at
                # full CRITICAL. Leave the gate at 8.
                add({"pos": pos, "op": ["DIG"], "kind": "DIG",
                     "value": (CRITICAL * 0.05 if st.n_weeds >= 8
                               else 2.0 * plan.action_value)})
                continue

            if kind == "PLANT":
                crop = tile.get("crop")
                spec = CROPS.get(crop)
                if spec is None:
                    continue
                if crop in on_board:
                    on_board[crop] += 1
                age = _age(st, tile)
                price = plan.price_hint.get(crop, MARKET_PARAMS[crop]["base"])
                units_now = int(tile.get("yield_units", 0) or 0)
                unwatered = int(tile.get("consecutive_unwatered", 0) or 0)
                watered = bool(tile.get("watered_today", False))

                if not watered:
                    if unwatered >= 1:
                        add({"pos": pos, "op": ["WATER"], "kind": "WATER",
                             "value": CRITICAL + max(units_now, 1) * price})
                    else:
                        start = Econ.bonus_start(crop)
                        in_window = (not spec["ongoing"]) and start <= age <= spec["max_day"]
                        # Daily water is cheap labour and protects the bonus.
                        bonus = price if in_window or spec["ongoing"] else 0.35 * price
                        add({"pos": pos, "op": ["WATER"], "kind": "WATER",
                             "value": max(bonus, 0.3 * plan.action_value)})

                if units_now > 0 and age >= spec["first"]:
                    if spec["ongoing"]:
                        add({"pos": pos, "op": ["HARVEST"], "kind": "HARVEST",
                             "value": units_now * price})
                    else:
                        at_peak = (crop == "MELON" and (units_now >= 6 or age >= 10)) or (
                            crop != "MELON" and age >= spec["max_day"])
                        if at_peak or age > spec["max_day"] or days_left <= 1 or plan.phase == "LIQUIDATE":
                            # Holding ripe wheat after hour 14 cut the
                            # starter floor $56k → $53.5k: seed 9051 milk
                            # died at $175 (cows ate shed wheat we refused
                            # to replenish) and weeds rose on 9017/9068.
                            urg = 1.7 if age > spec["max_day"] else 1.0
                            add({"pos": pos, "op": ["HARVEST"], "kind": "HARVEST",
                                 "value": units_now * price * urg})
                continue

            if "animal" in tile:
                animal = tile.get("animal")
                spec = ANIMALS.get(animal)
                if spec is None:
                    continue
                prod = spec["product"]
                price = plan.price_hint.get(prod, MARKET_PARAMS[prod]["base"])
                unfed = int(tile.get("consecutive_unfed", 0) or 0)
                fed = bool(tile.get("fed_today", False))
                cared = bool(tile.get("cared_today", False))
                units_now = int(tile.get("yield_units", 0) or 0)
                if not fed:
                    animals_unfed += 1
                    future = (max(0, days_left - 1) / float(spec["interval"])) * price
                    val = (CRITICAL + future) if unfed >= 1 else (price / float(spec["interval"])) * 2.0
                    add({"pos": pos, "op": ["FEED"], "kind": "FEED",
                         "value": val, "need": "WHEAT"})
                if fed and not cared and days_left > spec["interval"]:
                    # Blanket 2*price*3 stole WATER: 9051 wheat 13→6,
                    # weeds 1→7, floor $59.1k→$53.3k. 9085 jumped +$7k.
                    # Raise CARE only after today's plants are watered.
                    if animal == "COW" and st.n_unwatered == 0:
                        care_val = 2.0 * price * 3.0
                    elif animal == "SHEEP" and st.n_unwatered == 0:
                        # Same watered-first gate as cows. Weaker than the
                        # cow boost so melon HARVEST ($1500) still wins nearby.
                        # Blanket CARE stole WATER; this stays off while
                        # plants are dry.
                        care_val = 2.0 * price * 2.0
                    else:
                        care_val = price * 0.95
                    add({"pos": pos, "op": ["CARE"], "kind": "CARE",
                         "value": care_val})
                if units_now > 0:
                    add({"pos": pos, "op": ["HARVEST"], "kind": "HARVEST",
                         "value": units_now * price})
                if tile.get("fertilizer_available"):
                    add({"pos": pos, "op": ["COLLECT_FERTILIZER"], "kind": "COLLECT",
                         "value": 0.85 * plan.price_hint.get("FERTILIZER", 100)})
                continue

    # Structures first: planting every empty tile is how a goose target of 8
    # dies on a 25-tile board. Reserve empties for missing coops/pastures,
    # then plant the rest. Never plant on hour 22+: consecutive_unwatered
    # starts at 1 and EOD makes a weed if nobody waters the same turn.
    # Cap on TOTAL structures (empty + occupied). have_c lags while workers
    # walk, so reserving `target - alive` every turn paved 47 empty coops.
    target_g = min(int(plan.animal_targets.get("GOOSE", 0) or 0), goose_cap(st))
    target_c = min(int(plan.animal_targets.get("COW", 0) or 0), pasture_cap(st, "MILK"))
    target_s = min(int(plan.animal_targets.get("SHEEP", 0) or 0), pasture_cap(st, "WOOL"))
    target_p = target_c + target_s
    # Structures lead living animals by at most 2. Targeting 24 geese and
    # reserving `target - n_coops` paved 19 empty sheds on seed 9000.
    inflight = 2
    shed_g = int(st.shed.get("GOOSE", 0) or 0)
    shed_p = int(st.shed.get("COW", 0) or 0) + int(st.shed.get("SHEEP", 0) or 0)
    alive_g = st.animals_alive["GOOSE"]
    alive_p = st.animals_alive["COW"] + st.animals_alive["SHEEP"]
    empty_past = sum(1 for _, k in st.empty_structs if k == "PASTURE")
    empty_coop = sum(1 for _, k in st.empty_structs if k == "COOP")
    need_coops = max(0, min(
        target_g - st.n_coops,
        (alive_g + shed_g + inflight) - st.n_coops,
        inflight,
        max(0, 3 - empty_coop),
    ))
    need_past = max(0, min(
        target_p - st.n_pastures,
        (alive_p + shed_p + inflight) - st.n_pastures,
        inflight,
        max(0, 3 - empty_past),
    ))
    can_stock_pasture = st.money >= 400 and (
        st.wheat_held() >= 2 or shed_p > 0 or st.n_animals >= 2)
    if not can_stock_pasture and shed_p <= 0:
        need_past = 0
    reserve_n = min(need_coops + need_past, len(empties))
    # Build next to the shed. Last-empties on a 75-tile board are SW, a
    # 9-step walk, so a dusk DROP used to bounce the cow and pave 15 sheds.
    def _shed_d(pos):
        return abs(pos[0] - 4) + abs(pos[1] - 4)
    near = sorted(empties, key=_shed_d)
    build_empties = near[:reserve_n]
    build_set = set(build_empties)
    plant_empties = [p for p in empties if p not in build_set]
    # Planters cannot water the same turn. Cap sow so leftover workers can
    # water new plants before EOD (consecutive_unwatered starts at 1).
    labor = effective_labor(st)
    hours_left = max(0, 22 - st.hour)
    sow_this_hour = max(0, labor // 2) if st.hour <= 16 else 0
    if st.hour <= 12 and len(empties) >= 8:
        sow_this_hour = max(sow_this_hour, min(max(0, labor - 3), 8))
    water_left = max(0, labor * hours_left - st.n_unwatered)
    spare = max(0, min(plant_slots(st) - st.n_plants, sow_this_hour, water_left))
    if plan.phase in ("HARVEST", "LIQUIDATE"):
        # Late sow is how 36 melon became 26 weeds after harvest on seed 9051.
        # Re-enabled HARVEST wheat sow (693afb2) cut median $65k → $58k with
        # 6–8 end weeds. Keep the field as of turn 500.
        spare = 0
    plant_empties = plant_empties[:spare]

    # crop_mix is a standing target, not a per-turn quota. Replanting the
    # whole mix every hour stacked 12 melon/day into 36 and crashed the book.
    want = {c: max(0, int(plan.crop_mix.get(c, 0) or 0) - on_board.get(c, 0))
            for c in CROPS}
    planted = {c: 0 for c in CROPS}
    # Wheat harvests leave empties; price_hint then sows strawberry into
    # the feed block (3 wheat / 12 straw, 12 cows starving). Feed first.
    # Reserving this-hour wheat (0e9a2f6) cut 9051 wheat 13→8 and the
    # floor $60.1k→$53.3k. 9085 straw stayed at 3 (plan cap, not sow).
    _sow_order = ["WHEAT"] + sorted(
        (k for k in want if k != "WHEAT"),
        key=lambda k: -plan.price_hint.get(k, 0),
    )
    if st.hour <= 16 and days_left >= 3:
        for pos in plant_empties:
            crop = None
            for c in _sow_order:
                if want[c] <= 0:
                    continue
                spec = CROPS[c]
                need_days = 11 if c == "MELON" else (spec["max_day"] + 1 if not spec["ongoing"]
                                                     else spec["first"] + 3)
                if need_days > days_left:
                    continue
                if st.seeds.get(c, 0) <= planted[c]:
                    continue
                crop = c
                break
            if crop is None:
                break
            want[crop] -= 1
            planted[crop] += 1
            units = Econ.planned_units(crop)
            net = units * plan.price_hint.get(crop, MARKET_PARAMS[crop]["base"]) - SEED_COST[crop]
            add({"pos": pos, "op": ["PLANT", crop], "kind": "PLANT",
                 "value": max(1.0, net)})

    bi = 0
    for _ in range(min(max(0, need_coops), len(build_empties))):
        add({"pos": build_empties[bi], "op": ["BUILD_COOP"], "kind": "BUILD",
             "value": 500 + 0.6 * plan.price_hint.get("EGG", 50) * max(1, days_left - 4)})
        bi += 1
    for _ in range(min(max(0, need_past), max(0, len(build_empties) - bi))):
        add({"pos": build_empties[bi], "op": ["BUILD_PASTURE"], "kind": "BUILD",
             "value": 0.4 * plan.price_hint.get("MILK", 160) * max(1, days_left - 8)})
        bi += 1

    st._empties = empties
    st._animals_unfed = animals_unfed
    return tasks


class KaggricultureAgent(object):
    def __init__(self):
        self.el = BayesianElasticityFilter()
        self.gate = LiquidationGateway()
        self.mpc = MPCRevenueEngine(self.el)
        self.calib = DirectionCalibrator()
        self.labor = LaborAssigner()
        self.last_sales = {}
        self.last_turn = -1
        self.opp_peak_tiles = {p: 0 for p in PRODUCTS}

    def _inv(self, st, idx):
        try:
            return dict(st.inventories[idx]) if idx < len(st.inventories) else {}
        except Exception:
            return {}

    def _nearest(self, src, cands):
        best, bd = None, None
        for c in cands:
            d = abs(c[0] - src[0]) + abs(c[1] - src[1])
            if bd is None or d < bd:
                best, bd = c, d
        return best, (bd if bd is not None else 99)

    def _goto_or(self, pos, dst, op):
        if tuple(pos) == tuple(dst):
            return list(op)
        verb = self.calib.step_toward(pos, dst)
        return [verb] if verb else ["PASS"]

    def act(self, obs):
        t0 = time.time()
        st = State(obs)
        self.last_turn = st.turn
        for p, n in st.opp_tiles_of.items():
            self.opp_peak_tiles[p] = max(int(self.opp_peak_tiles.get(p, 0) or 0), int(n or 0))
        st.refresh_book(self.opp_peak_tiles)
        self.calib.observe(st.farmer)
        self.el.observe(st.inventory, st.prices, self.last_sales, st.shops)
        self.gate.arm(st.turn)
        plan = self.mpc.maybe_replan(st)

        workers = [tuple(st.farmer)] + [tuple(h) for h in st.hands]
        n_hands = len(st.hands)
        actions = [None] * len(workers)
        shed_tiles = st.shed_access()
        try:
            tasks = build_tasks(st, plan)
        except Exception:
            tasks = []
        empty_structs = list(st.empty_structs)

        # --- committed duties (inventory already in hand) -------------------
        free_idx = []
        for i, wpos in enumerate(workers):
            inv = self._inv(st, i)
            carried_animal = next((a for a in ANIMALS if inv.get(a, 0) > 0), None)
            if carried_animal:
                want = ANIMAL_STRUCTURE[carried_animal]
                slots = [p for p, k in empty_structs if k == want]
                if slots:
                    dst, _ = self._nearest(wpos, slots)
                    empty_structs = [(p, k) for p, k in empty_structs if p != dst]
                    actions[i] = self._goto_or(wpos, dst, ["PLACE", carried_animal, 1])
                    continue
                # Seed 9000 vs starter paved 15 empty pastures: a worker
                # picked up a cow, dusk DROP returned it, and we built more
                # sheds against shed_p. Hold the animal until a slot exists.
                continue
            # FEED is inventory-gated. A worker holding wheat who is standing
            # on (or one step from) an unfed animal should feed before anything
            # else — a starved animal is an unrecoverable write-off.
            if inv.get("WHEAT", 0) > 0:
                feed = [t for t in tasks if t.get("need") == "WHEAT"]
                if feed:
                    dst, d = self._nearest(wpos, [t["pos"] for t in feed])
                    if d <= 2 or st.hour >= 20:
                        actions[i] = self._goto_or(wpos, dst, ["FEED"])
                        tasks = [t for t in tasks if not (t.get("need") == "WHEAT" and t["pos"] == dst)]
                        continue
            if inv.get("FERTILIZER", 0) > 0:
                fert_tiles = []
                for y, row in enumerate(st.tiles):
                    for x, tile in enumerate(row):
                        if (isinstance(tile, dict) and tile.get("kind") == "PLANT"
                                and not CROPS.get(tile.get("crop"), {}).get("ongoing", True)
                                and int(tile.get("fertilized_until_day", -1) or -1) < st.day
                                and _age(st, tile) < CROPS[tile["crop"]]["max_day"]):
                            fert_tiles.append((x, y))
                if fert_tiles:
                    dst, d = self._nearest(wpos, fert_tiles)
                    if d <= 3:
                        actions[i] = self._goto_or(wpos, dst, ["FERTILIZE"])
                        continue
            produce = sum(int(v or 0) for k, v in inv.items()
                          if k in PRODUCTS)
            near_crit = any(
                abs(t["pos"][0] - wpos[0]) + abs(t["pos"][1] - wpos[1]) <= 1
                and t["value"] >= CRITICAL for t in tasks)
            deliver = (produce >= 4 or st.hour >= 18 or self.gate.armed
                       or st.shed_total > SHED_CAPACITY * 0.80)
            if produce > 0 and deliver and not near_crit:
                dst, _ = self._nearest(wpos, shed_tiles)
                actions[i] = self._goto_or(wpos, dst, ["DROP"])
                continue
            free_idx.append(i)

        # --- shed fetch: wheat for the herd, animals for empty structures ---
        unfed = getattr(st, "_animals_unfed", 0)
        wheat_on_workers = sum(int(self._inv(st, i).get("WHEAT", 0) or 0) for i in range(len(workers)))
        need_wheat = max(0, unfed - wheat_on_workers)
        if need_wheat > 0 and st.shed.get("WHEAT", 0) > 0 and free_idx:
            i = min(free_idx, key=lambda k: min(
                abs(workers[k][0] - s[0]) + abs(workers[k][1] - s[1]) for s in shed_tiles))
            wpos = workers[i]
            dst, _ = self._nearest(wpos, shed_tiles)
            n = int(min(8, need_wheat, st.shed.get("WHEAT", 0)))
            actions[i] = self._goto_or(wpos, dst, ["PICKUP", "WHEAT", n])
            free_idx = [k for k in free_idx if k != i]

        pending_animals = []
        if any(k == "PASTURE" for _, k in empty_structs):
            if st.shed.get("COW", 0):
                pending_animals.append("COW")
            if st.shed.get("SHEEP", 0):
                pending_animals.append("SHEEP")
        if st.shed.get("GOOSE", 0):
            pending_animals.append("GOOSE")
        for pending_animal in pending_animals:
            if not free_idx:
                break
            want = ANIMAL_STRUCTURE[pending_animal]
            if not any(k == want for _, k in empty_structs):
                continue
            i = free_idx[0]
            wpos = workers[i]
            dst, _ = self._nearest(wpos, shed_tiles)
            actions[i] = self._goto_or(wpos, dst, ["PICKUP", pending_animal, 1])
            free_idx = free_idx[1:]

        if (st.shed.get("FERTILIZER", 0) > 0 and free_idx and st.hour <= 8
                and plan.phase in ("EXPAND", "COMPOUND")):
            i = free_idx[0]
            wpos = workers[i]
            dst, d = self._nearest(wpos, shed_tiles)
            if d <= 2:
                actions[i] = self._goto_or(wpos, dst, ["PICKUP", "FERTILIZER", 1])
                free_idx = free_idx[1:]

        field_tasks = [t for t in tasks if t.get("need") != "WHEAT"]
        feed_left = [t for t in tasks if t.get("need") == "WHEAT"]
        holders = [i for i in free_idx if self._inv(st, i).get("WHEAT", 0) > 0]
        others = [i for i in free_idx if i not in holders]
        claimed = set()

        def _apply(idxs, pool):
            if not idxs or not pool or time.time() - t0 >= TURN_BUDGET_S:
                for i in idxs:
                    if actions[i] is None:
                        actions[i] = ["PASS"]
                return
            chosen = self.labor.assign([workers[i] for i in idxs], pool)
            for slot, i in enumerate(idxs):
                t = chosen[slot] if slot < len(chosen) else None
                if t is None or id(t) in claimed:
                    actions[i] = ["PASS"]
                    continue
                if t.get("need") == "WHEAT" and self._inv(st, i).get("WHEAT", 0) <= 0:
                    actions[i] = ["PASS"]
                    continue
                claimed.add(id(t))
                actions[i] = self._goto_or(workers[i], t["pos"], t["op"])

        _apply(holders, feed_left + field_tasks)
        remain = [t for t in field_tasks if id(t) not in claimed]
        _apply(others, remain)

        for i in range(len(actions)):
            if not actions[i]:
                actions[i] = ["PASS"]

        farmer_action = actions[0] if actions else ["PASS"]
        self.calib.note_issued(farmer_action[0], st.farmer)
        hand_actions = actions[1:1 + n_hands]
        while len(hand_actions) < n_hands:
            hand_actions.append(["PASS"])

        market = self._market(st, plan)
        self.last_sales = {}
        for o in market:
            if o and o[0] == "SELL":
                self.last_sales[o[1]] = self.last_sales.get(o[1], 0) + int(o[2])
        return {"farmer": farmer_action, "hands": hand_actions, "market": market}

    def _market(self, st, plan):
        days_left = max(0, DAYS - st.day)
        herd = st.n_animals
        reserve_wheat = plan.wheat_reserve if not self.gate.armed else 0
        reserve_wheat = max(reserve_wheat, herd * (1 if self.gate.armed else 2))
        # herd*5 reserve (ca910d7) collapsed 9017 to $9.5k: we stopped
        # selling the log-curve staple and the till died. Keep the
        # 2-per-head ration.

        cash_tight = st.money < 1400 or (
            st.next_land_cost is not None and st.money < st.next_land_cost + 300)
        orders = []
        for prod in PRODUCTS:
            held = int(st.shed.get(prod, 0) or 0)
            if prod == "WHEAT":
                held = max(0, held - reserve_wheat)
            if held <= 0:
                continue
            inv = st.inventory.get(prod, MARKET_I0)
            drain = self.el.drain_rate.get(prod, 0.0)
            if self.gate.armed:
                n = self.gate.units_this_turn(
                    prod, held, inv, drain, st.turn,
                    opp_remain=st.opp_flow.get(prod, st.opp_pipeline.get(prod, 0.0)),
                    opp_imminent=st.opp_imminent.get(prod, 0.0))
            else:
                floor = plan.reserve.get(prod, 1.0)
                if st.opp_flow.get(prod, 0) > 0 and prod in PREMIUM:
                    floor *= 0.88
                if st.stance == "LOCK" and prod in PREMIUM:
                    floor *= 1.08
                elif st.stance == "CONTEST" and prod in PREMIUM:
                    floor *= 0.78
                if cash_tight and prod in STAPLES:
                    floor = min(floor, 0.35 * MARKET_PARAMS[prod]["base"])
                sellable = Econ.units_until(prod, inv, max(1.0, floor))
                turns_to_gate = max(1, LIQUIDATION_TURN - st.turn)
                rate = max(drain, held / float(turns_to_gate), 1.0)
                if prod in STAPLES:
                    n = int(min(held, max(sellable, held if cash_tight else 0), 40))
                    if n == 0:
                        n = int(min(held, sellable))
                else:
                    n = int(min(held, sellable, math.ceil(rate * 2.0)))
                    # Beat their harvest onto the book: if they are 0-2 days
                    # from dumping this premium, sell our lot first.
                    if st.opp_imminent.get(prod, 0) > 0:
                        n = int(min(held, max(n, math.ceil(held * 0.40)), sellable or held))
                if st.shed_total > SHED_CAPACITY * 0.75:
                    n = max(n, min(held, 12))
            if n > 0:
                orders.append(["SELL", prod, int(n)])
        orders.sort(key=lambda o: -Econ.price(o[1], st.inventory.get(o[1], MARKET_I0)) * o[2])

        if self.gate.armed:
            return orders[:MAX_MARKET_ORDERS]

        budget = float(st.money)
        for o in orders:
            budget += Econ.marginal_revenue(o[1], st.inventory.get(o[1], MARKET_I0), o[2])

        # Capital-velocity: cash sell, a few HIREs, wheat, land, animals, rest.
        # Eight HIREs at hour 0 used 8 of 10 order slots and dropped wheat /
        # land / geese — the same 10-order cap that used to drop HIREs, with
        # the crowding reversed. Four HIREs/turn fill a 12-hand crew by hour 3
        # and leave room for the ramp.
        hires = []
        core = []
        seeds = []
        pending_wheat = 0

        def _spend(dest, order, cost):
            dest.append(order)
            return budget - cost

        # Engine: farm["hands"] = [] at EOD. The crew does not accumulate.
        # Re-hire every morning. Fib(0..11) ≈ 376/day.
        need_hands = max(0, plan.target_hands - len(st.hands))
        n = st.hires_today
        living = len(st.hands)
        # hires_today already arrived as hands. 4 living + 4 earlier HIREs
        # looking like a staffed crew is how scaler seed 9000 kept 4 workers:
        # the $400 float then blocked the rest.
        staffed_now = living >= 8
        reserved = 1  # wheat
        land_now = live_buy_land(st, plan)
        if staffed_now and land_now:
            reserved += 1
        if staffed_now and any(int(v or 0) > 0 for v in (plan.animal_targets or {}).values()):
            reserved += 2
        reserved += 1  # one sell
        if staffed_now:
            reserved += 1  # seeds
        hire_slots = max(2, MAX_MARKET_ORDERS - reserved)
        need_pasture_buy = any(
            int(plan.animal_targets.get(a, 0) or 0)
            > st.animals_alive.get(a, 0) + int(st.shed.get(a, 0) or 0)
            for a in ("COW", "SHEEP")
        )
        # Seed 9051 printed $0 and 4 hands: 3 HIREs then cows spent the till.
        # Four HIREs until 8 are living or landing this pack; cows wait.
        # Fib(0..7) ≈ $54.
        per_turn = min(need_hands, hire_slots, 4 if not staffed_now else (3 if need_pasture_buy else 4))
        float_cash = 400.0
        queued = 0
        for _ in range(per_turn):
            c = fib(n)
            if budget < c:
                break
            if living + queued >= 8 and budget < c + float_cash:
                break
            budget = _spend(hires, ["HIRE"], c)
            n += 1
            queued += 1
        staff_first = (living + queued) < 8

        short = reserve_wheat - st.wheat_held()
        # Feed the living herd plus the next few buys, not the 24-head target.
        short = max(short, 3 * (herd + 2) - st.wheat_held())
        if short > 0 and (herd > 0 or plan.animal_targets.get("GOOSE", 0) > 0):
            price = Econ.price("WHEAT", st.inventory.get("WHEAT", MARKET_I0))
            afford = int(min(max(short, 1), max(0.0, budget - 400) // max(1.0, price), 16))
            if afford > 0:
                budget = _spend(core, ["BUY_PRODUCT", "WHEAT", afford], afford * price)
                pending_wheat = afford

        # Density-crop seeds before extra geese. 18 geese at $246 left
        # seed 9000 with zero melon and $13.8k; the $28k farm was 8 geese
        # plus melon sold into a still-alive book.
        land_now = live_buy_land(st, plan)
        geese_alive = st.animals_alive.get("GOOSE", 0)
        # SW first in the pack. Seeds-then-cows-then-land never issued
        # (three CI runs, every seed locked=50). Keep $400 after the $2000.
        if (not staff_first and land_now and st.next_land_cost
                and st.next_land_cost >= 2000
                and geese_alive >= 4
                and budget >= st.next_land_cost + 400):
            budget = _spend(core, ["BUY_LAND"], st.next_land_cost)
            land_now = False

        if not staff_first:
            # $56k floor seeds had 4 wheat on 24 animals: strawberry/melon
            # seeds took the 10-order cap. Feed seeds first.
            want_w = int(plan.crop_mix.get("WHEAT", 0) or 0)
            if want_w >= 2:
                have_w = int(st.seeds.get("WHEAT", 0) or 0) + int(st.crops_alive.get("WHEAT", 0) or 0)
                # Egg dump was bit-identical (staples already sell).
                # 9017 mid wheat is 6; want is 12. Seed cap 16 can
                # starve replants after harvest. Buy up to 24.
                need_w = max(0, min(want_w, 24) - have_w)
                cost_w = SEED_COST["WHEAT"]
                afford_w = int(min(need_w, max(0.0, budget - 400) // cost_w)) if cost_w else 0
                if afford_w > 0:
                    budget = _spend(core, ["BUY_SEED", "WHEAT", afford_w], afford_w * cost_w)

            for crop in ("STRAWBERRY", "MELON"):
                want = int(plan.crop_mix.get(crop, 0) or 0)
                if want <= 0:
                    continue
                spec = CROPS[crop]
                need_days = 11 if crop == "MELON" else spec["max_day"] + 1
                if need_days > days_left:
                    continue
                have = int(st.seeds.get(crop, 0) or 0)
                standing = int(st.crops_alive.get(crop, 0) or 0)
                need = max(0, min(want, 6) - have - standing)
                cost = SEED_COST[crop]
                keep = 400
                afford = int(min(need, max(0.0, budget - keep) // cost)) if cost else 0
                if afford > 0:
                    budget = _spend(core, ["BUY_SEED", crop, afford], afford * cost)

            cows_needed = (
                int(plan.animal_targets.get("COW", 0) or 0)
                > st.animals_alive.get("COW", 0) + int(st.shed.get("COW", 0) or 0)
            )
            sheep_needed = (
                int(plan.animal_targets.get("SHEEP", 0) or 0)
                > st.animals_alive.get("SHEEP", 0) + int(st.shed.get("SHEEP", 0) or 0)
            )
            # NE ($1000) still goes here. SW already issued above.
            land_after_geese = bool(
                land_now and st.next_land_cost and st.next_land_cost >= 2000
                and geese_alive < 4)
            land_after_pasture = False
            if (land_now and st.next_land_cost
                    and not land_after_geese and not land_after_pasture
                    and budget >= st.next_land_cost + 400):
                budget = _spend(core, ["BUY_LAND"], st.next_land_cost)

            wheat_next = st.wheat_held() + pending_wheat
            g_cap_buy = goose_buy_cap(st, plan)
            for animal in ("GOOSE", "COW", "SHEEP"):
                target = plan.animal_targets.get(animal, 0)
                alive = st.animals_alive.get(animal, 0)
                in_shed = int(st.shed.get(animal, 0) or 0)
                need = target - alive - in_shed
                cost = ANIMAL_COST[animal]
                if need <= 0 or days_left <= ANIMALS[animal]["first"] + 2:
                    continue
                if animal == "GOOSE" and (alive + in_shed) >= g_cap_buy:
                    continue
                if animal != "GOOSE":
                    prod = ANIMAL_PRODUCT[animal]
                    if (alive + in_shed) >= max(1, pasture_cap(st, prod)):
                        continue
                    # LOCK vacates a dying book, not a healthy $300 milk quote.
                    if st.stance == "LOCK":
                        quote = Econ.price(prod, st.inventory.get(prod, MARKET_I0))
                        if product_contested(st, prod) or quote < 0.90 * MARKET_PARAMS[prod]["base"]:
                            continue
                    if (st.animals_alive.get("GOOSE", 0) + int(st.shed.get("GOOSE", 0) or 0)) < 2:
                        continue
                want = ANIMAL_STRUCTURE[animal]
                housed = st.n_coops if animal == "GOOSE" else st.n_pastures
                empty_for = sum(1 for _, k in st.empty_structs if k == want)
                if empty_for <= 0 and housed >= max(target, 1):
                    continue
                if wheat_next < 2:
                    price = Econ.price("WHEAT", st.inventory.get("WHEAT", MARKET_I0))
                    afford = int(min(4, max(0.0, budget - 400) // max(1.0, price), 8))
                    if afford > 0:
                        budget = _spend(core, ["BUY_PRODUCT", "WHEAT", afford], afford * price)
                        pending_wheat += afford
                        wheat_next += afford
                    if wheat_next < 2:
                        continue
                if (animal == "GOOSE" and land_now and st.next_land_cost is not None
                        and alive >= 8 and (cows_needed or sheep_needed)
                        and budget < st.next_land_cost + 400):
                    continue
                bought = 0
                pasture_wanted = cows_needed or sheep_needed
                if animal == "COW":
                    quote_m = Econ.price("MILK", st.inventory.get("MILK", MARKET_I0))
                    need = min(need, max(0, 14 - alive - in_shed))
                    if need <= 0:
                        continue
                    if quote_m < 1.05 * MARKET_PARAMS["MILK"]["base"] and (alive + in_shed) >= 10:
                        continue
                    cap = 1 if (alive + in_shed) >= 12 else 2
                elif (animal == "GOOSE" and not pasture_wanted
                      and wheat_next >= 4 * (st.n_animals + 1)):
                    cap = 2
                else:
                    cap = 1
                while need > 0 and bought < cap:
                    if budget < cost + 400:
                        break
                    budget = _spend(core, ["BUY_ANIMAL", animal, 1], cost)
                    need -= 1
                    bought += 1
                    wheat_next = max(0, wheat_next - 2)

            if (land_now and st.next_land_cost
                    and (land_after_geese or land_after_pasture)
                    and budget >= st.next_land_cost + 400):
                budget = _spend(core, ["BUY_LAND"], st.next_land_cost)

            seed_order = ("STRAWBERRY", "MELON", "WHEAT", "CARROT", "TOMATO")
            for crop in seed_order:
                want = plan.crop_mix.get(crop, 0)
                spec = CROPS[crop]
                need_days = 11 if crop == "MELON" else spec["max_day"] + 1
                if want <= 0 or need_days > days_left:
                    continue
                have = int(st.seeds.get(crop, 0) or 0)
                standing = int(st.crops_alive.get(crop, 0) or 0)
                need = max(0, min(int(want), st.usable_tiles) - have - standing)
                if need <= 0:
                    continue
                cost = SEED_COST[crop]
                keep = 400
                if crop == "MELON":
                    geese_need = max(0, goose_buy_cap(st, plan) - st.animals_alive.get("GOOSE", 0))
                    keep = max(keep, 250 + 300 * min(2, geese_need))
                elif crop == "STRAWBERRY":
                    # 34 strawberry seeds at $100 left seed 9051 with $9 and 7 hands.
                    keep = 400
                    need = min(need, 6)
                afford = int(min(need, max(0.0, budget - keep) // cost)) if cost else 0
                if afford > 0:
                    budget = _spend(seeds, ["BUY_SEED", crop, afford], afford * cost)

        cash_sells = orders[:2]
        rest_sells = orders[2:]
        # Sells first so HIRE has cash. Hires before cows so seed 9051
        # cannot print $0 / 4 hands (cows ate the till after a failed dawn hire).
        # Shipping orders[1] after core (a9e2b62) dried mid-cash: 9034
        # $10.6k→$5.6k and the floor $59.2k→$57.4k.
        packed = cash_sells[:1] + hires + core + rest_sells + seeds
        return packed[:MAX_MARKET_ORDERS]


_AGENTS = {}


def agent(obs, config=None):
    """Kaggle entrypoint. Never raises."""
    try:
        player = int(_get(obs, "player", 0) or 0)
    except Exception:
        player = 0
    try:
        inst = _AGENTS.get(player)
        if inst is None:
            inst = _AGENTS[player] = KaggricultureAgent()
        action = inst.act(obs)
        if not isinstance(action, dict):
            return dict(SAFE_ACTION)
        action.setdefault("farmer", ["PASS"])
        action.setdefault("hands", [])
        action.setdefault("market", [])
        if not isinstance(action["farmer"], list) or not action["farmer"]:
            action["farmer"] = ["PASS"]
        if not isinstance(action["hands"], list):
            action["hands"] = []
        if not isinstance(action["market"], list):
            action["market"] = []
        action["market"] = action["market"][:MAX_MARKET_ORDERS]
        return action
    except Exception:
        return {"farmer": ["PASS"], "hands": [], "market": []}


__all__ = ["agent", "KaggricultureAgent", "Econ"]
