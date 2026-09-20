"""Kaggriculture — finite-horizon MDP agent (self-contained submission entrypoint).

The Kaggle evaluator exec()s the archive-root ``main.py`` and calls ``agent(obs)``.
This module is deliberately dependency-free (stdlib only) and single-file: the
competition contract lists import-path failure on ``/kaggle_simulations/agent/``
as a top cause of ``Error`` submissions, and a single file has no import surface.

Architecture (see docs/ARCHITECTURE.md):
  Econ                      exact analytic price/yield model, derived from the rules
  BayesianElasticityFilter  Normal-Gamma posterior over realised price impact
  MarketPlanner             reservation-price sell scheduler (MR equalisation)
  LiquidationGateway        backward-induction dump schedule, hard-armed at turn 650
  MPCRevenueEngine          rolling-horizon portfolio choice over crops/animals
  LaborAssigner             Hungarian linear assignment over workers x tasks
  KaggricultureAgent        orchestration + turn budget guard
"""

from __future__ import annotations

import math
import time

# --------------------------------------------------------------------------
# Horizon
# --------------------------------------------------------------------------
TURNS_PER_DAY = 24
DAYS = 30
HORIZON = TURNS_PER_DAY * DAYS          # 720
LIQUIDATION_TURN = 650                  # hard, un-bypassable gateway
BOARD = 10
QUADRANT = 5
SHED_CAPACITY = 100
MAX_MARKET_ORDERS = 10
START_MONEY = 3000
TURN_BUDGET_S = 0.55                    # actTimeout is 1.0s; leave hard margin
# Tiles one worker can keep serviced per day. A tile needs roughly a watering
# plus an amortised share of planting, harvesting and carrying, and the worker
# has to walk between them, so ~1.5 of its 24 actions go to each tile.
ACTIONS_PER_TILE_DAY = 16


# --------------------------------------------------------------------------
# Exact market model (Price Function table, verified on all 9 resources x 2 sides)
# --------------------------------------------------------------------------
def _f_linear(x, T):  return x
def _f_sq(x, T):      return x * x
def _f_sqrt(x, T):    return math.sqrt(x)
def _f_log(x, T):     return math.log1p(x)
def _f_log10(x, T):   return math.log10(1.0 + x)
def _f_hinge(x, T):
    u = x / float(T)
    return u + 8.0 * (max(0.0, u - 1.0) ** 2)

_SHAPES = {
    "linear": _f_linear, "sq": _f_sq, "sqrt": _f_sqrt,
    "log": _f_log, "log10": _f_log10, "hinge": _f_hinge,
}

# resource -> (base, I0, T, below_func, below_target, above_func, above_target)
MARKET_PARAMS = {
    "WHEAT":      (25,  10000, 400, "sqrt",  0.80, "log",    0.20),
    "CARROT":     (35,  10000, 450, "hinge", 1.00, "sqrt",   0.70),
    "TOMATO":     (60,  10000, 200, "hinge", 0.40, "sqrt",   0.60),
    "STRAWBERRY": (120, 10000, 100, "sqrt",  0.70, "linear", 1.60),
    "MELON":      (250, 10000, 300, "log",   0.20, "sq",     3.60),
    "EGG":        (50,  10000, 332, "hinge", 0.40, "log",    0.20),
    "MILK":       (160, 10000, 122, "sqrt",  0.60, "linear", 1.60),
    "WOOL":       (200, 10000, 105, "log",   0.20, "sq",     3.20),
    "FERTILIZER": (100, 10000, 200, "linear", 0.40, "linear", 0.40),
}

# Fixed purchase prices (not market-driven)
SEED_COST = {"WHEAT": 10, "CARROT": 20, "TOMATO": 50, "STRAWBERRY": 100, "MELON": 80}
ANIMAL_COST = {"GOOSE": 300, "COW": 400, "SHEEP": 500}
ANIMAL_PRODUCT = {"GOOSE": "EGG", "COW": "MILK", "SHEEP": "WOOL"}
ANIMAL_STRUCTURE = {"GOOSE": "COOP", "COW": "PASTURE", "SHEEP": "PASTURE"}
# animal -> (first_yield_day, production_interval_days, max_held)
ANIMAL_SPEC = {"GOOSE": (4, 1, 4), "COW": (8, 2, 6), "SHEEP": (6, 3, 6)}
LAND_COSTS = (1000, 2000, 4000)

# crop -> (seed, first_yield_day, max_yield_day, ongoing, schedule, cap_plain, cap_fert)
CROP_SPEC = {
    "WHEAT":      (10, 2,  4,  False, None,               4, 6),
    "CARROT":     (20, 2,  3,  False, None,               3, 4),
    "TOMATO":     (50, 8,  11, True,  (8, 9, 10, 11),     4, 8),
    "STRAWBERRY": (100, 10, 16, True, (10, 12, 14, 16),   4, 8),
    "MELON":      (80, 10, 10, False, None,               6, 6),
}
# Melon's documented bonus window opens at age 6 (not ceil(max_yield_day/2)).
CROP_BONUS_START = {"WHEAT": 2, "CARROT": 2, "MELON": 6}

PRODUCTS = tuple(MARKET_PARAMS.keys())
SELLABLE = tuple(p for p in PRODUCTS)


