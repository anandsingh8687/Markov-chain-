# Architecture

Derived from the official Kaggriculture interpreter
(`kaggle_environments/envs/kaggriculture/kaggriculture.py`) and the published
rule tables. No public leaderboard agent was consulted.

## 1. What the game actually optimises

Two facts from the evaluation page dominate the rest.

**The score is a binary outcome, not a margin.** "The actual coin difference in
a match does not affect the rating change — only the win, loss, or tie outcome
matters." The objective is `P(my bank > their bank)` at turn 720. Unsold shed
and carried inventory is worth zero.

**Market absorption is the binding constraint.** Labour costs `fib(n)` per day
(ten hands ≈ $143). All four quadrants cost $7k once. Premium goods hit the $1
floor in tens to low hundreds of units:

| Product | Above curve | Units to $1 floor (approx.) |
| --- | --- | --- |
| Wheat / egg | `log`, 0.20 | thousands — they absorb |
| Carrot | `sqrt`, 0.70 | ~870 |
| Tomato | `sqrt`, 0.60 | ~540 |
| Melon | `sq`, 3.60 | ~158 |
| Milk | `linear`, 1.60 | ~76 |
| Strawberry | `linear`, 1.60 | ~62 |
| Wool | `sq`, 3.20 | ~59 |

Production is easy to scale. The skill is not farming a crop into worthlessness,
and not leaving tile-days idle while the book still has room.

## 2. Engine facts the previous local-optima agents get wrong

Read from the interpreter, not from prose:

- `FEED` calls `_inv_take(inv, "WHEAT", 1)` on the **acting worker**. Wheat in
  the shed cannot feed an animal. The worker must `PICKUP WHEAT` first.
- `FERTILIZE` likewise consumes carried fertilizer, not shed fertilizer.
- `SELL` / `BUY_ANIMAL` / `BUY_PRODUCT` touch the shed only.
- If N workers `PLANT C` and `seeds[C] < N`, **every** plant of C that turn is
  voided.
- Market resolves **after** farm actions. Seeds bought this turn cannot be
  planted until the next turn. Hands hired this turn act from the next turn.
- A fresh plant starts with `consecutive_unwatered = 1`. Planting on hour 23
  without a same-turn watering (impossible for one worker) makes a weed at EOD.
- Melon: `max_yield_day = 12`, `first_yield_day = 10`, cap 6. Bonus window
  opens at `ceil(12/2) = 6`. Harvest at age 10 once the cap is reached.
- Empty coop/pasture is `{"kind": "COOP"}` — the `"animal"` key is absent.
- Shop ids are `PIZZA_SHOP`, `BRUNCH_SPOT`, `YARN_STORE`, … not display names.
- `NORTH = (0, -1)`; `tiles[y][x]`; farmer is `[x, y]`.

## 3. Global optimum, not local

Tile-days are scarce and the market is the ceiling. The inner allocation
satisfies the KKT condition

```
price_p(I0 + X_p) / tdpu_p  =  mu      for every produced p
```

Equalising **price per unit** is the local optimum and it is wrong: `tdpu`
varies about 7× (egg 0.5, melon 1.83, strawberry 4.25). A flat floor rejects
eggs (base $50, log glut curve) and accepts strawberries (base $120, linear
crash). A cared goose is the only asset that scales; melon is the highest
density **capacity-capped** crop.

Capacity is a flow:

```
X_p = headroom(now, reserve_p) + drain_p * turns_left - opponent_pipeline_p
```

`drain_p` is the official town-center (1 / 24) plus each unlocked shop
instance (1 or 2 / 4). Opponent tiles are public, so their forthcoming harvest
is subtracted before we plant into the same book.

Early capital is a **non-linear multiplier**, not a cash pile. That is why
the state machine is phased rather than running the KKT solver from turn 0:

| Phase | Turns | Policy |
| --- | --- | --- |
| BOOTSTRAP | 0–72 | 100% carrot on the starting 25 tiles; hire the cheap fib hands |
| EXPAND | 72–240 | buy land, stand up geese, plant melon that still matures |
| COMPOUND | 240–500 | full KKT water-fill + town-shop posterior + collapse pivot |
| HARVEST | 500–650 | no new long-cycle assets |
| LIQUIDATE | 650–720 | backward-induction flatten; unsold `q > 0` is `-inf` |

