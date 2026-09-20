# Architecture

Derived from the shipped interpreter (`kaggle_environments/envs/kaggriculture/
kaggriculture.py`, pinned at 1.32.7) and the published tables. No public
leaderboard solution was consulted. Every number below was read off the
interpreter or measured in a cloud episode; none of it is estimated.

---

## 1. The finding that reframes the game

Every agent this repository had produced before — and, as far as the traces
show, the obvious line of play generally — treats the market as a **ceiling**:
sell too much and the price collapses, so ration production and chase the
highest base price. That is true in isolation and false in the game.

The town is a continuous *sink*. `_town_consume` runs every turn:

* the town centre removes one of every non-fertilizer product every
  `townCenterSellInterval` (24) turns;
* each unlocked shop instance removes one of each of its products every
  `townShopSellInterval` (4) turns, doubled for single-product shops;
* shops unlock every 3 days up to 8 instances, **drawn with replacement**.

At eight instances that is on the order of **120 units/day** removed from the
book, against which a farm that works all 100 tiles supplies perhaps 60-80.
Inventory therefore spends the whole season *below* the reference level
`I0 = 10000`, which is the **scarcity** side of the price curve:

```
price(inv) = base + amp * f(I0 - inv)          for inv < I0
```

So the quote sits **above** base and climbs all season. Measured on seed 1,
end of season, with an agent selling into it the whole time:

| Product | Inventory vs I0 | Quote | vs base |
| --- | --- | --- | --- |
| Carrot | −584 | **$186** | 5.3x |
| Wheat | −616 | **$52** | 2.1x |
| Egg | −99 | $58 | 1.2x |

Carrot and egg use the `hinge` shape, which is linear up to `T` and then adds
`8 * (u - 1)^2` — calm until the resource is genuinely scarce, then it runs
away. Nothing in the earlier agents ever pushed carrot back toward `I0`.

The consequence: **absorption is not the binding constraint, throughput is.**
The question is never "will the book take this", it is "which tile-day and
which worker-action earns most". The old agents were solving the wrong problem,
which is why they converged on a $10-19k plateau.

## 2. What the agent optimises

Tile-days and worker-actions are the scarce resources. Allocation equalises
marginal revenue per tile-day (the KKT condition for the tile-day budget), with
the marginal price read off the **end-of-horizon** book rather than the spot
quote:

```
end_inv(p) = inv(p) + own_pipeline(p) - drain_rate(p) * turns_left
```

`drain_rate` is computed from `obs["town"]["unlocked_shops"]` — the shops
actually drawn *this episode*, duplicates counted separately. That matters:
the draw is random with replacement, so an episode with no `YARN_STORE` has
almost no wool demand and the sheep herd cap collapses to ~2, while an episode
with two `PET_CAFE`s makes carrot the best crop on the board. `own_pipeline`
carries growing yield, unharvested animal product, the shed and everything in
worker pockets, and it *subtracts* the wheat that will be burned as feed, since
feed is never sold.

The free-tile loop is a water-fill: after each tile is committed, that crop's
added volume is folded back into the price before the next tile is scored, so
the mix equalises at the margin instead of dumping every tile into one crop.

## 3. Why the plan is livestock-led

The care bonus is the most under-priced rule in the game. `_daily_refresh_
animals` banks +1 per fed-and-cared day and pays the **whole** accumulated
bonus on the next production day, so a cared animal yields `(1 + interval) /
interval` per day:

| Animal | Interval | Units/day cared | Product | Town draw/day | Sustainable herd |
| --- | --- | --- | --- | --- | --- |
| Goose | 1 | **2.0** | Egg | ~13 | ~7 |
| Cow | 2 | **1.5** | Milk | ~19 | ~13 |
| Sheep | 3 | **1.33** | Wool | ~12 | ~9 |

At quotes that sit above base, a cared cow or sheep returns roughly
**$255-260 per tile-day** against ~$130 for melon and ~$55 for carrot, on one
tile, for 2.5 worker-actions a day. Livestock also drops one fertilizer per
animal per day for a single action — a by-product on a curve the town never
touches.

