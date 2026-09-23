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

SAFE_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}


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

    def units_this_turn(self, product, held, inventory, drain, turn):
        turns_left = max(1, HORIZON - turn)
        if held <= 0:
            return 0
        if turns_left <= 4:
            return int(held)
        try:
            plan, tps = self._solve(product, int(held), float(inventory),
                                    float(drain), int(turns_left))
        except Exception:
            return int(math.ceil(held / float(turns_left)))
        if not plan:
            return int(math.ceil(held / float(turns_left)))
        return int(min(held, max(1, math.ceil(plan[0] / max(1.0, tps)))))

    def _solve(self, product, total_units, inv0, drain, turns_left):
        key = (product, int(total_units), int(inv0 // 25), int(turns_left // 8))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        stages = max(1, min(self.STAGES, turns_left))
        tps = turns_left / float(stages)
        bucket = max(1, int(math.ceil(total_units / float(self.BUCKETS))))
        nq = int(math.ceil(total_units / float(bucket)))
        inv_lo = max(1.0, inv0 - drain * tps * max(0, stages - 1))
        span = int(inv0 + total_units - inv_lo) + total_units + 2
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
    __slots__ = ("phase", "crop_mix", "animal_targets", "buy_land",
                 "target_hands", "price_hint", "capacity", "reserve",
                 "shadow_td", "action_value", "wheat_reserve")

    def __init__(self):
        self.phase = "BOOTSTRAP"
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

    Turns 0-72  BOOTSTRAP  : 100% carrot. Fastest legal compounding on 25 tiles.
    Turns 72-240 EXPAND    : buy land, stand up geese, plant melon that still matures.
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

    def phase_of(self, turn):
        if turn >= LIQUIDATION_TURN:
            return "LIQUIDATE"
        if turn >= 500:
            return "HARVEST"
        if turn >= 240:
            return "COMPOUND"
        if turn >= 72:
            return "EXPAND"
        return "BOOTSTRAP"

    def maybe_replan(self, st):
        if st.turn - self._last < self.REPLAN_EVERY and self.plan.crop_mix:
            self.plan.phase = self.phase_of(st.turn)
            return self.plan
        self._last = st.turn
        try:
            self.plan = self._replan(st)
        except Exception:
            if not self.plan.crop_mix:
                self.plan.crop_mix = {"CARROT": max(1, st.usable_tiles)}
        return self.plan

    def _eligible(self, st, phase, days_left, shops_w):
        """Which products may receive new tiles this phase."""
        allow = set()
        if phase == "LIQUIDATE":
            return allow
        if phase == "BOOTSTRAP":
            if days_left >= 4:
                allow.add("CARROT")
            return allow
        if phase == "HARVEST":
            if days_left >= 4:
                allow.add("CARROT")
            if days_left >= 5:
                allow.add("WHEAT")
            return allow
        # EXPAND / COMPOUND
        if days_left >= 4:
            allow.add("CARROT")
        if days_left >= 5:
            allow.add("WHEAT")
        if days_left >= 12:
            allow.add("MELON")
        if days_left >= 8:
            allow.add("EGG")
        if phase == "COMPOUND" and days_left >= 14:
            if shops_w.get("MILK", 0) >= 2:
                allow.add("MILK")
            if shops_w.get("WOOL", 0) >= 2:
                allow.add("WOOL")
            if shops_w.get("TOMATO", 0) >= 3 and days_left >= 13:
                allow.add("TOMATO")
            if shops_w.get("STRAWBERRY", 0) >= 3 and days_left >= 18:
                allow.add("STRAWBERRY")
        return allow

    def _demand(self, st, mu, eligible, turns_to_gate):
        total = 0.0
        units = {}
        for prod in eligible:
            cost = TDPU.get(prod, 2.0)
            if self.el.collapsed.get(prod) and prod not in ("WHEAT", "EGG"):
                cost *= 1.0 + 2.0 * max(0.0, self.el.collapse_depth.get(prod, 0.0))
            inv = st.inventory.get(prod, MARKET_I0)
            floor = max(1.0, mu * cost)
            if Econ.price(prod, inv) < floor:
                units[prod] = 0
                continue
            headroom = Econ.units_until(prod, inv, floor)
            regen = self.el.drain_rate.get(prod, 0.0) * turns_to_gate
            opp = st.opp_pipeline.get(prod, 0)
            X = max(0.0, headroom + regen - opp)
            units[prod] = X
            total += X * cost
        return total, units

    def _replan(self, st):
        p = Plan()
        p.phase = self.phase_of(st.turn)
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
            p.target_hands = 6
            p.wheat_reserve = 0
            p.buy_land = False
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

        for prod in PRODUCTS:
            cost = TDPU.get(prod)
            p.reserve[prod] = max(1.0, mu * cost) if cost else 1.0
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
                        p.animal_targets[animal] = tiles

        # Feed wheat is not optional once animals exist or are planned.
        geese = p.animal_targets.get("GOOSE", 0)
        cows = p.animal_targets.get("COW", 0)
        sheep = p.animal_targets.get("SHEEP", 0)
        herd = geese + cows + sheep + st.n_animals
        # One wheat tile yields 4 units / 5 days = 0.8 wheat/day; one animal
        # eats 1 wheat/day. Size the wheat block to the herd, not the leftover.
        feed_tiles = int(math.ceil(herd * 1.25)) if herd else 0
        if feed_tiles and days_left >= 5:
            p.crop_mix["WHEAT"] = max(p.crop_mix.get("WHEAT", 0), feed_tiles)

        # Collapse pivot: drop the crashed crop from new plantings.
        for crop, prod in (("MELON", "MELON"), ("STRAWBERRY", "STRAWBERRY"),
                           ("TOMATO", "TOMATO"), ("CARROT", "CARROT")):
            if self.el.collapsed.get(prod) and crop in p.crop_mix:
                if self.el.collapse_depth.get(prod, 0.0) > 0.25:
                    p.crop_mix.pop(crop, None)

        if not p.crop_mix and not p.animal_targets and days_left >= 4:
            p.crop_mix["CARROT"] = max(1, st.usable_tiles // 2)

        # Never over-allocate tiles.
        used = sum(p.crop_mix.values()) + sum(p.animal_targets.values())
        if used > st.usable_tiles > 0:
            scale = st.usable_tiles / float(used)
            p.crop_mix = {k: max(0, int(v * scale)) for k, v in p.crop_mix.items()}
            p.animal_targets = {k: max(0, int(v * scale)) for k, v in p.animal_targets.items()}

        p.action_value = max(2.0, mu / 4.0)
        p.wheat_reserve = max(herd * 2, st.n_animals * 3)

        next_cost = st.next_land_cost
        if (next_cost is not None and days_left >= 6 and p.phase in ("EXPAND", "COMPOUND")
                and st.money > next_cost * 1.20):
            marginal = mu * 25.0 * min(days_left, 16) * 0.35
            p.buy_land = marginal > next_cost

        # Hands: fib cost vs. a worker-day. Always enough to service the herd.
        worker_day = 0.50 * p.action_value * TURNS_PER_DAY
        need = int(math.ceil((st.usable_tiles + st.n_animals * 3.2) / 20.0))
        target, cum, n = 0, 0, 0
        cash = max(0.0, st.money * 0.28)
        while target < 18:
            c = fib(n)
            if c > worker_day and target >= max(4, need):
                break
            if cum + c > cash and target >= max(4, need):
                break
            cum += c
            target += 1
            n += 1
        p.target_hands = max(4, min(18, max(target, need)))
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
        self.usable_tiles = self._count_usable()
        self.next_land_cost = self._next_land_cost()
        self.n_animals = 0
        self.animals_alive = {"GOOSE": 0, "COW": 0, "SHEEP": 0}
        self.empty_structs = []
        self.opp_pipeline = {}
        self.risk_lambda = 0.0
        self._scan_board()
        self._opp_pipeline()

    def _count_usable(self):
        n = 0
        for row in self.tiles:
            for t in row:
                if t != "LOCKED":
                    n += 1
        return n if n else QUADRANT * QUADRANT

    def _next_land_cost(self):
        bought = max(0, len(self.quadrants) - 1)
        if bought >= len(LAND_PRICES):
            return None
        return LAND_PRICES[bought]

    def _scan_board(self):
        for y, row in enumerate(self.tiles):
            for x, tile in enumerate(row):
                if not isinstance(tile, dict):
                    continue
                if "animal" in tile:
                    a = tile.get("animal")
                    if a in self.animals_alive:
                        self.animals_alive[a] += 1
                        self.n_animals += 1
                elif tile.get("kind") in ("COOP", "PASTURE"):
                    self.empty_structs.append(((x, y), tile.get("kind")))

    def _opp_pipeline(self):
        """Units the opponent is about to drop into the shared book."""
        pipe = {p: 0.0 for p in PRODUCTS}
        for row in self.opp_tiles:
            for t in row:
                if not isinstance(t, dict):
                    continue
                if t.get("kind") == "PLANT":
                    crop = t.get("crop")
                    spec = CROPS.get(crop)
                    if not spec:
                        continue
                    age = self.day - int(t.get("planted_day", self.day))
                    if age >= spec["first"] - 2:
                        pipe[crop] = pipe.get(crop, 0.0) + Econ.planned_units(crop)
                elif t.get("animal") in ANIMALS:
                    a = ANIMALS[t["animal"]]
                    left = max(0, DAYS - self.day - a["first"])
                    cycles = left // max(1, a["interval"])
                    pipe[a["product"]] = pipe.get(a["product"], 0.0) + cycles * 1.5
        self.opp_pipeline = pipe

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

    def compute_risk(self):
        if self.turn < 400:
            self.risk_lambda = 0.0
            return
        mine = self.money
        for p in PRODUCTS:
            mine += self.shed.get(p, 0) * Econ.price(p, self.inventory.get(p, MARKET_I0))
        edge = mine - self.opp_money
        self.risk_lambda = max(-0.6, min(0.6, edge / 25000.0))


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
                add({"pos": pos, "op": ["DIG"], "kind": "DIG",
                     "value": 0.8 * plan.action_value})
                continue

            if kind == "PLANT":
                crop = tile.get("crop")
                spec = CROPS.get(crop)
                if spec is None:
                    continue
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
                    add({"pos": pos, "op": ["CARE"], "kind": "CARE",
                         "value": price * 0.95})
                if units_now > 0:
                    add({"pos": pos, "op": ["HARVEST"], "kind": "HARVEST",
                         "value": units_now * price})
                if tile.get("fertilizer_available"):
                    add({"pos": pos, "op": ["COLLECT_FERTILIZER"], "kind": "COLLECT",
                         "value": 0.85 * plan.price_hint.get("FERTILIZER", 100)})
                continue

    # Planting. Never issue more PLANT C than seeds[C] — the engine voids all.
    # Never plant on hour 23: consecutive_unwatered starts at 1, EOD makes a weed.
    want = dict(plan.crop_mix)
    planted = {c: 0 for c in CROPS}
    if st.hour < 23 and days_left >= 3:
        for pos in empties:
            crop = None
            for c in sorted(want, key=lambda k: -plan.price_hint.get(k, 0)):
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

    # Structures for planned animals.
    need_coops = max(0, plan.animal_targets.get("GOOSE", 0) - st.animals_alive["GOOSE"])
    need_past = max(0, (plan.animal_targets.get("COW", 0) + plan.animal_targets.get("SHEEP", 0)
                        - st.animals_alive["COW"] - st.animals_alive["SHEEP"]))
    have_c = sum(1 for _, k in st.empty_structs if k == "COOP")
    have_p = sum(1 for _, k in st.empty_structs if k == "PASTURE")
    plant_pos = {t["pos"] for t in tasks if t["kind"] == "PLANT"}
    free = [p for p in empties if p not in plant_pos]
    bi = 0
    for _ in range(min(max(0, need_coops - have_c), len(free))):
        add({"pos": free[bi], "op": ["BUILD_COOP"], "kind": "BUILD",
             "value": 0.6 * plan.price_hint.get("EGG", 50) * max(1, days_left - 4)})
        bi += 1
    for _ in range(min(max(0, need_past - have_p), max(0, len(free) - bi))):
        add({"pos": free[bi], "op": ["BUILD_PASTURE"], "kind": "BUILD",
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
        self.calib.observe(st.farmer)
        self.el.observe(st.inventory, st.prices, self.last_sales, st.shops)
        st.compute_risk()
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
                          if k in PRODUCTS or k in ANIMALS)
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

        pending_animal = next((a for a in ("GOOSE", "COW", "SHEEP") if st.shed.get(a, 0) > 0), None)
        if pending_animal and empty_structs and free_idx:
            want = ANIMAL_STRUCTURE[pending_animal]
            if any(k == want for _, k in empty_structs):
                i = free_idx[0]
                wpos = workers[i]
                dst, _ = self._nearest(wpos, shed_tiles)
                actions[i] = self._goto_or(wpos, dst, ["PICKUP", pending_animal, 1])
                free_idx = free_idx[1:]

        if (st.shed.get("FERTILIZER", 0) > 0 and free_idx and st.hour <= 10
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
                n = self.gate.units_this_turn(prod, held, inv, drain, st.turn)
            else:
                floor = plan.reserve.get(prod, 1.0)
                # Shared book + binary win: taking premium capacity before the
                # opponent is itself a payoff, so shade the floor slightly.
                if st.opp_pipeline.get(prod, 0) > 0 and MARKET_PARAMS[prod]["base"] >= 100:
                    floor *= 0.88
                if st.risk_lambda > 0.25 and MARKET_PARAMS[prod]["base"] >= 100:
                    floor *= 1.05   # ahead: do not dump premium into the floor
                if st.risk_lambda < -0.25 and MARKET_PARAMS[prod]["base"] >= 100:
                    floor *= 0.80   # behind: monetise
                sellable = Econ.units_until(prod, inv, max(1.0, floor))
                turns_to_gate = max(1, LIQUIDATION_TURN - st.turn)
                rate = max(drain, held / float(turns_to_gate), 1.0)
                n = int(min(held, sellable, math.ceil(rate * 2.0)))
                if st.shed_total > SHED_CAPACITY * 0.82:
                    n = max(n, min(held, 8))
            if n > 0:
                orders.append(["SELL", prod, int(n)])
        orders.sort(key=lambda o: -Econ.price(o[1], st.inventory.get(o[1], MARKET_I0)) * o[2])

        if self.gate.armed:
            return orders[:MAX_MARKET_ORDERS]

        budget = float(st.money)
        for o in orders:
            budget += Econ.marginal_revenue(o[1], st.inventory.get(o[1], MARKET_I0), o[2])

        buys = []

        # Seeds for the planned mix (planted NEXT turn — market is after farm).
        for crop, want in sorted(plan.crop_mix.items(),
                                 key=lambda kv: -plan.price_hint.get(kv[0], 0)):
            spec = CROPS[crop]
            need_days = 11 if crop == "MELON" else spec["max_day"] + 1
            if want <= 0 or need_days > days_left:
                continue
            have = int(st.seeds.get(crop, 0) or 0)
            need = max(0, min(int(want), st.usable_tiles) - have)
            if need <= 0:
                continue
            cost = SEED_COST[crop]
            afford = int(min(need, budget // cost)) if cost else 0
            if afford > 0:
                buys.append(["BUY_SEED", crop, afford])
                budget -= afford * cost

        # Wheat for feed when the field cannot cover the herd.
        short = reserve_wheat - st.wheat_held()
        if short > 0 and herd > 0:
            price = Econ.price("WHEAT", st.inventory.get("WHEAT", MARKET_I0))
            afford = int(min(short, budget // max(1.0, price), 20))
            if afford > 0:
                buys.append(["BUY_PRODUCT", "WHEAT", afford])
                budget -= afford * price

        if plan.buy_land and st.next_land_cost and budget > st.next_land_cost:
            buys.append(["BUY_LAND"])
            budget -= st.next_land_cost

        for animal in ("GOOSE", "COW", "SHEEP"):
            target = plan.animal_targets.get(animal, 0)
            alive = st.animals_alive.get(animal, 0)
            in_shed = int(st.shed.get(animal, 0) or 0)
            need = target - alive - in_shed
            cost = ANIMAL_COST[animal]
            if need > 0 and budget > cost * 1.4 and days_left > ANIMALS[animal]["first"] + 2:
                n = 1
                buys.append(["BUY_ANIMAL", animal, n])
                budget -= cost

        # Hire at the top of the day so the shift is almost a full 24 turns.
        if st.hour <= 3:
            to_hire = max(0, plan.target_hands - st.hires_today)
            n = st.hires_today
            for _ in range(min(to_hire, 8)):
                c = fib(n)
                if budget < c:
                    break
                buys.append(["HIRE"])
                budget -= c
                n += 1

        return (orders + buys)[:MAX_MARKET_ORDERS]


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