class Econ:
    """Closed-form price / yield model. All figures derived from the rule tables."""

    @staticmethod
    def price(resource, inventory):
        """Analytic spot price at a given market inventory (floored at $1)."""
        p = MARKET_PARAMS.get(resource)
        if p is None:
            return 1.0
        base, i0, T, bf, bt, af, at = p
        x = abs(inventory - i0)
        if inventory < i0:
            f, target, sign = _SHAPES[bf], bt, 1.0
        else:
            f, target, sign = _SHAPES[af], at, -1.0
        fT = f(float(T), T)
        if fT <= 0:
            return float(base)
        amp = target * base / fT
        val = base + sign * amp * f(float(x), T)
        return max(1.0, val)

    @staticmethod
    def marginal_revenue(resource, inventory, units):
        """Revenue from selling `units` now. Sell quotes use pre-trade inventory,
        one unit at a time, so revenue is the sum of the unit-by-unit quotes."""
        if units <= 0:
            return 0.0
        total = 0.0
        for j in range(int(units)):
            total += round(Econ.price(resource, inventory + j))
        return total

    @staticmethod
    def units_until_price_floor(resource, inventory, floor_price):
        """How many units can be sold before the marginal quote drops below
        `floor_price`. Bisection on the monotone decreasing above-curve."""
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
    def crop_yield(crop, age_days, watered_days_in_window, fertilized_days=0):
        """Harvestable units for a one-time crop of the given age."""
        spec = CROP_SPEC.get(crop)
        if spec is None:
            return 0
        seed, first, maxday, ongoing, sched, cap_plain, cap_fert = spec
        if ongoing:
            return 0
        if age_days < first:
            return 0
        cap = cap_fert if fertilized_days > 0 else cap_plain
        units = 1 + watered_days_in_window + fertilized_days
        return int(min(cap, units))

    @staticmethod
    def crop_plan_value(crop, price_hint):
        """Ex-ante value of one tile-cycle of `crop` at an assumed unit price:
        returns (net_value, tile_days, actions, units, age_at_harvest)."""
        seed, first, maxday, ongoing, sched, cap_plain, cap_fert = CROP_SPEC[crop]
        if ongoing:
            units = len(sched)
            age = sched[-1]
            actions = 1 + (age + 1) + units        # plant + daily water + harvests
        else:
            start = CROP_BONUS_START.get(crop, (maxday + 1) // 2)
            age = maxday
            watered = max(0, age - start + 1)
            units = min(cap_plain, 1 + watered)
            actions = 1 + (age + 1) + 1            # plant + daily water + 1 harvest
        tile_days = age + 1
        net = units * price_hint - seed
        return net, tile_days, actions, units, age

    @staticmethod
    def animal_plan_value(animal, days_remaining, price_hint, cared=True):
        """Ex-ante value of one animal held for `days_remaining` days.
        CARE banks +1 per fed-and-cared day and pays out on the next scheduled
        production, so a cared animal produces (1 + interval) per interval."""
        cost = ANIMAL_COST[animal]
        first, interval, max_held = ANIMAL_SPEC[animal]
        productive = max(0, days_remaining - first)
        cycles = productive // interval
        per_cycle = 1 + (interval if cared else 0)
        per_cycle = min(per_cycle, max_held)
        units = cycles * per_cycle
        # daily feed: 1 wheat/day while productive-or-growing
        feed_days = max(0, days_remaining - 1)
        net = units * price_hint - cost
        actions = 1 + 1 + feed_days + (feed_days if cared else 0) + cycles
        return net, units, actions, feed_days



# --------------------------------------------------------------------------
# Bayesian price elasticity filter
# --------------------------------------------------------------------------
class BayesianElasticityFilter:
    """Per-product posterior over *realised* price impact.

    The analytic curve gives the impact of our own order in isolation. The
    opponent sells into the same book and the town drains it every few turns, so
    realised impact is a noisy version of the analytic slope. We keep a scalar
    Normal-Gamma conjugate posterior over

        dPrice_t = -beta * dInventory_t + eps,      eps ~ N(0, 1/tau)
        (beta, tau) ~ NormalGamma(mu, lam, alpha, beta_ng)

    and blend its mean with the analytic slope, weighted by posterior
    confidence. We also estimate the town's net drain rate, which is precisely
    what makes spreading sales across turns more profitable than dumping.
    """

    WINDOW = 12                     # collapse-detection window (turns)
    COLLAPSE_FRAC = 0.15            # >15% drop across the window triggers a pivot
    DRAIN_PRIOR = 0.25              # units/turn/product absorbed by the town

    def __init__(self):
        self.mu = {p: 0.0 for p in PRODUCTS}
        self.lam = {p: 1.0 for p in PRODUCTS}
        self.alpha = {p: 2.0 for p in PRODUCTS}
        self.beta_ng = {p: 1.0 for p in PRODUCTS}
        self.price_hist = {p: [] for p in PRODUCTS}
        self.drain_rate = {p: self.DRAIN_PRIOR for p in PRODUCTS}
        self.collapsed = {p: False for p in PRODUCTS}
        self.collapse_depth = {p: 0.0 for p in PRODUCTS}
        self._prev_inv = None
        self._prev_price = None

    def observe(self, inventory, prices, our_sales_last_turn):
        for p in PRODUCTS:
            pr = float(prices.get(p, MARKET_PARAMS[p][0]))
            h = self.price_hist[p]
            h.append(pr)
            if len(h) > self.WINDOW * 3:
                del h[0]

        if self._prev_inv is not None:
            for p in PRODUCTS:
                d_inv = float(inventory.get(p, 0)) - float(self._prev_inv.get(p, 0))
                d_pr = float(prices.get(p, 0)) - float(self._prev_price.get(p, 0))
                if abs(d_inv) > 1e-9:
                    x = -d_inv                       # regressor
                    lam0, mu0 = self.lam[p], self.mu[p]
                    lam1 = lam0 + x * x
                    mu1 = (lam0 * mu0 + x * d_pr) / lam1
                    self.alpha[p] += 0.5
                    self.beta_ng[p] += 0.5 * (
                        d_pr * d_pr + lam0 * mu0 * mu0 - lam1 * mu1 * mu1)
                    self.beta_ng[p] = max(1e-6, self.beta_ng[p])
                    self.lam[p], self.mu[p] = lam1, mu1
                ours = float(our_sales_last_turn.get(p, 0))
                exogenous = d_inv - ours             # town drain shows up negative
                self.drain_rate[p] = 0.9 * self.drain_rate[p] + 0.1 * max(0.0, -exogenous)

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

    def slope_uncertainty(self, product):
        a, b, lam = self.alpha[product], self.beta_ng[product], self.lam[product]
        if a <= 1.0 or lam <= 0:
            return 1.0
        return math.sqrt(max(1e-9, b / ((a - 1.0) * lam)))

    def effective_price(self, product, inventory, units, risk_lambda=0.0):
        """Risk-adjusted expected unit price for selling `units` right now."""
        if units <= 0:
            return 0.0
        analytic = Econ.marginal_revenue(product, inventory, units) / float(units)
        emp_slope = self.posterior_slope(product)
        emp = Econ.price(product, inventory) - 0.5 * emp_slope * (units - 1)
        sd = self.slope_uncertainty(product)
        w = 1.0 / (1.0 + 4.0 * sd)                   # confidence weight
        blended = (1.0 - w) * analytic + w * max(1.0, emp)
        return max(1.0, blended - risk_lambda * sd * units)


# --------------------------------------------------------------------------
# Backward-induction liquidation gateway
# --------------------------------------------------------------------------
class LiquidationGateway:
    """Hard-armed at turn 650: deterministic flatten-to-cash by turn 720.

    Arming is unconditional and irreversible. The schedule is solved by backward
    induction over (stage, units remaining), in chronological stages:

        V(i, q) = max_{0<=k<=q} [ rev(inv(i,q), k) + V(i+1, q-k) ]
        V(S, q) = 0 if q == 0 else -inf        # unsold stock scores zero at 720
        inv(i,q) = inv0 - drain*tps*i + (total - q)

    The terminal -inf enforces "everything is cash by 720". The drain term makes
    later stages cheaper to sell into, so the optimum is a back-loaded spread
    rather than one dump -- exactly the structure a single price-impact curve
    plus regeneration implies. Solved on a coarse grid and cached, so the
    one-off solve stays far inside the 1s act timeout.
    """

    STAGES = 12
    BUCKETS = 24
    NEG = -1e12

    def __init__(self):
        self.armed = False
        self._cache = {}

    def arm(self, turn):
        """Irreversible. Once armed, stays armed."""
        if turn >= LIQUIDATION_TURN:
            self.armed = True
        return self.armed

    def _solve(self, product, total_units, inv0, drain, turns_left):
        key = (product, int(total_units), int(inv0 // 25), int(turns_left // 6))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        stages = max(1, min(self.STAGES, turns_left))
        tps = turns_left / float(stages)             # turns per stage
        bucket = max(1, int(math.ceil(total_units / float(self.BUCKETS))))
        nq = int(math.ceil(total_units / float(bucket)))

        # Prefix-sum the unit quotes once. price() depends only on absolute
        # inventory, so revenue(inv, n) = C[off+n] - C[off]; without this the
        # DP costs O(stages * nq^2 * bucket) price evaluations and would blow
        # the 1s actTimeout on the very turn the gateway arms.
        inv_lo = max(1.0, inv0 - drain * tps * max(0, stages - 1))
        span = int(inv0 + total_units - inv_lo) + total_units + 2
        span = max(2, min(span, 6000))
        C = [0.0] * (span + 1)
        acc = 0.0
        for m in range(span):
            acc += round(Econ.price(product, inv_lo + m))
            C[m + 1] = acc

        def rev(inv, units):
            if units <= 0:
                return 0.0
            off = int(inv - inv_lo)
            if off < 0:
                off = 0
            a = off if off < span else span
            b = off + units
            b = b if b < span else span
            return C[b] - C[a]

        V_next = [self.NEG] * (nq + 1)
        V_next[0] = 0.0                              # terminal: q>0 is -inf
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
        if len(self._cache) > 256:
            self._cache.clear()
        return plan, tps

    def units_this_turn(self, product, held, inventory, drain, turn):
        """Units of `product` to push this turn under liquidation."""
        turns_left = max(1, HORIZON - turn)
        if held <= 0:
            return 0
        if turns_left <= 3:
            return held                               # unsold stock scores zero
        try:
            plan, tps = self._solve(product, int(held), float(inventory),
                                    float(drain), int(turns_left))
        except Exception:
            return int(math.ceil(held / float(turns_left)))
        if not plan:
            return int(math.ceil(held / float(turns_left)))
        # We re-solve every turn with the *current* holding, so we are always at
        # chronological stage 0 of a freshly solved plan.
        target = plan[0]
        per_turn = int(math.ceil(target / max(1.0, tps)))
        return int(min(held, max(1, per_turn)))


# --------------------------------------------------------------------------
# Direction calibration
# --------------------------------------------------------------------------
class DirectionCalibrator:
    """Learns the true (dx, dy) of each move verb from observed motion.

    The rules do not pin down whether NORTH decreases or increases the row
    index. Rather than assume, we issue moves, watch how our own farmer's
    coordinates actually change, and lock the mapping in. Until it is learned we
    use the conventional mapping, which is corrected within a couple of turns if
    it is wrong. This removes the only silent, total-failure pathing risk.
    """

    DEFAULT = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}

    def __init__(self):
        self.map = dict(self.DEFAULT)
        self.locked = set()
        self._pending = None        # (verb, (x, y)) issued last turn

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
        if (dx, dy) == (0, 0):
            return                  # blocked at an edge: uninformative
        if abs(dx) + abs(dy) == 1:
            self.map[verb] = (dx, dy)
            self.locked.add(verb)
            # the opposite verb is the negation
            opp = {"NORTH": "SOUTH", "SOUTH": "NORTH",
                   "EAST": "WEST", "WEST": "EAST"}[verb]
            if opp not in self.locked:
                self.map[opp] = (-dx, -dy)

    def step_toward(self, src, dst):
        """One move verb that reduces Manhattan distance, or None if arrived."""
        sx, sy = src
        tx, ty = dst
        ddx, ddy = tx - sx, ty - sy
        if ddx == 0 and ddy == 0:
            return None
        # close the larger gap first; deterministic tie-break avoids oscillation
        prefer_x = abs(ddx) > abs(ddy) or (abs(ddx) == abs(ddy) and ddx != 0)
        order = []
        if prefer_x:
            order = [(ddx, 0), (0, ddy)]
        else:
            order = [(0, ddy), (ddx, 0)]
        for want_dx, want_dy in order:
            if want_dx == 0 and want_dy == 0:
                continue
            sign = (1 if want_dx > 0 else -1, 0) if want_dx else (0, 1 if want_dy > 0 else -1)
            for verb, vec in self.map.items():
                if vec == sign:
                    return verb
        return None


# --------------------------------------------------------------------------
# Linear assignment (Hungarian / Jonker-Volgenant, O(n^2 m))
# --------------------------------------------------------------------------
def linear_assignment(cost, n, m):
    """Minimum-cost assignment of n rows to m columns (n <= m).

    Standard JV shortest-augmenting-path formulation with dual potentials.
    Returns a list of length n holding the column assigned to each row.
    """
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
    """Frames worker routing as a linear assignment over a 3-turn lookahead.

    Every worker/task pair is scored by the task's value discounted by the
    travel time needed to reach it (GAMMA per turn, so a task three turns away
    is worth ~42% of an adjacent one). Solving the assignment globally -- rather
    than letting each worker greedily grab the best task -- is what prevents two
    workers converging on the same tile and what stops a worker stalling because
    every nearby task was already claimed.
    """

    GAMMA = 0.75
    LOOKAHEAD = 3
    # The solver is O(n^2 * m). Once the water-filling solve fills ~75 tiles
    # with animals, the raw task list runs to several hundred entries and the
    # assignment alone can blow the 1s actTimeout. A worker can only service
    # one task per turn, so keeping the best few per worker costs nothing:
    # anything outside the top slice was never going to be reached this turn.
    MAX_TASKS_PER_WORKER = 6
    MAX_TASKS = 72

    def __init__(self, calib):
        self.calib = calib

    def _shortlist(self, workers, tasks):
        cap = min(self.MAX_TASKS, max(len(workers), 1) * self.MAX_TASKS_PER_WORKER)
        if len(tasks) <= cap:
            return tasks
        # Rank by value discounted to the nearest worker, so a merely valuable
        # task on the far side of the board cannot crowd out reachable work.
        scored = []
        for t in tasks:
            tx, ty = t["pos"]
            best = None
            for (wx, wy) in workers:
                d = abs(tx - wx) + abs(ty - wy)
                if best is None or d < best:
                    best = d
            scored.append((t["value"] * (self.GAMMA ** min(best or 0, 12)), t))
        scored.sort(key=lambda kv: -kv[0])
        return [t for _v, t in scored[:cap]]

    def assign(self, workers, tasks):
        """workers: [(x, y), ...]; tasks: [task dict, ...] -> [task|None, ...]"""
        n = len(workers)
        if n == 0:
            return []
        if not tasks:
            return [None] * n
        tasks = self._shortlist(workers, tasks)
        # Pad with idle columns so the assignment is always feasible (n <= m).
        m = max(len(tasks), n)
        big = 1e9
        cost = []
        for (wx, wy) in workers:
            row = []
            for t in tasks:
                tx, ty = t["pos"]
                dist = abs(tx - wx) + abs(ty - wy)
                # A task beyond the lookahead still attracts, but weakly.
                discount = self.GAMMA ** min(dist, self.LOOKAHEAD * 4)
                row.append(-t["value"] * discount)
            row.extend([0.0] * (m - len(tasks)))     # idle columns cost nothing
            cost.append(row)
        try:
            sol = linear_assignment(cost, n, m)
        except Exception:
            return self._greedy(workers, tasks)
        out = []
        for i, j in enumerate(sol):
            out.append(tasks[j] if 0 <= j < len(tasks) else None)
        return out

    def _greedy(self, workers, tasks):
        taken = set()
        out = []
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


# --------------------------------------------------------------------------
# Macro revenue engine (rolling-horizon MPC over a KKT water-filling core)
# --------------------------------------------------------------------------
class Plan(object):
    __slots__ = ("crop_mix", "animal_targets", "buy_land", "target_hands",
                 "price_hint", "capacity", "action_value", "reserve",
                 "shadow_td", "tdpu")

    def __init__(self):
        self.crop_mix = {}
        self.animal_targets = {}
        self.buy_land = False
        self.target_hands = 0
        self.price_hint = {}
        self.capacity = {}
        self.reserve = {}          # per-product sell floor, = shadow_td * tdpu
        self.tdpu = {}             # tile-days consumed per unit produced
        self.shadow_td = 1.0       # shadow price of one tile-day
        self.action_value = 1.0


class MPCRevenueEngine:
    """Rolling-horizon MPC whose inner loop is a global water-filling solve.

    THE CENTRAL POINT. Tile-days are the scarce resource; the market is the
    ceiling. The global optimum of that allocation is the KKT condition

        price_p(I0 + X_p) / tdpu_p  =  mu     for every produced p

    i.e. equalise *revenue per tile-day*, not price per unit. mu is the shadow
    price of one tile-day, found by bisection so that total tile-days demanded
    exactly exhausts what the farm has.

    Equalising price per unit instead is the classic local optimum and it is
    badly wrong here, because tdpu varies by ~7x across the board:

        egg 0.63   melon 1.83   wool 1.04   tomato 3.0   strawberry 4.25

    A flat price floor rejects eggs (base $50) while accepting strawberries
    (base $120), even though a tile-day of geese returns roughly twice a
    tile-day of strawberries. Eggs sit on a `log` above-curve -- 2000 of them
    still quote ~$38 -- so their true reserve is far below base, while melon
    sits on `sq` and collapses, so its reserve is far above. One number cannot
    serve both; mu * tdpu_p gives each product its own.

    The same mu then sets the sell-side reservation, so production and
    liquidation are solved consistently rather than fighting each other.
    """

    REPLAN_EVERY = 8                # turns
    MU_LO, MU_HI = 0.5, 4000.0
    BISECT_STEPS = 26
    FERT_TDPU = 0.2                 # fertiliser is an animal byproduct: it
                                    # costs an action to collect, not a tile.

    def __init__(self, elasticity):
        self.el = elasticity
        self.plan = Plan()
        self._last_replan = -999

    def maybe_replan(self, st):
        if st.turn - self._last_replan < self.REPLAN_EVERY and self.plan.crop_mix:
            return self.plan
        self._last_replan = st.turn
        try:
            self.plan = self._replan(st)
        except Exception:
            if not self.plan.crop_mix:
                self.plan.crop_mix = {"WHEAT": max(1, st.usable_tiles // 2)}
        return self.plan

    # -- tile-day cost of one unit of each product ------------------------
    def _tdpu_table(self, days_left):
        out = {}
        for crop in CROP_SPEC:
            net, tile_days, actions, units, age = Econ.crop_plan_value(crop, 1.0)
            if units <= 0 or tile_days <= 0 or age + 1 > days_left:
                continue
            out[crop] = tile_days / float(units)
        for animal, prod in ANIMAL_PRODUCT.items():
            first, interval, max_held = ANIMAL_SPEC[animal]
            productive = days_left - first - 1
            if productive <= 0:
                continue
            cycles = productive // interval
            per_cycle = min(1 + interval, max_held)   # CARE banks +1/day
            units = cycles * per_cycle
            if units <= 0:
                continue
            tdpu = days_left / float(units)
            # keep the cheaper animal if two share a product (they do not today)
            if prod not in out or tdpu < out[prod]:
                out[prod] = tdpu
        if any(ANIMAL_PRODUCT[a] in out for a in ANIMAL_PRODUCT):
            out["FERTILIZER"] = self.FERT_TDPU
        return out

    def _capital_caps(self, st, tdpu, days_left):
        """Unit ceilings implied by cash on hand.

        Tile-days are not the only scarce resource: the farm starts on $3000
        and a goose is $300. An allocation solved on tile-days alone happily
        orders ~39 geese, builds coops it cannot stock, starves the ones it
        does, and finishes below the starting balance. Capital is the binding
        constraint early and stops binding once the crop engine is turning, so
        the ceiling is recomputed every replan and simply relaxes as cash
        accumulates -- which is what makes early revenue behave as a
        multiplier rather than as an end in itself.
        """
        caps = {}
        dl = float(max(1, days_left))

        # Working reserve: feed for the herd plus a seed float. Running the
        # balance to zero loses animals outright, which is unrecoverable.
        herd = sum(st.animals_alive.values())
        feed_reserve = herd * min(days_left, 6) * 25.0
        spare = max(0.0, st.money - feed_reserve)

        for prod, cost in tdpu.items():
            if prod == "FERTILIZER":
                continue
            if prod in CROP_SPEC:
                seed = SEED_COST[prod]
                net, tile_days, actions, units_cycle, age = Econ.crop_plan_value(prod, 1.0)
                if units_cycle <= 0 or seed <= 0:
                    continue
                # Seed spend is per cycle and recycles out of revenue, so
                # allow a generous multiple of current cash.
                tiles = (spare * 0.6) / float(seed)
                cycles = max(1.0, dl / float(max(1, tile_days)))
                caps[prod] = tiles * units_cycle * cycles
            else:
                for animal, produced in ANIMAL_PRODUCT.items():
                    if produced != prod:
                        continue
                    price = ANIMAL_COST[animal]
                    have = st.animals_alive.get(animal, 0)
                    # Animals are a sunk, non-recoverable purchase: only ever
                    # commit a fraction of spare cash to new stock.
                    buyable = int((spare * 0.5) // price)
                    total_animals = have + max(0, buyable)
                    per_animal = dl / cost if cost > 0 else 0.0
                    caps[prod] = total_animals * per_animal
        return caps

    def _demand(self, st, mu, tdpu, turns_to_gate, caps):
        """Tile-days demanded at shadow price `mu`, and the unit targets."""
        total = 0.0
        units = {}
        for prod, cost in tdpu.items():
            inv = st.inventory.get(prod, MARKET_PARAMS[prod][1])
            floor = max(1.0, mu * cost)
            if Econ.price(prod, inv) < floor:
                units[prod] = 0            # not worth a tile-day at this mu
                continue
            headroom = Econ.units_until_price_floor(prod, inv, floor)
            regen = self.el.drain_rate.get(prod, 0.0) * turns_to_gate
            X = headroom + regen
            cap = caps.get(prod)
            if cap is not None:
                X = min(X, cap)            # cannot grow what we cannot finance
            units[prod] = X
            total += X * cost
        return total, units

    def _replan(self, st):
        p = Plan()
        days_left = max(0, DAYS - st.day)
        turns_to_gate = max(1, LIQUIDATION_TURN - st.turn)
        tdpu = self._tdpu_table(days_left)
        p.tdpu = tdpu

        tile_days = max(1.0, st.usable_tiles * float(days_left))
        caps = self._capital_caps(st, tdpu, days_left)

        # Bisect the shadow price so demand exactly exhausts supply. Demand is
        # monotone decreasing in mu, so this is well posed.
        lo, hi = self.MU_LO, self.MU_HI
        if tdpu:
            for _ in range(self.BISECT_STEPS):
                mid = 0.5 * (lo + hi)
                demand, _u = self._demand(st, mid, tdpu, turns_to_gate, caps)
                if demand > tile_days:
                    lo = mid               # too cheap: over-subscribed
                else:
                    hi = mid
        mu = hi
        p.shadow_td = mu
        _total, unit_targets = self._demand(st, mu, tdpu, turns_to_gate, caps)

        for prod in PRODUCTS:
            inv = st.inventory.get(prod, MARKET_PARAMS[prod][1])
            cost = tdpu.get(prod)
            p.reserve[prod] = max(1.0, mu * cost) if cost else 1.0
            p.capacity[prod] = int(unit_targets.get(prod, 0))
            take = max(1, min(12, p.capacity[prod] or 1))
            hint = self.el.effective_price(prod, inv, take, st.risk_lambda)
            p.price_hint[prod] = max(1.0, hint)

        # Units -> standing tiles. One tile runs days_left/tile_days_per_cycle
        # cycles, so tiles = X * tdpu / days_left for crops and animals alike.
        dl = float(max(1, days_left))
        for prod, X in unit_targets.items():
            if X <= 0 or prod == "FERTILIZER":
                continue
            cost = tdpu[prod]
            tiles = int(X * cost / dl)
            if tiles <= 0:
                continue
            if prod in CROP_SPEC:
                p.crop_mix[prod] = tiles
            else:
                for animal, produced in ANIMAL_PRODUCT.items():
                    if produced == prod:
                        p.animal_targets[animal] = tiles

        # Never leave the farm idle: if the solve produced nothing feasible,
        # wheat is always plantable and always absorbs.
        if not p.crop_mix and not p.animal_targets and days_left > 0:
            p.crop_mix["WHEAT"] = max(1, st.usable_tiles // 2)

        # Roughly 4-5 worker actions service one tile-day (plant, water,
        # harvest, carry), so an action is worth about mu/4.
        p.action_value = max(1.0, mu / 4.0)

        # Land: 25 tiles for the rest of the horizon, valued at the shadow
        # price the solve just produced. At $1k/$2k/$4k this clears easily
        # whenever mu is meaningful, which is the correct aggressive answer --
        # tile-days are the binding constraint.
        # Land, but only once the crew can actually work what we already own.
        # Buying a quadrant we cannot tend converts cash -- the thing that
        # buys labour and animals -- into idle tiles, and the census showed
        # exactly that: 50 tiles unlocked on day 1, $1 in the bank, and no
        # hands for the next twelve days.
        next_cost = st.next_land_cost
        crew = 1 + len(st.hands)
        workable = crew * ACTIONS_PER_TILE_DAY
        if next_cost is not None and days_left >= 5:
            marginal = mu * (QUADRANT * QUADRANT) * min(days_left, 14) * 0.40
            p.buy_land = (marginal > next_cost
                          and st.money > next_cost * 2.5
                          and workable >= st.usable_tiles * 0.8)

        # Hands. Labour is the multiplier on everything else: a tile only
        # earns if somebody waters and harvests it, and one farmer is 24
        # actions a day against a board of 25-100 tiles. Hire cost is fib(n),
        # so the first dozen hands cost a few hundred coins in total -- an
        # absurd bargain against a shadow tile-day price in the tens.
        # Size the crew to the board, then clip to what cash allows.
        active = st.usable_tiles
        want_workers = int(math.ceil(active / float(ACTIONS_PER_TILE_DAY)))
        worker_day = 0.45 * p.action_value * TURNS_PER_DAY
        target, cum, a, b = 0, 0, 1, 1
        cash_for_labour = max(0.0, st.money * 0.55)
        while target < min(20, want_workers):
            if a > worker_day or cum + a > cash_for_labour:
                break
            cum += a
            target += 1
            a, b = b, a + b
        p.target_hands = target
        return p


# --------------------------------------------------------------------------
# Market planner
# --------------------------------------------------------------------------
class MarketPlanner:
    """Turns the plan into an ordered market queue.

    Sells lead the queue: order index decides resolution order, and proceeds
    can fund purchases later in the same queue. Volume is governed by the
    per-product reservation `mu * tdpu_p` handed down by the water-filling
    solve -- so eggs keep selling into the high $30s while melon holds out
    above $100 -- and the per-turn rate is capped so the book can refill from
    town consumption between our orders.
    """

    def __init__(self, elasticity, gateway):
        self.el = elasticity
        self.gate = gateway

    def sell_orders(self, st, plan):
        orders = []
        for prod in SELLABLE:
            held = int(st.shed.get(prod, 0))
            if held <= 0:
                continue
            inv = st.inventory.get(prod, MARKET_PARAMS[prod][1])
            drain = self.el.drain_rate.get(prod, 0.0)

            if self.gate.armed:
                n = self.gate.units_this_turn(prod, held, inv, drain, st.turn)
            else:
                floor = plan.reserve.get(prod, 1.0)
                # Opponent denial: the book is shared and the ladder scores
                # win/loss only, so taking premium capacity before they do is
                # worth as much as the cash it earns.
                if st.opp_pressure.get(prod, 0) > 0 and MARKET_PARAMS[prod][0] >= 100:
                    floor *= 0.85
                sellable = Econ.units_until_price_floor(prod, inv, max(1.0, floor))
                turns_to_gate = max(1, LIQUIDATION_TURN - st.turn)
                rate = max(drain, held / float(turns_to_gate), 1.0)
                n = int(min(held, sellable, math.ceil(rate)))
                # The shed holds 100 non-seed items and overflow is destroyed
                # at end of day. The census had it at 96/100 on day 24, so
                # relieve pressure well before the cliff -- a unit sold under
                # its reserve still beats a unit binned at midnight.
                if st.shed_total > SHED_CAPACITY * 0.55:
                    n = max(n, min(held, 10))
            if n > 0:
                orders.append((prod, int(n)))
        orders.sort(key=lambda o: -Econ.price(o[0], st.inventory.get(
            o[0], MARKET_PARAMS[o[0]][1])) * o[1])
        return [["SELL", prod, n] for prod, n in orders]


# --------------------------------------------------------------------------
# State extraction
# --------------------------------------------------------------------------
def _get(obj, key, default=None):
    """Tolerant accessor: the harness may hand us a dict or a struct."""
    try:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
    except Exception:
        return default


class State(object):
    """Flattened, defensive view of one observation."""

    def __init__(self, obs):
        self.player = int(_get(obs, "player", 0) or 0)
        self.day = int(_get(obs, "day", 0) or 0)
        self.hour = int(_get(obs, "hour", 0) or 0)
        step = _get(obs, "step", None)
        # Never trust `step`: a falsy 0 from a trimmed observation would pin the
        # agent to turn 0 forever. day*24+hour is always well defined.
        self.turn = self.day * TURNS_PER_DAY + self.hour
        if isinstance(step, int) and step > self.turn:
            self.turn = step
        self.turn = max(0, min(HORIZON, self.turn))

        farms = _get(obs, "farms", []) or []
        self.me = farms[self.player] if self.player < len(farms) else {}
        self.opp = farms[1 - self.player] if len(farms) > 1 else {}

        priv = _get(obs, "private", {}) or {}
        self.shed = dict(_get(priv, "shed", {}) or {})
        self.seeds = dict(_get(priv, "seeds", {}) or {})
        self.inventories = list(_get(priv, "inventories", []) or [])

        market = _get(obs, "market", {}) or {}
        self.inventory = dict(_get(market, "inventory", {}) or {})
        self.prices = dict(_get(market, "prices", {}) or {})
        for p in PRODUCTS:
            self.inventory.setdefault(p, MARKET_PARAMS[p][1])
            self.prices.setdefault(p, MARKET_PARAMS[p][0])

        town = _get(obs, "town", {}) or {}
        self.shops = list(_get(town, "unlocked_shops", []) or [])

        self.money = float(_get(self.me, "money", 0.0) or 0.0)
        self.opp_money = float(_get(self.opp, "money", 0.0) or 0.0)
        self.tiles = _get(self.me, "tiles", []) or []
        self.opp_tiles = _get(self.opp, "tiles", []) or []
        self.farmer = list(_get(self.me, "farmer", [0, 0]) or [0, 0])
        self.hands = [list(h) for h in (_get(self.me, "hands", []) or [])]
        self.hires_today = int(_get(self.me, "hires_today", 0) or 0)
        self.quadrants = set(_get(self.me, "unlocked_quadrants", ["NW"]) or ["NW"])

        self.shed_total = sum(v for k, v in self.shed.items() if k in PRODUCTS
                              or k in ANIMAL_COST)
        self.usable_tiles = self._count_usable()
        self.next_land_cost = self._next_land_cost()
        self.opp_pressure = self._opp_pressure()
        self.animals_alive, self.empty_structs = self._scan_structures()
        self.risk_lambda = 0.0

    def _count_usable(self):
        n = 0
        for row in self.tiles:
            for t in row:
                if t != "LOCKED":
                    n += 1
        return n if n else QUADRANT * QUADRANT

    def _next_land_cost(self):
        bought = max(0, len(self.quadrants) - 1)
        if bought >= len(LAND_COSTS):
            return None
        return LAND_COSTS[bought]

    def _opp_pressure(self):
        """Premium products the opponent is about to dump into the shared book."""
        pressure = {}
        for row in self.opp_tiles:
            for t in row:
                if isinstance(t, dict):
                    if t.get("kind") == "PLANT":
                        crop = t.get("crop")
                        if crop in CROP_SPEC:
                            age = self.day - int(t.get("planted_day", self.day))
                            if age >= CROP_SPEC[crop][1] - 2:
                                pressure[crop] = pressure.get(crop, 0) + 1
                    elif t.get("animal"):
                        prod = ANIMAL_PRODUCT.get(t.get("animal"))
                        if prod:
                            pressure[prod] = pressure.get(prod, 0) + 1
        return pressure

    def _scan_structures(self):
        """Own coops/pastures: what is stocked, and what is standing empty.

        The planner runs before task generation, so it needs its own view of
        the herd -- otherwise it re-buys animals it already owns and keeps
        building coops it cannot stock.
        """
        alive = {"GOOSE": 0, "COW": 0, "SHEEP": 0}
        empty = []
        for y, row in enumerate(self.tiles):
            for x, t in enumerate(row):
                if not isinstance(t, dict):
                    continue
                kind = t.get("kind")
                if kind not in ("COOP", "PASTURE"):
                    continue
                animal = t.get("animal")
                if animal:
                    alive[animal] = alive.get(animal, 0) + 1
                else:
                    empty.append(((x, y), kind))
        return alive, empty

    def tile_at(self, x, y):
        try:
            return self.tiles[y][x]
        except Exception:
            return "LOCKED"

    def shed_access_tiles(self):
        c = BOARD // 2
        return [(c - 1, c - 1), (c, c - 1), (c - 1, c), (c, c)]

    def compute_risk(self):
        """Ladder scores win/loss/tie only -- the coin margin is discarded. So
        the objective is P(my bank > their bank), not E[my bank]. Ahead late we
        shed variance; behind late we buy it."""
        if self.turn < 420:
            self.risk_lambda = 0.0
            return
        mine = self.money + sum(
            self.shed.get(p, 0) * Econ.price(p, self.inventory.get(p, 0))
            for p in PRODUCTS)
        theirs = self.opp_money
        edge = mine - theirs
        scale = 25000.0
        self.risk_lambda = max(-0.6, min(0.6, edge / scale))


# --------------------------------------------------------------------------
# Task generation
# --------------------------------------------------------------------------
CRITICAL = 1.0e6


def _plant_age(st, tile):
    return st.day - int(tile.get("planted_day", st.day))


def build_tasks(st, plan):
    """Every legal, useful field action this turn, valued in coins.

    Survival actions (a plant one missed watering from becoming a weed, an
    animal one missed feed from escaping) are priced at CRITICAL because losing
    the asset forfeits its entire remaining production, which dwarfs any
    marginal gain elsewhere on the board.
    """
    tasks = []
    add = tasks.append
    day = st.day
    days_left = max(0, DAYS - day)

    empties = []
    empty_structs = []      # (pos, animal_kind_needed)
    animals_alive = {"GOOSE": 0, "COW": 0, "SHEEP": 0}

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
                     "value": 0.6 * plan.action_value})
                continue

            if kind == "PLANT":
                crop = tile.get("crop")
                spec = CROP_SPEC.get(crop)
                if spec is None:
                    continue
                seed, first, maxday, ongoing, sched, cap_plain, cap_fert = spec
                age = _plant_age(st, tile)
                price = plan.price_hint.get(crop, MARKET_PARAMS[crop][0])
                units_now = int(tile.get("yield_units", 0) or 0)
                unwatered = int(tile.get("consecutive_unwatered", 0) or 0)
                watered = bool(tile.get("watered_today", False))

                if not watered:
                    if unwatered >= 1:
                        # Dies at end of day. Forfeits the whole plant.
                        remaining = max(units_now, cap_plain) * price
                        add({"pos": pos, "op": ["WATER"], "kind": "WATER",
                             "value": CRITICAL + remaining})
                    else:
                        start = CROP_BONUS_START.get(crop, (maxday + 1) // 2)
                        in_window = (not ongoing) and start <= age <= maxday
                        bonus = price if in_window else 0.0
                        if ongoing and tile.get("fertilized_until_day", -1) >= day:
                            bonus = price      # fertilised ongoing crops double
                        if bonus > 0:
                            add({"pos": pos, "op": ["WATER"], "kind": "WATER",
                                 "value": bonus})

                ready = units_now > 0
                if ready:
                    if ongoing:
                        add({"pos": pos, "op": ["HARVEST"], "kind": "HARVEST",
                             "value": units_now * price})
                    else:
                        decaying = age > maxday
                        at_peak = age >= maxday
                        if at_peak or decaying or days_left <= 1:
                            urgency = 1.6 if decaying else 1.0
                            add({"pos": pos, "op": ["HARVEST"], "kind": "HARVEST",
                                 "value": units_now * price * urgency})

                if (st.shed.get("FERTILIZER", 0) > 0
                        and not ongoing
                        and tile.get("fertilized_until_day", -1) < day
                        and age < maxday):
                    add({"pos": pos, "op": ["FERTILIZE"], "kind": "FERTILIZE",
                         "value": 1.2 * price})
                continue

            if kind in ("COOP", "PASTURE"):
                animal = tile.get("animal")
                if not animal:
                    need = "GOOSE" if kind == "COOP" else None
                    empty_structs.append((pos, kind))
                    continue
                animals_alive[animal] = animals_alive.get(animal, 0) + 1
                prod = ANIMAL_PRODUCT.get(animal, "EGG")
                price = plan.price_hint.get(prod, MARKET_PARAMS[prod][0])
                first, interval, max_held = ANIMAL_SPEC[animal]
                unfed = int(tile.get("consecutive_unfed", 0) or 0)
                fed = bool(tile.get("fed_today", False))
                cared = bool(tile.get("cared_today", False))
                units_now = int(tile.get("yield_units", 0) or 0)

                if not fed and st.shed.get("WHEAT", 0) > 0:
                    if unfed >= 1:
                        # Escapes tonight, unrecoverable: forfeits every future unit.
                        future = (max(0, days_left - 1) / float(interval)) * price
                        add({"pos": pos, "op": ["FEED"], "kind": "FEED",
                             "value": CRITICAL + future})
                    else:
                        add({"pos": pos, "op": ["FEED"], "kind": "FEED",
                             "value": (price / float(interval)) * 1.5})
                if fed and not cared and days_left > interval:
                    # CARE banks +1 per fed-and-cared day, paid on next production.
                    add({"pos": pos, "op": ["CARE"], "kind": "CARE",
                         "value": price * 0.9})
                if units_now > 0:
                    add({"pos": pos, "op": ["HARVEST"], "kind": "HARVEST",
                         "value": units_now * price})
                if tile.get("fertilizer_available"):
                    fprice = plan.price_hint.get("FERTILIZER", 100)
                    add({"pos": pos, "op": ["COLLECT_FERTILIZER"],
                         "kind": "COLLECT", "value": 0.8 * fprice})

    # --- planting ---------------------------------------------------------
    want = dict(plan.crop_mix)
    planted_slots = 0
    for pos in empties:
        if planted_slots >= len(empties):
            break
        crop = None
        for c in sorted(want, key=lambda k: -plan.price_hint.get(k, 0)):
            if want[c] > 0 and st.seeds.get(c, 0) > planted_slots:
                spec = CROP_SPEC[c]
                if spec[2] + 1 <= days_left:
                    crop = c
                    break
        if crop is None:
            break
        want[crop] -= 1
        planted_slots += 1
        net = Econ.crop_plan_value(crop, plan.price_hint[crop])[0]
        add({"pos": pos, "op": ["PLANT", crop], "kind": "PLANT",
             "value": max(1.0, net)})

    # --- structures -------------------------------------------------------
    need_coops = max(0, plan.animal_targets.get("GOOSE", 0) - animals_alive["GOOSE"])
    need_past = max(0, plan.animal_targets.get("COW", 0) + plan.animal_targets.get("SHEEP", 0)
                    - animals_alive["COW"] - animals_alive["SHEEP"])
    have_empty_coop = sum(1 for _, k in empty_structs if k == "COOP")
    have_empty_past = sum(1 for _, k in empty_structs if k == "PASTURE")
    build_coops = max(0, need_coops - have_empty_coop)
    build_past = max(0, need_past - have_empty_past)
    # An empty coop is a dead tile and a wasted action. Only raise housing we
    # can actually stock -- either the animal is already in the shed, or there
    # is cash on hand to buy one.
    if not (st.shed.get("GOOSE", 0) > 0 or st.money >= ANIMAL_COST["GOOSE"] * 1.3):
        build_coops = 0
    if not (st.shed.get("COW", 0) > 0 or st.shed.get("SHEEP", 0) > 0
            or st.money >= ANIMAL_COST["COW"] * 1.3):
        build_past = 0
    free = [p for p in empties if p not in {t["pos"] for t in tasks if t["kind"] == "PLANT"}]
    bi = 0
    for _ in range(min(build_coops, len(free))):
        add({"pos": free[bi], "op": ["BUILD_COOP"], "kind": "BUILD",
             "value": 0.5 * plan.price_hint.get("EGG", 50) * max(1, days_left - 5)})
        bi += 1
    for _ in range(min(build_past, max(0, len(free) - bi))):
        add({"pos": free[bi], "op": ["BUILD_PASTURE"], "kind": "BUILD",
             "value": 0.5 * plan.price_hint.get("MILK", 160) * max(1, days_left - 9)})
        bi += 1

    st._empty_structs = empty_structs
    st._animals_alive = animals_alive
    return tasks


# --------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------
SAFE_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}


class KaggricultureAgent(object):
    """Finite-horizon MDP controller.

    Turn loop: ingest -> filter -> (re)plan -> generate tasks -> assign labour
    -> emit market queue. Every stage is wrapped so that a failure degrades to a
    legal action rather than an episode error; an exception or a >1s turn is an
    automatic loss, so robustness strictly dominates cleverness here.
    """

    def __init__(self):
        self.el = BayesianElasticityFilter()
        self.gate = LiquidationGateway()
        self.mpc = MPCRevenueEngine(self.el)
        self.calib = DirectionCalibrator()
        self.labor = LaborAssigner(self.calib)
        self.market = MarketPlanner(self.el, self.gate)
        self.last_sales = {}
        self.last_turn = -1

    # -- helpers ---------------------------------------------------------
    def _inv_of(self, st, idx):
        try:
            inv = st.inventories[idx]
            return dict(inv) if inv else {}
        except Exception:
            return {}

    def _nearest(self, src, candidates):
        best, bd = None, None
        for c in candidates:
            d = abs(c[0] - src[0]) + abs(c[1] - src[1])
            if bd is None or d < bd:
                best, bd = c, d
        return best, (bd if bd is not None else 0)

    def _goto_or(self, pos, dst, op):
        """Perform `op` if standing on `dst`, else step toward it."""
        if tuple(pos) == tuple(dst):
            return list(op)
        verb = self.calib.step_toward(pos, dst)
        return [verb] if verb else ["PASS"]

    # -- main ------------------------------------------------------------
    def act(self, obs):
        t0 = time.time()
        st = State(obs)

        if st.turn <= self.last_turn:
            pass                                    # replayed/repeated turn
        self.last_turn = st.turn

        self.calib.observe(st.farmer)
        self.el.observe(st.inventory, st.prices, self.last_sales)
        st.compute_risk()
        self.gate.arm(st.turn)                      # hard, irreversible at 650

        plan = self.mpc.maybe_replan(st)

        # --- field actions -------------------------------------------------
        workers = [tuple(st.farmer)] + [tuple(h) for h in st.hands]
        n_hands = len(st.hands)
        actions = [None] * len(workers)

        shed_tiles = st.shed_access_tiles()
        try:
            tasks = build_tasks(st, plan)
        except Exception:
            tasks = []
        empty_structs = getattr(st, "_empty_structs", [])

        # Special duties resolved before the assignment: a worker holding stock
        # is committed, and routing it through the optimiser would only let a
        # field task outbid the delivery it is already halfway through.
        free_idx = []
        for i, wpos in enumerate(workers):
            inv = self._inv_of(st, i)
            carried_animal = next((a for a in ANIMAL_COST if inv.get(a, 0) > 0), None)
            if carried_animal:
                want_kind = ANIMAL_STRUCTURE[carried_animal]
                slots = [p for p, k in empty_structs if k == want_kind]
                if slots:
                    dst, _ = self._nearest(wpos, slots)
                    empty_structs = [(p, k) for p, k in empty_structs if p != dst]
                    actions[i] = self._goto_or(wpos, dst, ["PLACE", carried_animal, 1])
                    continue
            produce = sum(v for k, v in inv.items() if k in PRODUCTS)
            if produce > 0:
                near_task = any(
                    abs(t["pos"][0] - wpos[0]) + abs(t["pos"][1] - wpos[1]) <= 1
                    and t["value"] >= CRITICAL for t in tasks)
                deliver = produce >= 3 or st.hour >= TURNS_PER_DAY - 6 or self.gate.armed
                if deliver and not near_task:
                    dst, _ = self._nearest(wpos, shed_tiles)
                    actions[i] = self._goto_or(wpos, dst, ["DROP"])
                    continue
            free_idx.append(i)

        # Fetch a purchased animal out of the shed when a home is waiting.
        pending_animal = next((a for a in ANIMAL_COST if st.shed.get(a, 0) > 0), None)
        if pending_animal and empty_structs and free_idx:
            want_kind = ANIMAL_STRUCTURE[pending_animal]
            if any(k == want_kind for _, k in empty_structs):
                i = free_idx[0]
                wpos = workers[i]
                dst, _ = self._nearest(wpos, shed_tiles)
                actions[i] = self._goto_or(wpos, dst, ["PICKUP", pending_animal, 1])
                free_idx = free_idx[1:]

        # Global labour assignment over whoever is still free.
        if free_idx and tasks:
            if time.time() - t0 < TURN_BUDGET_S:
                chosen = self.labor.assign([workers[i] for i in free_idx], tasks)
            else:
                chosen = self.labor._greedy([workers[i] for i in free_idx], tasks)
            for slot, i in enumerate(free_idx):
                t = chosen[slot] if slot < len(chosen) else None
                if t is None:
                    actions[i] = ["PASS"]
                else:
                    actions[i] = self._goto_or(workers[i], t["pos"], t["op"])
        else:
            for i in free_idx:
                actions[i] = ["PASS"]

        for i in range(len(actions)):
            if not actions[i]:
                actions[i] = ["PASS"]

        farmer_action = actions[0] if actions else ["PASS"]
        self.calib.note_issued(farmer_action[0], st.farmer)
        hand_actions = actions[1:1 + n_hands]
        while len(hand_actions) < n_hands:
            hand_actions.append(["PASS"])

        # --- market queue ----------------------------------------------------
        market = self._market_queue(st, plan, t0)

        self.last_sales = {}
        for o in market:
            if o and o[0] == "SELL":
                self.last_sales[o[1]] = self.last_sales.get(o[1], 0) + o[2]

        return {"farmer": farmer_action, "hands": hand_actions, "market": market}

    def _market_queue(self, st, plan, t0):
        """Ordered orders, sells first so proceeds fund the same turn's buys."""
        days_left = max(0, DAYS - st.day)
        n_animals = sum(st.animals_alive.values())

        # Reserve the wheat the herd will eat; feeding is what keeps animals
        # alive, and a starved animal is an unrecoverable write-off.
        reserve_wheat = min(60, n_animals * max(1, min(days_left, 6)))
        true_shed = dict(st.shed)
        sell_view = dict(st.shed)
        if reserve_wheat > 0 and not self.gate.armed:
            sell_view["WHEAT"] = max(0, sell_view.get("WHEAT", 0) - reserve_wheat)
        st.shed = sell_view
        try:
            orders = self.market.sell_orders(st, plan)
        except Exception:
            orders = []
        finally:
            st.shed = true_shed

        # Never spend into the feed reserve: a starved animal is lost
        # outright and cannot be replaced for its remaining production.
        working_reserve = n_animals * min(days_left, 5) * 25.0
        budget = float(st.money) - working_reserve
        for o in orders:
            budget += Econ.marginal_revenue(
                o[1], st.inventory.get(o[1], MARKET_PARAMS[o[1]][1]), o[2])

        if self.gate.armed:
            # Nothing but liquidation: no new growth can mature before 720.
            return orders[:MAX_MARKET_ORDERS]

        buys = []
        crew = 1 + len(st.hands)

        # LABOUR FIRST. This ordering is the whole game in the opening: hands
        # cost fib(n) -- the first ten together are ~$143 -- and every other
        # purchase is worthless without somebody to work it. Spending the
        # opening balance on land and seeds first leaves nothing to hire with,
        # and with one farmer against 50 tiles the farm never earns enough to
        # hire later. That is a trap the tile-day solve cannot see, because it
        # assumes the labour to work its allocation exists.
        to_hire = max(0, plan.target_hands - st.hires_today)
        if to_hire > 0 and st.hour <= 6:
            a, b = 1, 1
            for _ in range(st.hires_today):
                a, b = b, a + b
            for _ in range(min(to_hire, 8)):
                if budget < a:
                    break
                buys.append(["HIRE"])
                budget -= a
                a, b = b, a + b

        # Seeds, capped by what the crew can actually tend. Seed bought for a
        # tile nobody waters is a plant that becomes a weed.
        workable = max(1, crew * ACTIONS_PER_TILE_DAY)
        plantable = max(0, min(st.usable_tiles, workable))
        for crop, want in sorted(plan.crop_mix.items(),
                                 key=lambda kv: -plan.price_hint.get(kv[0], 0)):
            if want <= 0 or CROP_SPEC[crop][2] + 1 > days_left:
                continue
            have = st.seeds.get(crop, 0)
            need = max(0, min(want, plantable) - have)
            if need <= 0:
                continue
            cost = SEED_COST[crop]
            afford = int(min(need, budget // cost)) if cost else 0
            if afford > 0:
                buys.append(["BUY_SEED", crop, afford])
                budget -= afford * cost

        # Wheat for feed, when the herd out-eats the harvest.
        if n_animals > 0:
            short = reserve_wheat - true_shed.get("WHEAT", 0)
            if short > 0:
                price = Econ.price("WHEAT", st.inventory.get("WHEAT", 10000))
                afford = int(min(short, budget // max(1.0, price)))
                if afford > 0:
                    buys.append(["BUY_PRODUCT", "WHEAT", afford])
                    budget -= afford * price

        # Animals: the only asset that scales, since EGG sits on a log
        # above-curve. Ahead of land, because a stocked coop earns and a
        # bought quadrant merely could.
        for animal in ("GOOSE", "COW", "SHEEP"):
            target = plan.animal_targets.get(animal, 0)
            alive = st.animals_alive.get(animal, 0)
            in_shed = true_shed.get(animal, 0)
            need = target - alive - in_shed
            cost = ANIMAL_COST[animal]
            if (need > 0 and budget > cost * 2.0
                    and days_left > ANIMAL_SPEC[animal][0] + 1):
                buys.append(["BUY_ANIMAL", animal, 1])
                budget -= cost

        # Land last: it is the only purchase that produces nothing by itself.
        if plan.buy_land and st.next_land_cost and budget > st.next_land_cost:
            buys.append(["BUY_LAND"])
            budget -= st.next_land_cost

        return (orders + buys)[:MAX_MARKET_ORDERS]


# --------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------
_AGENTS = {}


def agent(obs, config=None):
    """Kaggle entrypoint. Never raises: an exception forfeits the episode."""
    try:
        player = int(_get(obs, "player", 0) or 0)
    except Exception:
        player = 0
    try:
        # Keyed by player so a validation episode (agent vs. a copy of itself in
        # one process) cannot cross-contaminate the two controllers' state.
        inst = _AGENTS.get(player)
        if inst is None:
            inst = _AGENTS[player] = KaggricultureAgent()
        action = inst.act(obs)
        if not isinstance(action, dict):
            return dict(SAFE_ACTION)
        action.setdefault("farmer", ["PASS"])
        action.setdefault("hands", [])
        action.setdefault("market", [])
        return action
    except Exception:
        return {"farmer": ["PASS"], "hands": [], "market": []}


__all__ = ["agent", "KaggricultureAgent", "Econ"]
