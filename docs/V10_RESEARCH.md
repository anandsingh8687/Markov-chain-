# v10 research log

The goal for v10 is to close the gap to the top 10. Every experiment below was
measured with `kaggle-environments==1.32.7` and 720-turn games on real ladder
seeds. "Closed loop" means both agents play live. "Ghost" means real ladder
opponents replayed from their recorded actions (see `tools/ghost_bench.py`).

## How big the gap is

Measured against the **same opponent submissions** (15 shared opponents, real
ladder games):

| | Mean margin against those opponents |
| --- | --- |
| top-10 teams | **+$21.7k** |
| v8 | +$10.3k |

The top teams are about **$11k a game stronger** than v8 against identical
opposition. In 80 downloaded top-10 games, the top teams and their opponents
got **the same price per unit** for every product. So the gap is production,
not sale timing.

What the top teams build, compared with v8's own games:
* Land: 3-4 plots, by day 7-8. v8 has 2.2, around day 9.
* Cows: 7-14. v8 has 7.4.
* Strawberries: from day 2-3. v8 starts on day 5-6.
* Tomatoes: 7 of the 10 teams grow them. v8 grows almost none.
* Cash: they reinvest everything and keep the bank near $0 into mid-season.
  v8 holds **$16k idle by day 10 and $50k by day 18**.

## v9 (live)

* v8 plus a morning-hire cash reserve, plus Herd Safe v3's cheaper opening.
* Live since 2026-09-24; **9-0 in its first games**.
* Re-validated on a fresh v8 loss: v8 lost to herens by −$27,828 on the same
  day-1 hire crunch. v9 replayed on that game wins by **+$2,852**.

## What was tried for v10, and what it measured

| Idea | Result | Verdict |
| --- | --- | --- |
| Copy top-10 production plans (their recorded actions) as new routes for v9 | Replayed through v9's layers, even on their own seed: DECEM $180.5k → $44.6k. Raw on other seeds: $29-65k, against prv_rain's $107-195k. | **rejected**: top agents are adaptive planners (their plans diverge from game to game within 1-2 days), so a frozen plan collapses |
| Annex: buy the unused plot, hire extra hands, run a ranch | Hire cost is fib(n) a day; hands 12-14 cost $144-377 a day, which eats the annex's value | **rejected** (economics) |
| Widen v9's built-in six-sheep annex (1 yarn store, wool ≥ $170-200) | Head to head against v9: 1-10-5, **−$2.8k** a game when it fires | **rejected** |
| "Patient seller": hold units sold at crash prices and sell into the recovery (v9 sells 38% of its strawberries at $22, 43% of its milk at $46, 57% of its wool at $26) | Every variant worse than v9 against prv_rain and tetsu; the rival captures the demand we leave | **rejected** |
| Foreman: our own adaptive planner, taking over from v9 at day 6 | Best $62k against prv_rain on 8 seeds; v9 scores $96k on the same seeds. It is still behind when it takes over as late as day 28 ($92.8k against $95.9k). | **in progress** |

## Foreman (`agents/foreman/`)

A from-scratch production planner that reads the full state every turn:

* **Investment by value per worker-turn**, within a daily labour budget. The
  engine's own price curve is projected forward against town demand and our
  own supply. Measured values per worker-turn: melon about $50, sheep $49,
  cow $39, strawberry and carrot $12, wheat $8.
* **Routing**: each morning, cheapest-insertion routes, with critical work
  (feeding, watering) first; one visit handles all of a tile's work; routes
  start with a wheat, fertilizer or animal pickup; idle hands steal work.
* **Fertilizer on strawberries and tomatoes**: a fertilized production event
  yields 2 units instead of 1, so up to 8 strawberries per plant.

Where it still loses to v9's routes: walking (about 130 moves a day for about
130 useful actions), herd growth (its price model is too pessimistic about the
herd), and wheat (it buys feed that the routes grow).

Benchmark: `python agents/foreman/bench.py <seeds> <opponent main.py> <switch step> [params json]`.

## Foreman, second round (2026-09-24)

These results come from an exact execution audit: the same seed, the same
opponent, and Foreman given v9's farm composition as its target.

| Output | v9 | Foreman |
| --- | --- | --- |
| wheat | 145 planted, 569 units | 91 planted, 306 units |
| carrot | 31 planted, 90 units | 0 |
| strawberry | 29 plants, 238 units (about 8 a plant) | 29 plants, 151 units (about 5 a plant; 11 died before their production ended) |
| cow / sheep / goose output | 222 / 92 / 81 | 214 / 126 / 63 |

* Animal output is at parity. The loss is in crops and labour.
* Foreman's own *planned* routes carry about 115-130 moves a day for about 130
  work actions. v9's routes carry about 110 moves for about 150 work actions,
  and they are built around the layout: animals in lines leading away from the
  shed, crops in rows beyond them, and a fixed daily circuit per hand (wheat
  pickup, then feed, care and collect along the line, then fertilize and water
  along the rows, then a midday delivery for same-day sales).
* Changes tried, all within noise of the best score ($62k against v9's $96k on
  8 seeds):
  * smart watering (water only when a plant would die or when the water adds
    yield)
  * evening rescue replans
  * splitting hands into ranchers and croppers (worse: $53k)
  * 2-opt and relocate route search
  * v9's composition given as a blueprint

