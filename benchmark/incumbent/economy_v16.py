"""economy_v18cm — E21: emerg only if projected overnight cash misses land until day>=11.

Chassis: ba (rece-if-emerg, _EMERG_LAND fix). Never blanket d8.
Calibrated: wait through day10 evening wave; emerg if money+OVERNIGHT_EST*nights < land_need_normal.
Spares classic 8100 (fills d9) and starter 9101 (fills d11); helps 9117-class late land.
Zero kaggle submit.
Promoted local main 2026-09-18 IST. Zero kaggle submit until owner OK.
"""
from __future__ import annotations

from typing import Any

PASS = {"farmer": ["PASS"], "hands": [], "market": []}

# E18az+: soft recovery ONLY after emergency land (not normal packed land)
_LAND1_DAY = None
_LAST_DAY_SEEN = -1
_EMERG_LAND = False
_OPP_M_AT_D8 = None


def _post_land_recovery(day, unlocked):
    global _LAND1_DAY, _LAST_DAY_SEEN, _EMERG_LAND, _OPP_M_AT_D8
    if day < _LAST_DAY_SEEN or day == 0:
        _LAND1_DAY = None
        _EMERG_LAND = False
        _OPP_M_AT_D8 = None
    _LAST_DAY_SEEN = day
    if len(unlocked) <= 1:
        return False
    if not _EMERG_LAND:
        return False  # normal land: no soft recovery (spares 8100)
    if _LAND1_DAY is None:
        _LAND1_DAY = day
    return day <= _LAND1_DAY + 1


BOARD = 10
SHED = ((4, 4), (5, 4), (4, 5), (5, 5))
LAND_COSTS = (1000, 2000, 4000)
I0 = 10000

# Labor / land / livestock (v3)
TARGET_HANDS = 9  # E6g: daily 9 hands (fib +34 vs 8; pays vs starter)
HIRE_DAY0 = 5
LAND_TARGET = 1  # LAND2 off (E6b/f regressed)
LAND_FROM_DAY = 6
LAND2_FROM_DAY = 8
LAND_BUFFER = 700
LAND2_BUFFER = 1200
# E14: packed first-land (start quad only → unlock NE)
PACKED_LAND_BUFFER = 400
PACKED_OCC_MIN = 0.9
PACKED_LAND_FROM_DAY = 8
COW_TARGET = 6
COW_TARGET_WEAK = 4  # when town milk demand is thin
SHEEP_TARGET = 4
SHEEP_TARGET_YARN = 7  # E6c: yarn>=2 modest scale (was 6; avoid E3 sheep5 blind)
SHEEP_TARGET_YARN1 = 5  # yarn==1 mild tilt
ANIMAL_BATCH = 2
FEED_RESERVE_DAYS = 6
FEED_MIN_DAYS = 2
FEED_PRESSURE_DAYS = 3  # keep less wheat when shed pressured
MAX_WHEAT_PRICE = 55
WHEAT_BATCH = 24
INVEST_UNTIL = 22
LIQUIDATE_FROM = 27
ANIMAL_HARVEST_AT = 2
SHED_PRESSURE = 75
SHED_SOFT = 65
CARRY = 6
MAX_MARKET = 10
DROP_PRODUCE = ("MELON", "STRAWBERRY", "MILK", "WOOL", "EGG", "TOMATO", "CARROT", "FERTILIZER")
DROP_THRESHOLD = 3  # mid-game produce relay to shed
DROP_THRESHOLD_LIQ = 1
DROP_AFTER_HOUR = 8
LABOR_HEADROOM = 2  # free job slots before buying more animals
WHEAT_SELL_FROM_DAY = 24  # E8: no invest-phase wheat dumps (anti-churn)
WHEAT_BUY_CAP = 16  # E8: smaller per-order buy vs thrash batches
FEED_RESERVE_STABLE = 5  # E8: fixed days; do not shrink under shed pressure

# Town shop → product demand (engine SHOPS; single-product shops consume 2x)
SHOP_PRODUCTS = {
    "BAKERY": ("EGG", "WHEAT"),
    "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
    "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"),
    "YARN_STORE": ("WOOL",),
    "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"),
    "PET_CAFE": ("CARROT",),
    "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
    "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
}

# Crop program
SEED_STOCK_WHEAT = 10
SEED_STOCK_MELON = 10
SEED_STOCK_STRAW = 8
MELON_TARGET = 10
STRAW_TARGET = 8
WHEAT_PLANT_TARGET = 8
MELON_PLANT_UNTIL = 16
STRAW_PLANT_UNTIL = 18
WHEAT_PLANT_UNTIL = 24
SEED_COST = {"WHEAT": 10, "MELON": 80, "STRAWBERRY": 100}
MELON_FIRST, MELON_MAX = 10, 12
STRAW_FIRST = 10
WHEAT_FIRST, WHEAT_MAX = 2, 4
FERT_STOCK = 6
MELON_BONUS_START = 6

SELL_CHUNK = {
    "MILK": 6,
    "WOOL": 4,
    "MELON": 8,
    "STRAWBERRY": 6,
    "EGG": 20,
    "WHEAT": 20,
    "CARROT": 20,
    "TOMATO": 12,
    "FERTILIZER": 12,
}
# Soft floors (calibrated): milk book often sits 70–100; 90 was too sticky.
PRICE_FLOOR = {
    "MELON": 120,
    "MILK": 55,
    "WOOL": 45,
    "STRAWBERRY": 55,
}
HARD_FLOOR = {
    "MELON": 40,
    "MILK": 25,
    "WOOL": 20,
    "STRAWBERRY": 25,
}
GLUT_ABOVE = {"MELON": 80, "MILK": 40, "WOOL": 30, "STRAWBERRY": 40}
GLUT_CHUNK = {"MELON": 4, "MILK": 3, "WOOL": 2, "STRAWBERRY": 3}