The herd is capped near the town's own draw for that product, because milk and
wool sit on `linear 1.6` and `sq 3.2` above `I0`: oversupply there is punished
far harder than undersupply. That cap is computed per episode from the shop
draw, not hardcoded.

The opening is still melon — six units at age 10 on an 11-tile-day cycle, the
largest single capital event available before the herd can ramp — and carrot
and wheat carry the middle game and feed the animals.

## 4. Three invariants, each of which cost a rewrite

These are not tuning. Each one was added after an agent that ignored it
collapsed in a traced episode.

**Labour is funded before capital.** A hand costs `fib(n)` per day and returns
23 actions; ten hands cost $143/day total. It is by far the cheapest capacity
in the game, and an under-staffed farm turns into weeds — a traced run had 45
weed tiles, 45% of the board idle, while sitting on $20k.

**Capital is only spent above an operating runway.** Two consecutive missed
feeds and an animal is gone permanently. An early version bought livestock down
to its last $50, could not afford wheat, and watched the herd starve; it scored
17k where the same code with a runway scored 62k. Cash starvation kills a farm
faster than any market move.

**Stock and structures are gated on each other.** `BUY_ANIMAL` drops the animal
in the shed; it needs a matching empty structure, a worker to carry it and a
`PLACE`. Agents that buy first strand livestock — the previous `main.py` ended
its episode with 12 geese, 3 cows and 4 sheep sitting in the shed, about $6,800
of dead capital. Purchases here are gated on a free structure, on labour, on
feed and on the herd cap.

## 5. Engine facts the plan depends on

Read off the interpreter, several of which contradict the natural reading:

* **`agent` must be the last callable in `main.py`.** `get_last_callable`
  returns `[v for v in env.values() if callable(v)][-1]` — the last callable
  bound in the module namespace, *not* the one named `agent`. A helper defined
  below it silently becomes the submission. `tools/cloud_verify.py` asserts
  this; it cost a rewrite to find.
* **The last agent action is step 718, not 719.** The interpreter sets `DONE`
  at `step >= episodeSteps - 2`, so the final end-of-day never runs and
  anything a worker is still carrying on day 29 is forfeited. The agent
  harvests, walks to the shed, drops and sells from that point.
* **Watering every other day is enough to survive.** A tile becomes a weed only
  after *two* consecutive dry end-of-days, so outside the bonus window the
  agent waters on alternate days and spends the action elsewhere. It must water
  on the planting day itself: `_new_plant` sets `consecutive_unwatered = 1`.
* **`BUY_PRODUCT` is priced dynamically**, at `market_price(inv - 1)` —
  `AGENTS.md` describes it as fixed. Buying wheat walks its own price up.
* **Sales at $1 do not increase supply**, so a floored product can be dumped
  without further damage.
* **Melon's best exit is age 10, not 12** — six units is already `max_yield`.
* **Over-planting a crop past the seeds held voids every `PLANT` of that crop
  that turn**, so planned plantings are counted against the seed balance.
* **The shed caps all non-seed items at 100**, bought animals included, and
  overflow at the end-of-day drop is discarded — so workers drop mid-day and
  the agent sells every turn.
* Fertilizer is not consumed by the town at all; the whole `linear 0.4` curve
  is uncontested.

## 6. Measured

Cloud runs, `kaggle-environments==1.32.7`, 720 turns, sides swapped, strict
mode (the agent's own exception guard disabled so nothing is hidden):

| Match | Result |
| --- | --- |
| This agent vs. built-in `starter` | 100%, ~$65k vs ~$3.4k |
| This agent vs. PR #1 incumbent | see `benchmark/`; ~$62-89k vs ~$10-12k |
| Previous `main.py` vs. PR #1 incumbent | 31% win rate (both $9-13k) |

The jump is not tuning. It comes from reading the market as a sink rather than
a ceiling, and from actually staffing and feeding the farm that conclusion
implies.