**Conclusion.** A generic task-dispatch planner does not reach the tape's
execution quality. The next Foreman design has to copy the tape's structure:
lay the farm out for circuits (animal lines, crop rows) and give each hand a
fixed daily circuit, then choose investments within that structure.

## v9 on the ladder (2026-09-24)

v9 is 47-14 (77%), rated 2277.2. v8 finished 111-33 at 2255.9.

All 14 v9 losses were downloaded and replayed with our agent in its seat. **None
is a hire failure**, so the v9 fix held. What the opponents sold that we did not:

| Product | Effect over the 14 losses | Where it happens |
| --- | --- | --- |
| Tomato (volume) | −$27.8k | Pizza shop and farmers market layouts. One opponent sold 80 at $168 while we sold none; another sold 190 |
| Strawberry (price) | −$15.0k | Mostly route-105 layouts, where the opponent sells before the price drops |
| Carrot (volume) | −$11.9k | Pet cafe and farmers market layouts |

None of the 41 route tapes plants a tomato. The only tomatoes v9 grows come from
the day-18 "V219" annex (buy the SE plot, grow 10 tomatoes for days 26-29). It
only fires when **3 or more** of the unlocked shops buy tomatoes.

## Tomatoes are the untapped market

Each shop drains 1 unit of each of its products every 4 turns, which is 6 a day,
and the town center drains 1 a day. Tomato prices use a "hinge" curve that stays
calm until the unmet demand passes 200 units and then climbs fast. Nobody in
v9's games sells tomatoes, so the unmet demand keeps growing:

| Game (v9 vs prv_rain) | Day 18 | Day 24 | Day 27 | Day 29 |
| --- | --- | --- | --- | --- |
| 923533578 | $75 (126 short) | $89 (222) | $123 (279) | $164 (317) |
| 1892559107 | $77 (144) | $96 (240) | $161 (315) | $234 (365) |
| 424470723 | $77 (144) | $138 (294) | $205 (347) | $179 (329) |

Selling the whole backlog of 330 units would bring in about $30k. Since shops are
drawn with replacement, about 90% of games unlock a pizza shop or a farmers
market at some point.

The per-tile comparison is less one-sided than the prices suggest. A watered
wheat plant gives 4-6 units every 3-4 days (about $40 each, and v9 sells about
750 wheat a game). An unfertilized tomato gives 4 units over 12 days. A tomato
therefore only beats wheat on the same tile when it is fertilized (8 units) and
sells for $100 or more. That points to the late-game annex (days 18-29), not a
general wheat-to-tomato swap.

### Loosening the tomato annex gate: rejected

The annex gate counts pizza shops and farmers markets among the shops unlocked
by day 18. v9 fires the annex at 3 or more. Lower thresholds were tested, head
to head:

| Gate | Seeds where it changes the game | Result |
| --- | --- | --- |
| 1 or more | 6 (adapt2 seeds, 3 opponents each) | −$566 a game; 5 of the 6 seeds got worse |
| 2 or more | 17 (adapt2 seeds) | +$371 a game, within noise |
| 2 or more | **49 fresh seeds** | **−$325 a game against v9 (6-27)**; against prv_rain, wins fell from 46 to 23 |

With only two tomato-buying shops, the $4,000 plot plus the daily crew costs more
than ten tomatoes earn. The 3-shop gate stays.

**A benchmarking warning.** Any change after day 18 alters the weed RNG, and so
which shops unlock later. Both banks then move by ±$2-4k for reasons unrelated
to the change. A late-game layer needs 40 or more seeds on which it actually
fires before a result means anything.

## Adaptive routes: the layout table does not generalize

The router picks one of 41 route tapes at turn 144 from the first two shops. To
test whether a better table exists, 60 seeds × 3 opponents were played with the
default route and with 6 alternative routes forced from turn 144: 180 games plus
1002 alternatives.

* A per-game oracle over the alternatives would flip 14 of 40 losses. That is the
  headroom.
* Choosing the best route per layout, and testing it on held-out seeds (leave one
  seed out), scores **−$45 to −$215 a game**, depending on how strict the choice
  is. Results for one layout differ from seed to seed. That is because shops 3-8,
  which arrive after turn 144, matter as much as the first two, and the layout
  itself depends on both players' actions through the shared weed RNG.
* The earlier "best alternative per layout" finding, for example 105 → 103 for
  bakery + ice cream, came from a single seed per layout. It was overfit.

**Verdict:** the existing router is already about as good as any static
layout-to-route table. Adapting further needs information that arrives after
turn 144, which a fixed tape cannot use.

## The uploaded paper (game-theoretic DEA)

Input-oriented DEA with variable returns to scale, applied to downloaded ladder
games. Each farm-game is one unit. Inputs: wages, land, animals, seeds, and
bought feed and fertilizer. Output: sales revenue.

* v8's efficiency is 0.98 and the top-10 teams' is 0.94.
* So the gap is **scale, not efficiency**: the top teams use more inputs, and use
  them slightly less efficiently.

The paper's payoff-matrix view led to the route-by-layout experiment above. Its
metaheuristics and L-BFGS-B solver do not apply to our noisy, simulation-only
payoffs.

## Next

1. Keep the empirical loop that produced v9: download each new ladder loss and
   fix any failure mode it shows. v9's fix is the only change so far that turned
   large losses into wins.
2. Foreman: get to parity with v9's routes from day 6, then add early reinvestment
   (the third plot, a bigger herd). A planner with v9's efficiency plus the top
   teams' investment timing is the route to +$11k a game.