ANIMAL_COST = {"COW": 400, "SHEEP": 500, "GOOSE": 300}


def _g(o: Any, k: str, d=None):
    try:
        return o[k]
    except Exception:
        return getattr(o, k, d)


def _d(o: Any) -> dict:
    if o is None:
        return {}
    if isinstance(o, dict):
        return dict(o)
    try:
        return dict(o)
    except Exception:
        return {}


def _turn(obs) -> int:
    return int(_g(obs, "day", 0) or 0) * 24 + int(_g(obs, "hour", 0) or 0)


def _man(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _step(fx, fy, tx, ty):
    dx, dy = tx - fx, ty - fy
    if abs(dx) >= abs(dy) and dx:
        return ["EAST"] if dx > 0 else ["WEST"]
    if dy:
        return ["SOUTH"] if dy > 0 else ["NORTH"]
    if dx:
        return ["EAST"] if dx > 0 else ["WEST"]
    return ["PASS"]


def _tile(tiles, x, y):
    try:
        return tiles[y][x]
    except Exception:
        return None


def _shed_tile(tiles):
    for p in SHED:
        if _tile(tiles, p[0], p[1]) != "LOCKED":
            return p
    return SHED[0]


def _carried(invs, item):
    s = 0
    for inv in invs or []:
        s += int(_d(inv).get(item, 0) or 0)
    return s


def _opp_crops(obs, player: int) -> dict:
    out = {"MELON": 0, "STRAWBERRY": 0, "WHEAT": 0, "n_plants": 0}
    farms = _g(obs, "farms", []) or []
    if len(farms) < 2:
        return out
    opp = farms[1 - int(player)]
    tiles = _g(opp, "tiles")
    if not tiles:
        return out
    for y in range(BOARD):
        for x in range(BOARD):
            t = _tile(tiles, x, y)
            if not isinstance(t, dict):
                continue
            if t.get("kind") == "PLANT" or "crop" in t:
                crop = t.get("crop")
                out["n_plants"] += 1
                if crop in out:
                    out[crop] += 1
    return out


def _town_demand(obs) -> dict:
    """Approx daily town drain units per product from unlocked shops + center."""
    town = _g(obs, "town", {}) or {}
    shops = list(_g(town, "unlocked_shops", []) or [])
    # shops fire every 4 turns → 6x/day; single-product shops use multiplier 2
    per_day = 6
    out = {"MILK": 1, "WOOL": 1, "STRAWBERRY": 1, "MELON": 1, "WHEAT": 1, "EGG": 1}
    # town center: +1/day each non-fert product (already seeded as 1)
    milk_shops = yarn = straw_shops = 0
    for name in shops:
        products = SHOP_PRODUCTS.get(name, ())
        mult = 2 if len(products) == 1 else 1
        for p in products:
            if p in out:
                out[p] += per_day * mult
        if "MILK" in products:
            milk_shops += 1
        if name == "YARN_STORE":
            yarn += 1
        if "STRAWBERRY" in products:
            straw_shops += 1
    out["milk_shops"] = milk_shops
    out["yarn"] = yarn
    out["straw_shops"] = straw_shops
    out["n_shops"] = len(shops)
    return out


def _should_harvest_plant(crop, age, yu, day, liquidate):
    if yu <= 0:
        return False
    if liquidate or day >= LIQUIDATE_FROM - 1:
        return True
    if crop == "WHEAT":
        return age >= WHEAT_MAX
    if crop == "MELON":
        # E10-melon: harvest at yield cap / peak age (engine max at ~10), not age 12
        return yu >= 6 or age >= MELON_FIRST
    if crop == "STRAWBERRY":
        return yu >= 2 or age >= STRAW_FIRST + 6
    return age >= 10 and yu > 0


def _scan(me, day, liquidate):
    tiles = _g(me, "tiles")
    feed, water, harvest, care, dig = [], [], [], [], []
    fert, collect = [], []
    free_p, free_c = [], []
    n_cow = n_sheep = n_goose = n_pasture = n_coop = 0
    n_wheat = n_melon = n_straw = n_plants = 0
    empties = []
    owned = 0

    for y in range(BOARD):
        for x in range(BOARD):
            t = _tile(tiles, x, y)
            pos = (x, y)
            if t is None:
                owned += 1
                empties.append(pos)
                continue
            if t == "LOCKED":
                continue
            owned += 1
            if not isinstance(t, dict):
                continue
            kind = t.get("kind")
            if kind == "WEED":
                dig.append({"pos": pos, "op": ["DIG"], "need": None})
            elif kind == "PLANT" or "crop" in t:
                n_plants += 1
                crop = t.get("crop")
                if crop == "WHEAT":
                    n_wheat += 1
                elif crop == "MELON":
                    n_melon += 1
                elif crop == "STRAWBERRY":
                    n_straw += 1
                if not t.get("watered_today"):
                    water.append({"pos": pos, "op": ["WATER"], "need": None})
                planted = int(t.get("planted_day", day) or day)
                age = day - planted
                yu = int(t.get("yield_units", 0) or 0)
                fert_until = int(t.get("fertilized_until_day", -1) or -1)
                if (
                    crop == "MELON"
                    and MELON_BONUS_START <= age <= MELON_MAX
                    and day > fert_until
                    and not liquidate
                ):
                    fert.append({"pos": pos, "op": ["FERTILIZE"], "need": ("FERTILIZER", 1)})
                if _should_harvest_plant(crop, age, yu, day, liquidate):
                    harvest.append({"pos": pos, "op": ["HARVEST"], "need": None})
            elif kind == "PASTURE":
                n_pasture += 1
                if "animal" not in t:
                    free_p.append(pos)
                else:
                    an = t["animal"]
                    if an == "COW":
                        n_cow += 1
                    elif an == "SHEEP":
                        n_sheep += 1
                    if not t.get("fed_today"):
                        feed.append({"pos": pos, "op": ["FEED"], "need": ("WHEAT", 1)})
                    if not t.get("cared_today"):
                        care.append({"pos": pos, "op": ["CARE"], "need": None})
                    if t.get("fertilizer_available"):
                        collect.append({"pos": pos, "op": ["COLLECT_FERTILIZER"], "need": None})
                    yu = int(t.get("yield_units", 0) or 0)
                    if yu >= ANIMAL_HARVEST_AT or (yu > 0 and day >= LIQUIDATE_FROM):
                        harvest.append({"pos": pos, "op": ["HARVEST"], "need": None})
            elif kind == "COOP":
                n_coop += 1
                if "animal" not in t:
                    free_c.append(pos)
                else:
                    n_goose += 1
                    if not t.get("fed_today"):
                        feed.append({"pos": pos, "op": ["FEED"], "need": ("WHEAT", 1)})
                    if not t.get("cared_today"):
                        care.append({"pos": pos, "op": ["CARE"], "need": None})
                    if t.get("fertilizer_available"):
                        collect.append({"pos": pos, "op": ["COLLECT_FERTILIZER"], "need": None})
                    yu = int(t.get("yield_units", 0) or 0)
                    if yu >= ANIMAL_HARVEST_AT or (yu > 0 and day >= LIQUIDATE_FROM):
                        harvest.append({"pos": pos, "op": ["HARVEST"], "need": None})

    empties.sort(key=lambda p: _man(p, (4, 4)))
    return {
        "feed": feed,
        "water": water,
        "harvest": harvest,
        "care": care,
        "dig": dig,
        "fert": fert,
        "collect": collect,
        "free_p": free_p,
        "free_c": free_c,
        "n_cow": n_cow,
        "n_sheep": n_sheep,
        "n_goose": n_goose,
        "n_animals": n_cow + n_sheep + n_goose,
        "n_pasture": n_pasture,
        "n_coop": n_coop,
        "n_plants": n_plants,
        "n_wheat": n_wheat,
        "n_melon": n_melon,
        "n_straw": n_straw,
        "empties": empties,
        "owned": owned,
    }


def _pick_crop(scan, seeds, day, planting, straw_tgt=None, recover=False):
    if not planting:
        return None
    st = STRAW_TARGET if straw_tgt is None else straw_tgt
    if recover:
        if day <= WHEAT_PLANT_UNTIL and scan["n_wheat"] < WHEAT_PLANT_TARGET and int(seeds.get("WHEAT", 0) or 0) > 0:
            return "WHEAT"
        if day <= MELON_PLANT_UNTIL and scan["n_melon"] < MELON_TARGET and int(seeds.get("MELON", 0) or 0) > 0:
            return "MELON"
        if day <= STRAW_PLANT_UNTIL and scan["n_straw"] < st and int(seeds.get("STRAWBERRY", 0) or 0) > 0:
            return "STRAWBERRY"
        return None
    if day <= MELON_PLANT_UNTIL and scan["n_melon"] < MELON_TARGET and int(seeds.get("MELON", 0) or 0) > 0:
        return "MELON"
    if day <= STRAW_PLANT_UNTIL and scan["n_straw"] < st and int(seeds.get("STRAWBERRY", 0) or 0) > 0:
        return "STRAWBERRY"
    if day <= WHEAT_PLANT_UNTIL and scan["n_wheat"] < WHEAT_PLANT_TARGET and int(seeds.get("WHEAT", 0) or 0) > 0:
        return "WHEAT"
    return None


def _jobs(scan, me, priv, day, liquidate, planting):
    tiles = _g(me, "tiles")
    shed = _d(_g(priv, "shed", {}))
    seeds = _d(_g(priv, "seeds", {}))
    invs = list(_g(priv, "inventories", []) or [])
    unlocked = list(_g(me, "unlocked_quadrants", ["NW"]) or ["NW"])
    recover = _post_land_recovery(day, unlocked)
    # E15e: modest densify only after land open + feed float
    flock = scan["n_animals"] + int(shed.get("COW", 0) or 0) + int(shed.get("SHEEP", 0) or 0) + int(shed.get("GOOSE", 0) or 0)
    feed_ok = (_carried(invs, "WHEAT") + int(shed.get("WHEAT", 0) or 0)) >= max(8, flock * FEED_MIN_DAYS)
    straw_tgt = 10 if (len(unlocked) > 1 and feed_ok) else STRAW_TARGET
    sp = _shed_tile(tiles)
    jobs = []

    need = len(scan["feed"]) - _carried(invs, "WHEAT")
    if need > 0 and shed.get("WHEAT", 0) > 0:
        n_units = 1 + len(_g(me, "hands", []) or [])
        # E8: more parallel wheat pickups when many mouths unfed (free later labor)
        trips = min(max(1, need), n_units, 6)
        qty = min(CARRY, int(shed["WHEAT"]), max(1, need))
        for _ in range(trips):
            jobs.append({"pos": sp, "op": ["PICKUP", "WHEAT", qty], "need": None, "skip": "WHEAT"})

    fert_need = len(scan["fert"]) - _carried(invs, "FERTILIZER")
    if fert_need > 0 and int(shed.get("FERTILIZER", 0) or 0) > 0:
        trips = min(fert_need, int(shed.get("FERTILIZER", 0) or 0), 3)
        for _ in range(trips):
            jobs.append({"pos": sp, "op": ["PICKUP", "FERTILIZER", 1], "need": None, "skip": "FERTILIZER"})

    if liquidate:
        # E12c: harvest earlier in endgame (bank conversion)
        jobs += scan["feed"] + scan["harvest"] + scan["water"] + scan["fert"]
    else:
        jobs += scan["feed"] + scan["water"] + scan["harvest"] + scan["fert"]

    for animal, frees in (("COW", scan["free_p"]), ("SHEEP", scan["free_p"]), ("GOOSE", scan["free_c"])):
        if not frees:
            continue
        in_shed = int(shed.get(animal, 0) or 0)
        in_hands = _carried(invs, animal)
        available = in_shed + in_hands
        if available <= 0:
            continue
        if in_shed > 0 and in_hands < min(len(frees), in_shed + in_hands):
            trips = min(in_shed, max(1, len(frees) - in_hands), 4)
            for _ in range(trips):
                jobs.append({"pos": sp, "op": ["PICKUP", animal, 1], "need": None, "skip": animal})
        for pos in frees[:available]:
            jobs.append({"pos": pos, "op": ["PLACE", animal], "need": (animal, 1)})

    jobs += scan["care"] + scan["collect"]

    reserved = 0
    if not liquidate and day <= INVEST_UNTIL:
        pending = (
            int(shed.get("COW", 0) or 0)
            + int(shed.get("SHEEP", 0) or 0)
            + _carried(invs, "COW")
            + _carried(invs, "SHEEP")
        )
        want = min(COW_TARGET + SHEEP_TARGET, scan["n_animals"] + pending + 2)
        need_b = min(max(0, want - scan["n_pasture"]), 4)
        for pos in scan["empties"][:need_b]:
            jobs.append({"pos": pos, "op": ["BUILD_PASTURE"], "need": None})
            reserved += 1

    if planting:
        plant_slots = scan["empties"][reserved:]
        max_plant = 4
        planted = 0
        sim_seeds = {
            "WHEAT": int(seeds.get("WHEAT", 0) or 0),
            "MELON": int(seeds.get("MELON", 0) or 0),
            "STRAWBERRY": int(seeds.get("STRAWBERRY", 0) or 0),
        }
        sim_counts = {
            "n_wheat": scan["n_wheat"],
            "n_melon": scan["n_melon"],
            "n_straw": scan["n_straw"],
        }
        for pos in plant_slots:
            if planted >= max_plant:
                break
            fake = {
                "n_melon": sim_counts["n_melon"],
                "n_straw": sim_counts["n_straw"],
                "n_wheat": sim_counts["n_wheat"],
            }
            crop = _pick_crop(fake, sim_seeds, day, planting, straw_tgt=straw_tgt, recover=recover)
            if not crop or sim_seeds.get(crop, 0) <= 0:
                break
            jobs.append({"pos": pos, "op": ["PLANT", crop], "need": None})
            sim_seeds[crop] -= 1
            if crop == "MELON":
                sim_counts["n_melon"] += 1
            elif crop == "STRAWBERRY":
                sim_counts["n_straw"] += 1
            else:
                sim_counts["n_wheat"] += 1
            planted += 1

    jobs += scan["dig"]
    return jobs


def _produce_load(inv) -> int:
    return sum(int(_d(inv).get(item, 0) or 0) for item in DROP_PRODUCE)


def _assign(me, priv, jobs, day=0, hour=0, liquidate=False):
    farmer = tuple(_g(me, "farmer", (4, 4)) or (4, 4))
    hands = [tuple(h) for h in (_g(me, "hands", []) or [])]
    positions = [farmer] + hands
    invs = list(_g(priv, "inventories", []) or [])
    while len(invs) < len(positions):
        invs.append({})

    claimed_pos = set()
    ops = [["PASS"] for _ in positions]
    used_job = set()
    busy = [False] * len(positions)

    # E12b: deposit produce to shed so SELL can clear same day; free carry slots
    tiles = _g(me, "tiles")
    sx, sy = _shed_tile(tiles)
    thr = DROP_THRESHOLD_LIQ if liquidate else DROP_THRESHOLD
    after_h = 0 if liquidate else DROP_AFTER_HOUR
    if hour >= after_h:
        for i, pos in enumerate(positions):
            load = _produce_load(invs[i])
            if load < thr:
                continue
            busy[i] = True
            if pos in SHED:
                ops[i] = ["DROP"]
            else:
                ops[i] = _step(pos[0], pos[1], sx, sy)

    # E12c: op priority (lower = sooner). List order remains secondary.
    _PRIO = {
        "FEED": 0,
        "PICKUP": 1,
        "WATER": 2,
        "HARVEST": 3,
        "FERTILIZE": 4,
        "PLACE": 5,
        "BUILD_PASTURE": 6,
        "PLANT": 7,
        "CARE": 8,
        "COLLECT_FERTILIZER": 9,
        "DIG": 10,
    }

    for i, pos in enumerate(positions):
        if busy[i]:
            continue
        inv = _d(invs[i])
        best = None
        best_key = None
        for ji, job in enumerate(jobs):
            if ji in used_job:
                continue
            jp = job["pos"]
            if jp in claimed_pos and jp != pos:
                continue
            sk = job.get("skip")
            if sk and int(inv.get(sk, 0) or 0) > 0:
                continue
            need = job.get("need")
            if need:
                item, qty = need
                if int(inv.get(item, 0) or 0) < qty:
                    continue
            dist = _man(pos, jp)
            on = 0 if dist == 0 else 1
            op0 = job["op"][0] if job.get("op") else ""
            prio = _PRIO.get(op0, 12)
            # liquidate: prefer HARVEST slightly over WATER when both off-tile
            if liquidate and op0 == "HARVEST":
                prio = 2
            key = (on, prio, dist, ji)
            if best_key is None or key < best_key:
                best_key = key
                best = (ji, job)
        if best is None:
            # E12c anti-PASS: walk toward nearest open service job
            walk = None
            walk_key = None
            for ji, job in enumerate(jobs):
                if ji in used_job:
                    continue
                op0 = job["op"][0] if job.get("op") else ""
                if op0 not in ("HARVEST", "WATER", "FEED", "DIG", "PLANT", "BUILD_PASTURE"):
                    continue
                jp = job["pos"]
                if jp in claimed_pos and jp != pos:
                    continue
                dist = _man(pos, jp)
                prio = _PRIO.get(op0, 12)
                key = (prio, dist, ji)
                if walk_key is None or key < walk_key:
                    walk_key = key
                    walk = job
            if walk is not None:
                tx, ty = walk["pos"]
                ops[i] = _step(pos[0], pos[1], tx, ty)
            continue
        ji, job = best
        used_job.add(ji)
        claimed_pos.add(job["pos"])
        tx, ty = job["pos"]
        if pos == (tx, ty):
            ops[i] = list(job["op"])
        else:
            ops[i] = _step(pos[0], pos[1], tx, ty)
    return ops[0], ops[1:]


def _fib_cost(n_hires_done: int) -> int:
    a, b = 1, 1
    for _ in range(max(0, n_hires_done)):
        a, b = b, a + b
    return a


def _sell_chunk(item, prices, minv, opp_crops, force, shed_qty=0, day=0, town=None, shed_n=0, recover=False):
    base = SELL_CHUNK.get(item, 12)
    if force:
        return base
    town = town or {}
    inv_n = int(minv.get(item, I0) or I0)
    book = inv_n - I0  # >0 surplus (price pressure), <0 deficit (strong demand)
    glut_thr = GLUT_ABOVE.get(item)
    if glut_thr is not None and inv_n >= I0 + glut_thr:
        base = min(base, GLUT_CHUNK.get(item, max(1, base // 2)))
    if item == "MELON" and opp_crops.get("MELON", 0) >= 8:
        base = min(base, 4)
    if item == "STRAWBERRY" and opp_crops.get("STRAWBERRY", 0) >= 8:
        base = min(base, 3)
    # E8: capture melon when town book is hungry (ceiling games sold more)
    if item == "MELON" and book < -10:
        base = max(base, 10 if book < -30 else 8)
    if item == "STRAWBERRY" and book < -20:
        base = max(base, 6)

    milk_shops = int(town.get("milk_shops", 0) or 0)
    yarn = int(town.get("yarn", 0) or 0)

    # Contested milk: no/few milk shops + book surplus → meter hard
    # E6a: milk_shops>=2 → freer premium sells (right-tail lift)
    if item == "MILK":
        daily = int(town.get("MILK", 1) or 1)
        if milk_shops >= 2:
            # E8: deeper left-tail avoidance — when book hungry, clear harder
            if book < -40:
                base = max(base, 12)
            elif book < 0:
                base = max(base, 10)
            elif book < 25:
                base = max(base, 8)
            else:
                base = max(base, 6)  # still move volume under soft glut
        elif milk_shops == 0 or book >= 10:
            base = min(base, 2 if book >= 20 else 3)
        elif milk_shops == 1 and book >= 0:
            base = min(base, 4)
        # Never flood more than ~1 day of town drain when contested
        if milk_shops <= 1 and book >= 0:
            base = min(base, max(1, daily // 2))

    if item == "WOOL":
        if yarn >= 2:
            # Yarn town: freer wool clears (mirror milk H1)
            if book < 0:
                base = max(base, 8)
            elif book < 20:
                base = max(base, 6)
            else:
                base = max(base, 4)
        elif yarn == 1 and book < 0:
            base = max(base, 5)
        elif yarn == 0 and book >= 10:
            base = min(base, 2)

    px = int(prices.get(item, 0) or 0)
    soft = PRICE_FLOOR.get(item)
    hard = HARD_FLOOR.get(item, 1)
    # Dynamic soft floors: hold contested, relax when shops absorb
    if item == "MILK":
        if milk_shops == 0:
            soft = max(soft or 55, 70)  # hold longer when no milk shops
            if book >= 30:
                soft = max(soft, 90)
        elif milk_shops >= 2:
            soft = min(soft or 55, 45)  # freer: accept lower px to clear volume
            if book < -30:
                soft = min(soft, 35)
            if book < -60:
                soft = min(soft, 30)  # E8: hungry book — don't stick inventory
    if item == "WOOL" and yarn >= 2:
        soft = min(soft or 45, 35)
        if book < -20:
            soft = min(soft, 28)
    # E18am: post-land recovery — freer melon/wool to refill cash after land spend
    if recover and soft is not None:
        if item == "MELON":
            soft = min(soft, 100)
            base = max(base, 6)
        elif item == "WOOL":
            soft = min(soft, 35)
            base = max(base, 4)
    # E6g: late-game convert inventory → bank (right-tail), keep hard floors
    if day >= 20 and soft is not None and item in PRICE_FLOOR:
        soft = min(soft, max(HARD_FLOOR.get(item, 1) + 15, soft - 20))
    if day >= 24 and soft is not None and item in PRICE_FLOOR:
        soft = min(soft, HARD_FLOOR.get(item, 1) + 5)
    if soft is not None and px < soft:
        pressure = shed_n >= SHED_SOFT or shed_qty >= 12 or (shed_qty >= 8 and day >= 18)
        late = day >= 22
        # Contested milk: only drip under pressure; avoid hard-floor dumps early
        if item == "MILK" and milk_shops <= 1 and book >= 0:
            if pressure or late:
                if px >= max(hard, 40) or shed_n >= 90 or day >= 27:
                    return min(base, 2)
            return 0
        # Shop-rich towns: allow hard-floor drip earlier to keep cash turning
        if item in ("MILK", "WOOL") and (
            (item == "MILK" and milk_shops >= 2) or (item == "WOOL" and yarn >= 2)
        ):
            if px >= hard and (pressure or late or shed_qty >= 6 or day >= 16):
                return min(base, max(3, base // 2))
            return 0
        if px >= hard and (pressure or late):
            return min(base, GLUT_CHUNK.get(item, max(2, base // 3)))
        return 0
    return base


def _market(obs, me, priv, scan, day, hour, liquidate, investing, planting, player):
    money = float(_g(me, "money", 0) or 0)
    shed = _d(_g(priv, "shed", {}))
    seeds = _d(_g(priv, "seeds", {}))
    invs = list(_g(priv, "inventories", []) or [])
    market = _g(obs, "market", {}) or {}
    prices = _d(_g(market, "prices", {}))
    minv = _d(_g(market, "inventory", {}))
    unlocked = list(_g(me, "unlocked_quadrants", ["NW"]) or ["NW"])
    n_hands = len(_g(me, "hands", []) or [])
    hires_today = int(_g(me, "hires_today", 0) or 0)
    opp_crops = _opp_crops(obs, player)
    town = _town_demand(obs)
    orders = []

    flock_live = scan["n_animals"]
    flock_pending = (
        int(shed.get("COW", 0) or 0)
        + int(shed.get("SHEEP", 0) or 0)
        + int(shed.get("GOOSE", 0) or 0)
    )
    flock = flock_live + flock_pending
    # Dynamic herd caps from town portfolio
    milk_shops = int(town.get("milk_shops", 0) or 0)
    yarn = int(town.get("yarn", 0) or 0)
    # Day<9 shops are still unlocking — don't starve cow ramp on day-0 zero shops.
    if milk_shops >= 2:
        cow_tgt = COW_TARGET
    elif milk_shops == 1:
        cow_tgt = 5
    elif day >= 9:
        cow_tgt = COW_TARGET_WEAK  # contested season confirmed
    else:
        cow_tgt = 5  # provisional mid until shop signal
    sheep_tgt = SHEEP_TARGET_YARN if yarn >= 2 else (SHEEP_TARGET_YARN1 if yarn >= 1 else SHEEP_TARGET)
    feed_heads = max(flock, (cow_tgt + sheep_tgt) // 2 if investing else flock)
    carry_w = _carried(invs, "WHEAT")
    shed_w = int(shed.get("WHEAT", 0) or 0)
    shed_n_pre = sum(int(v or 0) for v in shed.values())
    # E8: stable feed float — pressure-shrink caused sell→rebuy thrash on floor seeds.
    if day >= 29:
        wheat_reserve = 0
    elif liquidate:
        wheat_reserve = feed_heads * 2
    else:
        wheat_reserve = feed_heads * FEED_RESERVE_STABLE

    def spend(c):
        nonlocal money
        if money >= c:
            money -= c
            return True
        return False

    shed_n = sum(int(v or 0) for v in shed.values())
    force = day >= 29 or (liquidate and day >= 28) or shed_n >= SHED_PRESSURE
    recover_sell = _post_land_recovery(day, unlocked)

    def sell(item):
        nonlocal money
        n = int(shed.get(item, 0) or 0)
        if n <= 0:
            return
        if item == "WHEAT":
            keep = max(0, wheat_reserve - carry_w)
            n = max(0, n - keep)
            if n <= 0:
                return
            # E8 anti-churn: never sell wheat while investing unless hard shed pressure.
            # Floor games sold+bought 2–3k units (0.75 haircut) and starved capital.
            if not force and day < WHEAT_SELL_FROM_DAY and shed_n < SHED_PRESSURE:
                return
        chunk = _sell_chunk(
            item, prices, minv, opp_crops, force,
            shed_qty=int(shed.get(item, 0) or 0), day=day,
            town=town, shed_n=shed_n, recover=recover_sell,
        )
        if chunk <= 0:
            return
        take = n if (force and item in ("WHEAT", "EGG", "CARROT", "TOMATO", "FERTILIZER")) else min(n, chunk)
        if force and day >= 29:
            take = n
        # Prefer clearing premiums; under pressure take fuller wheat dumps
        if item == "WHEAT" and shed_n >= SHED_SOFT:
            take = min(n, max(chunk, 12))
        if take > 0:
            orders.append(["SELL", item, take])
            money += 0.75 * int(prices.get(item, 0) or 0) * take

    for item in ("MILK", "WOOL", "MELON", "STRAWBERRY", "EGG", "CARROT", "TOMATO", "FERTILIZER", "WHEAT"):
        if len(orders) >= MAX_MARKET:
            break
        sell(item)
    orders[:] = orders[:MAX_MARKET]

    target_hands = HIRE_DAY0 if day == 0 else TARGET_HANDS
    hire_budget = 0
    tmp = hires_today
    for i in range(max(0, target_hands - n_hands)):
        hire_budget += _fib_cost(tmp + i)
    cash_floor = hire_budget + (400 if investing else 0)

    # E12b: also hire in liquidate when harvest / shed sell work remains (hands vanish EOD)
    sellable_shed = sum(int(shed.get(it, 0) or 0) for it in DROP_PRODUCE)
    liq_work = liquidate and (
        len(scan["harvest"]) > 0 or sellable_shed >= 5 or day >= 28
    )
    if hour <= 6 and (not liquidate or liq_work):
        made = 0
        while n_hands + made < target_hands and len(orders) < MAX_MARKET:
            cost = _fib_cost(hires_today + made)
            if money < cost + (0 if day == 0 and made < HIRE_DAY0 else 50):
                break
            orders.append(["HIRE"])
            spend(cost)
            made += 1

    need = max(wheat_reserve, flock * FEED_MIN_DAYS, 12 if day <= 1 else 0)
    gap = need - shed_w - carry_w
    wp = int(prices.get("WHEAT", 25) or 25)
    if gap > 0 and wp <= MAX_WHEAT_PRICE and len(orders) < MAX_MARKET and not liquidate:
        affordable = int(max(0, money - cash_floor) // max(1, wp))
        # E8: cap buy size; skip if shed already near reserve (avoid thrash refill)
        if shed_w + carry_w >= wheat_reserve and day > 1:
            n = 0
        else:
            n = min(gap, WHEAT_BUY_CAP, affordable)
        if n > 0 and spend(n * wp):
            orders.append(["BUY_PRODUCT", "WHEAT", n])
            shed_w += n

    # Land: 1st ~day 6 with herd_gate; 2nd only when herd+cash+labor ready (not day-forced)
    bought = max(0, len(unlocked) - 1)
    herd_gate = scan["n_animals"] + flock_pending
    labor_load = len(scan["feed"]) + len(scan["water"]) + len(scan["harvest"])
    labor_ok = labor_load <= max(1, n_hands + 1) * LABOR_HEADROOM + 4
    if investing and bought < LAND_TARGET and bought < len(LAND_COSTS) and len(orders) < MAX_MARKET:
        cost = LAND_COSTS[bought]
        # E14 single knob: packed start-quad → cheaper first-land buffer
        if bought == 0:
            owned_n = int(scan.get("owned") or 0)
            empties_n = len(scan.get("empties") or [])
            occ = (1.0 - empties_n / owned_n) if owned_n > 0 else 0.0
            if day >= PACKED_LAND_FROM_DAY and occ >= PACKED_OCC_MIN:
                buf = PACKED_LAND_BUFFER
            else:
                buf = LAND_BUFFER
        else:
            buf = LAND2_BUFFER
        if bought == 0:
            ready = day >= LAND_FROM_DAY and herd_gate >= 3
        else:
            # 2nd land: wait for real herd + feed float + cash, typically day 8+
            ready = (
                day >= LAND2_FROM_DAY
                and herd_gate >= 6
                and (shed_w + carry_w) >= feed_heads * FEED_MIN_DAYS
                and money >= cost + buf + cash_floor + 800
            )
        owned_ne = int(scan.get("owned") or 0)
        empties_ne = len(scan.get("empties") or [])
        occ_e = (1.0 - empties_ne / owned_ne) if owned_ne > 0 else 0.0
        # E18cq: proj11 + contested early emerg
        land_need_normal = cost + buf + cash_floor
        OVERNIGHT_EST = 700
        global _OPP_M_AT_D8
        farms_all = _g(obs, "farms", []) or []
        opp_m = 0.0
        try:
            opp_farm = farms_all[1 - int(player)]
            opp_m = float(_g(opp_farm, "money", 0) or 0)
        except Exception:
            opp_m = 0.0
        if day == 8 and _OPP_M_AT_D8 is None:
            _OPP_M_AT_D8 = opp_m  # first day-8 observation
        contested = (
            _OPP_M_AT_D8 is not None and opp_m >= float(_OPP_M_AT_D8) + 400
        )
        if contested and day >= 9:
            # live H2H: don't wait for d10 evening — shop fight starves overnight fill
            will_miss = money < land_need_normal
        elif day < 10:
            projected = money + OVERNIGHT_EST * max(0, 11 - day)
            will_miss = projected < land_need_normal
        elif day == 10:
            if hour < 18:
                will_miss = False
            else:
                projected = money + OVERNIGHT_EST
                will_miss = projected < land_need_normal
        else:
            will_miss = money < land_need_normal
        emerg = (
            bought == 0
            and occ_e >= 0.95
            and day >= 8
            and herd_gate >= 3
            and money < land_need_normal
            and money >= cost + hire_budget + 0
            and will_miss
        )
        land_need = (cost + hire_budget + 0) if emerg else land_need_normal
        if ready and money >= land_need and spend(cost):
            if emerg:
                global _EMERG_LAND
                _EMERG_LAND = True
            orders.append(["BUY_LAND"])

    if investing and len(orders) < MAX_MARKET:
        feed_ok = (shed_w + carry_w) >= max(8, flock * FEED_MIN_DAYS)
        # E6c: yarn towns need slightly looser float so sheep can scale modestly
        float_days = 3 if yarn >= 2 else max(4, FEED_MIN_DAYS)
        float_ok = (shed_w + carry_w) >= feed_heads * float_days
        # Herd ROI: proven feed+labor headroom; tilt cows/sheep by town demand
        # E8: no more animals while shed soft-clogged (floor 8114 hit shed=100)
        shed_free = shed_n < SHED_SOFT
        # E9b1: drop labor_ok from animal buys (keep shed/feed gates)
        # E18am soft recovery: after land, animals only if cash-rich (not hard freeze)
        recover_m = _post_land_recovery(day, unlocked)
        just_land = any(isinstance(o, list) and o and o[0] == "BUY_LAND" for o in orders)
        ani_floor = cash_floor + (1200 if (recover_m or just_land) else 500)
        if feed_ok and float_ok and shed_free and money > ani_floor:
            # Cows first (8-day ramp). Sheep-first ONLY when yarn heavy & milk thin
            # and cows already at weak floor.
            # E8: count carried animals — missing carry caused overshoot to 8 cows.
            cows_have = (
                scan["n_cow"]
                + int(shed.get("COW", 0) or 0)
                + _carried(invs, "COW")
            )
            sheep_have = (
                scan["n_sheep"]
                + int(shed.get("SHEEP", 0) or 0)
                + _carried(invs, "SHEEP")
            )
            order = (
                ("COW", cow_tgt, cows_have),
                ("SHEEP", sheep_tgt, sheep_have),
            )
            # E6c: yarn-heavy → sheep after weak cow floor (even if 1 milk shop)
            if yarn >= 2 and cows_have >= COW_TARGET_WEAK and (
                milk_shops == 0 or sheep_have < sheep_tgt
            ):
                if milk_shops == 0 or cows_have >= min(cow_tgt, 5):
                    order = (order[1], order[0])
            for animal, tgt, have in order:
                if have >= tgt:
                    continue
                # Contested milk: do not expand cows further into surplus book
                if animal == "COW" and milk_shops <= 1:
                    book_m = int(minv.get("MILK", I0) or I0) - I0
                    # E8: contested or thin milk — freeze expansion earlier
                    if milk_shops == 0 and book_m >= 5 and have >= COW_TARGET_WEAK:
                        continue
                    if milk_shops == 1 and book_m >= 20 and have >= 5:
                        continue
                cost = ANIMAL_COST[animal]
                room = int((money - cash_floor - 300) // cost)
                n = min(ANIMAL_BATCH, tgt - have, room)
                if n > 0 and spend(n * cost):
                    orders.append(["BUY_ANIMAL", animal, n])
                    flock += n
                    break

    feed_covered = (shed_w + carry_w) >= max(8, feed_heads * FEED_MIN_DAYS)
    if planting and feed_covered and len(orders) < MAX_MARKET and money > cash_floor + 150:
        have_w = int(seeds.get("WHEAT", 0) or 0)
        if have_w < SEED_STOCK_WHEAT and day <= WHEAT_PLANT_UNTIL:
            n = min(
                SEED_STOCK_WHEAT - have_w,
                int((money - cash_floor - 100) // SEED_COST["WHEAT"]),
                MAX_MARKET - len(orders),
            )
            if n > 0 and spend(n * SEED_COST["WHEAT"]):
                orders.append(["BUY_SEED", "WHEAT", n])

        have_m = int(seeds.get("MELON", 0) or 0)
        melon_want = SEED_STOCK_MELON if day <= 8 else max(0, MELON_TARGET - scan["n_melon"])
        if (
            day <= MELON_PLANT_UNTIL
            and have_m < melon_want
            and money > cash_floor + 400
            and len(orders) < MAX_MARKET
            and (scan["n_animals"] >= 2 or day >= 2)
        ):
            room = int((money - cash_floor - 300) // SEED_COST["MELON"])
            n = min(melon_want - have_m, 4, room, MAX_MARKET - len(orders))
            if n > 0 and spend(n * SEED_COST["MELON"]):
                orders.append(["BUY_SEED", "MELON", n])

        have_s = int(seeds.get("STRAWBERRY", 0) or 0)
        # E15e: stock/target 10 when land open + feed ok
        post_land = len(unlocked) > 1
        feed_ok_s = (shed_w + carry_w) >= max(8, flock * FEED_MIN_DAYS)
        densify = post_land and feed_ok_s
        straw_cap = 10 if densify else SEED_STOCK_STRAW
        straw_tgt_m = 10 if densify else STRAW_TARGET
        straw_want = straw_cap if day <= 10 else max(0, straw_tgt_m - scan["n_straw"])
        if (
            day <= STRAW_PLANT_UNTIL
            and have_s < straw_want
            and money > cash_floor + 600
            and len(orders) < MAX_MARKET
            and (scan["n_melon"] + have_m >= 4 or day >= 5)
        ):
            room = int((money - cash_floor - 400) // SEED_COST["STRAWBERRY"])
            n = min(straw_want - have_s, 3, room, MAX_MARKET - len(orders))
            if n > 0 and spend(n * SEED_COST["STRAWBERRY"]):
                orders.append(["BUY_SEED", "STRAWBERRY", n])

    if (
        investing
        and planting
        and day <= MELON_PLANT_UNTIL + 2
        and scan["n_melon"] + int(seeds.get("MELON", 0) or 0) > 0
        and len(orders) < MAX_MARKET
    ):
        have_f = int(shed.get("FERTILIZER", 0) or 0) + _carried(invs, "FERTILIZER")
        if have_f < FERT_STOCK and money > cash_floor + 300:
            fp = int(prices.get("FERTILIZER", 100) or 100)
            if fp <= 120:
                n = min(FERT_STOCK - have_f, 3, int((money - cash_floor - 200) // max(1, fp)))
                if n > 0 and spend(n * fp):
                    orders.append(["BUY_PRODUCT", "FERTILIZER", n])

    return orders[:MAX_MARKET]


def agent(obs, config=None):
    try:
        return _agent(obs)
    except Exception:
        return dict(PASS)


def _agent(obs):
    player = int(_g(obs, "player", 0) or 0)
    farms = _g(obs, "farms", []) or []
    if not farms or player >= len(farms):
        return dict(PASS)

    me = farms[player]
    priv = _g(obs, "private", {}) or {}
    day = int(_g(obs, "day", 0) or 0)
    hour = int(_g(obs, "hour", 0) or 0)
    _ = _turn(obs)

    liquidate = day >= LIQUIDATE_FROM
    investing = day <= INVEST_UNTIL and not liquidate
    planting = day <= WHEAT_PLANT_UNTIL and not liquidate

    scan = _scan(me, day, liquidate)
    jobs = _jobs(scan, me, priv, day, liquidate, planting)
    market = _market(obs, me, priv, scan, day, hour, liquidate, investing, planting, player)
    farmer_op, hand_ops = _assign(me, priv, jobs, day=day, hour=hour, liquidate=liquidate)

    n_hands = len(_g(me, "hands", []) or [])
    if len(hand_ops) < n_hands:
        hand_ops += [["PASS"]] * (n_hands - len(hand_ops))
    else:
        hand_ops = hand_ops[:n_hands]

    return {"farmer": farmer_op, "hands": hand_ops, "market": market}