A 15% price drop across 12 turns sets a collapse flag and derates that crop's
`tdpu` (i.e. it must earn more per tile-day to keep its slots). That is the
maximum-expected-utility pivot.

## 4. Labour

Workers × tasks is a linear assignment over a 3-turn lookahead
(Jonker–Volgenant). Survival actions are priced at `CRITICAL`. Inventory
routing is resolved **before** the matrix:

- a worker holding an animal is committed to `PLACE`
- a worker holding wheat who is near an unfed animal `FEED`s
- a worker holding fertilizer `FERTILIZE`s a one-time crop in its window
- otherwise the nearest free worker `PICKUP`s wheat for the unfed herd

This is the difference between a farm that keeps its geese and a farm that
watches them escape because the planner thought shed wheat was feed.

## 5. Robustness

- Single file, stdlib only. No import surface on `/kaggle_simulations/agent/`.
- `agent(obs)` never raises.
- `step` is never trusted; `day * 24 + hour` is the clock.
- Turn budget 0.55 s inside a 1.0 s `actTimeout`.
- Cloud gate: syntax, import, 720-turn self-play, overage telemetry, ≥60% vs
  `starter`, ≥50% vs a cloud-only carrot-scaler. No workstation loop.

## 6. Sell-side must not fight the ramp

Premium goods keep the KKT reservation (`mu * tdpu`) so melon/milk/wool are
not walked to $1. Staples (carrot, wheat, egg) sell at a low fraction of
base. A high egg floor is how an agent produces the right asset and then
refuses to convert it to land and more geese. Cloud episodes that scored
~8k against the starter were that lock: carrot cycles with no expansion.

Buy order is hire → feed wheat → land → geese → seeds, which is the
capital-velocity order, not the unit-price order.

## 7. Dual NAV, flow occupancy, contested liquidation

Exact Bellman / Nash / 720-turn MILP is not the 1s timeout (that claim
was unmeasured). The infeasible object is the **action space**: 720
turns × workers × tiles × market. The feasible global policy is the
KKT forecast plus the state-contingent forecasts below.

1. **Both NAVs, late LOCK.** `my_nav = bank + shed + my field`.
   `opp_nav = their bank + their public field + replant flow` (shed hidden
   ⇒ lower bound). Counting only the standing plants overstates the lead
   vs a 25-tile carrot farm and fires LOCK while we are still on their
   book. LOCK starts at turn 300. It does **not** mean "stop premium":
   it means vacate books they already occupy. Eggs absorb; uncontested
   melon is how a lead is locked in. `CONTEST` takes remaining book.
2. **Opponent occupancy is a FLOW.** A 25-tile carrot farm is not 75
   units of current plants. It is `tiles × (units/cycle) × days left`
   after this cycle. Peak tiles persist across harvest gaps so a brief
   empty board does not look like a free carrot book. Capacity is
   `headroom + town drain − that flow`.
3. **Liquidation vs their dump.** Town drain makes later stages cheaper;
   opponent flow does the opposite. Imminent premium is raced.

Phase changes force a replan so a carrot BOOTSTRAP mix cannot linger into
EXPAND. A carrot-only opponent ends bootstrap at turn 48 (first cash
print) instead of 72.

## 8. Goose ramp cannot lose to the planter

Three engine-faithful failure modes print a 6k farm that still "wins"
against a weak bot:

- Planting every empty tile leaves no square for `BUILD_COOP`. Geese
  sit in the shed. Reserve empties for missing coops **before** plant.
- `1.25` wheat tiles per animal on a 25-tile farm crowds out the herd.
  Plant a thin wheat block; buy the rest (wheat absorbs).
- The market cap is 10 orders. A long sell tape must not drop
  hire / feed-wheat / land / goose. Sells still go first so the engine
  has cash; buys keep reserved slots.
- Structure count is `empty + occupied`, at most 2 new coops per turn.
  Weeds are **under-staffing**, not over-expansion. The 10-order cap
  plus `target − hires_today` (re-hire the crew every morning, explode
  fib) plus a 50-tile ceiling froze a 17% board. Fib resets daily: 4
  cheap HIREs/day reach 18 hands in a week. Pack 2 cash sells then
  HIRE so those orders land. Plants scale as `workers×4`. Land is
  NE/SW/SE at 4/8/12 hands. Milk/wool reopen; glut (inv > I0) is
  derated so eggs do not print into a crash while carrot is scarce.
  Vacate a book only when its quote is already dying.
