# Architecture

Derived from the competition rules and the published economic tables only. No
public leaderboard solution was consulted.

## 1. What the game actually optimises

Two facts from the rules dominate everything else.

**The score is a binary outcome, not a margin.** The evaluation page is
explicit: "The actual coin difference in a match does not affect the rating
change — only the win, loss, or tie outcome matters." So the objective is
`P(my bank > their bank)`, not `E[my bank]`. These diverge sharply at the
margins: holding a lead, a risk-neutral maximiser will take a fair gamble that
a win-probability maximiser must refuse. Since the opponent's cash and tiles
are public, the agent can measure its edge directly and price variance
accordingly — see `State.compute_risk`, which drives `risk_lambda` into the
market planner from turn 420 onward.

**Market absorption is the binding constraint — not land, not labour.**

| Input | Cost to saturate | Verdict |
| --- | --- | --- |
| Labour | hands cost `fib(n)`: ten hands ≈ $143/day for 240 actions | effectively free |
| Land | $1k + $2k + $4k for all 100 tiles | cheap, one-off |
| Market | premium goods hit the $1 floor within ~60–160 units | **the real ceiling** |

Solving `price(inv) = 1` on each above-curve gives the lifetime capacity of each
product for the *entire shared book* (both players plus the town):

| Product | Above curve | Units until the $1 floor |
| --- | --- | --- |
| Wheat | `log`, 0.20 | effectively unbounded (~$19 at +1000) |
| Egg | `log`, 0.20 | effectively unbounded (~$38 at +1000) |
| Carrot | `sqrt`, 0.70 | ~870 |
| Tomato | `sqrt`, 0.60 | ~540 |
| Melon | `sq`, 3.60 | **~158** |
| Milk | `linear`, 1.60 | **~76** |
| Strawberry | `linear`, 1.60 | **~62** |
| Wool | `sq`, 3.20 | **~59** |

This reframes the whole game. Production is trivially scalable; the skill is in
not farming a crop into worthlessness.

## 2. Where the value is

Value per tile-day at base prices, from the yield rules:

| Asset | Units | Gross | Net of seed | Tile-days | **Net / tile-day** |
| --- | --- | --- | --- | --- | --- |
| Melon | 6 @ age 10 | $1500 | $1420 | 11 | **$129** |
| Goose (fed + cared) | ~2 eggs/day | — | ~$1950 over 29d | 29 | **$67** |
| Strawberry | 4 | $480 | $380 | 17 | $22 |
| Carrot | 3 @ age 3 | $105 | $85 | 4 | $21 |
| Wheat | 4 @ age 4 | $100 | $90 | 5 | $18 |
| Tomato | 4 | $240 | $190 | 12 | $16 |

Melon dominates by 2× — and its capacity is ~158 units, which is 26 tiles of
six. A 5×5 quadrant is 25 tiles. **The melon allocation and one quadrant are
the same number**, which falls straight out of the price curve rather than
being tuned.

`CARE` is the other large, under-priced lever: it banks +1 unit per fed-and-cared
day and pays out on the next scheduled production, so a cared goose yields
~2 eggs/day instead of 1 — and egg sits on a `log` above-curve that absorbs
thousands of units. Geese are therefore the only asset that scales.

Integrating the melon curve, `∫₀^X (250 − 0.01x²)dx`, peaks at `X = 158` for a
theoretical ceiling of ~$26k from melon alone. That is the number the planner is
implicitly chasing.

## 3. Components

### Capacity is a flow, not a stock

The single most important modelling choice. The table above gives *instantaneous*
headroom — what the book will absorb right now. But the town centre drains every
24 turns and each of up to 8 shop instances drains every 4 turns, so demand
regenerates continuously. Total absorption before the liquidation gateway is

```
capacity ≈ headroom(now) + drain_rate × turns_remaining
```

Sizing a 30-day plan off the snapshot alone under-plants the farm several times
over: at turn 0 a 90%-of-base reservation leaves melon room for only ~50 units
(8 tiles), wheat ~19 (4 tiles), strawberry ~6 (1 tile) — 17 of 25 tiles, most of
them singletons. `BayesianElasticityFilter.drain_rate` therefore starts from a
rules-based prior rather than zero, and the posterior takes over within ~12 turns.

Planning generously is safe because the two sides are decoupled: the planner
decides what to *grow*, while the sell-side reservation price independently
refuses to *dump* below `frac × base`. Overplanting costs seed and labour, both
of which are nearly free; underplanting forfeits tile-days, which are the
binding constraint.

### The global-optimum core: equalise revenue per tile-day

Tile-days are the scarce resource and the market is the ceiling, so the optimal
allocation satisfies the KKT condition

```
price_p(I0 + X_p) / tdpu_p  =  mu      for every produced p
```

where `tdpu_p` is tile-days consumed per unit and `mu` is the shadow price of a
tile-day, found by bisection so demand exactly exhausts supply.

Equalising **price per unit** instead is the classic local optimum, and it is
badly wrong here because `tdpu` varies about 7x across the board:

| | egg | wool | milk | melon | carrot | wheat | tomato | strawberry |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `tdpu` | 0.63 | 1.04 | 1.04 | 1.83 | 1.33 | 1.25 | 3.0 | 4.25 |

A flat price floor rejects eggs (base $50) while accepting strawberries (base
$120) — even though a tile-day of geese returns roughly twice a tile-day of
strawberries. Eggs sit on a `log` above-curve, so 2,000 of them still quote
~$38 and their true reserve is far *below* base; melon sits on `sq` and
collapses, so its reserve is far *above*. One number cannot serve both.
`mu * tdpu_p` gives each product its own.

At 100 tiles this solve returns roughly 39 geese, 20 melon tiles, 8 cows and
8 sheep — against ~4 geese and 181 wasted strawberry units under a flat floor.

Measured: a flat floor scored a median margin of **−68,628** against the
incumbent; widening capacity without fixing the floor made it **−78,716**,
because it simply grew more of the wrong thing.

The same `mu` sets the sell-side reservation, so production and liquidation are
solved consistently instead of fighting each other.

### Macro revenue engine (`MPCRevenueEngine`)
Rolling-horizon MPC, replanning every 8 turns. Each replan re-derives, from live
market state, the value of a tile-day and of an action, then allocates the farm
by value density — **capped by absorption**: `units_until_price_floor` bounds
each crop's tile count so the plan can never overproduce into the floor. Early
capital is scored purely as a multiplier (value per tile-day over the remaining
horizon), never as standalone cash, so the engine front-loads whatever compounds
fastest. Land and hand-count fall out of the same marginal calculation: buy a
quadrant when 25 tile-days × density clears the price; hire while `fib(n)` is
below the value of a worker-day.

### Vectorised labour allocation (`LaborAssigner`)
Workers × tasks is scored as a matrix, each entry the task's coin value
discounted by travel time (`γ=0.75` per turn over a 3-turn lookahead), and solved
as a **linear assignment problem** by Jonker–Volgenant with dual potentials
(`linear_assignment`). Solving globally rather than greedily is what prevents two
workers converging on the same tile and what stops a worker stalling because
every nearby task was already claimed. Idle columns pad the matrix so it is
always feasible; a greedy fallback covers the time budget.

Survival actions are priced at `CRITICAL` (10⁶): a plant one missed watering from
becoming a weed, or an animal one missed feed from escaping, forfeits its entire
remaining production, which dominates any marginal gain elsewhere.

### Bayesian price elasticity filter (`BayesianElasticityFilter`)
The analytic curve is exact for our own order, but the opponent sells into the
same book and the town drains it, so *realised* impact is noisy. A scalar
Normal-Gamma conjugate posterior is maintained over
`dPrice = −β·dInventory + ε`, and its mean is blended with the analytic slope,
weighted by posterior confidence. The filter also estimates the town's net drain
rate, which is what makes spreading sales across turns strictly better than
dumping.

Over a rolling 12-turn window, a price drop past **15%** sets a collapse flag;
the MPC then derates that crop's value density by twice the collapse depth,
pivoting the allocation on a maximum-expected-utility basis.

### Backward-induction liquidation (`LiquidationGateway`)
Hard-armed at **turn 650**, unconditionally and irreversibly. The schedule is a
backward induction over (stage, units remaining):

```
V(i, q) = max_{0<=k<=q} [ rev(inv(i,q), k) + V(i+1, q−k) ]
V(S, q) = 0 if q == 0 else −inf          # unsold stock scores zero at 720
inv(i,q) = inv0 − drain·tps·i + (total − q)
```

The `−inf` terminal enforces flat-to-cash by 720. The drain term makes later
stages cheaper to sell into, so the optimum is a back-loaded spread rather than
one dump. Solved on a coarse 12×24 grid and cached, keeping the one-off solve
far inside the 1s act timeout.

Note that the reservation-price schedule already sells continuously from turn 0,
so by 650 there is usually little left. The gateway is a guarantee, not the main
revenue event — which is the correct relationship, since the town keeps
regenerating demand and hoarding for a late dump destroys value.

## 4. Robustness

An exception or a turn over 1s forfeits the episode, so robustness strictly
dominates cleverness:

- **Single file, zero imports.** The contract lists import-path failure on
  `/kaggle_simulations/agent/` as a top cause of `Error` submissions. A
  self-contained stdlib-only `main.py` has no import surface at all.
- **`step` is never trusted.** A falsy `0` from a trimmed observation would pin
  the agent to turn 0 forever; `day*24 + hour` is always well defined.
- **Movement is self-calibrating.** The rules do not pin down whether `NORTH`
  decreases or increases the row index. `DirectionCalibrator` issues a move,
  watches how the farmer's coordinates actually change, and locks the mapping
  in — removing the only silent, total-failure pathing risk.
- **State is keyed by player id**, so a validation episode (agent vs. a copy of
  itself, possibly in one process) cannot cross-contaminate the controllers.
- **Turn budget guard** at 0.55s falls back from Hungarian to greedy.
- **Every stage is wrapped**; `agent()` cannot raise.
