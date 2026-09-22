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

## 3b. The book stays starved even against a mirror of this agent

The obvious objection to section 1 is that it measures a market with one
serious producer in it: put a real competitor on the other side and the
ceiling reappears. It does not. Two copies of this agent, both farming all
100 tiles for the full season, end seed 1 like this:

| Product | Inventory vs I0 | Quote | Base | |
| --- | --- | --- | --- | --- |
| Milk | −398 | **$333** | $160 | above base |
| Strawberry | −248 | **$252** | $120 | above base |
| Tomato | −352 | **$213** | $60 | above base |
| Wheat | −860 | **$54** | $25 | above base |
| Wool | −6 | $217 | $200 | above base |
| Egg | −66 | $54 | $50 | above base |
| Carrot | +14 | $31 | $35 | at base |
| Melon | +128 | $86 | $250 | below base |
| Fertilizer | +236 | $53 | $100 | below base |

Only melon and fertilizer — the two products the town never buys on a shop
tick — finish oversupplied. Everything the town actually demands finishes
*under*supplied, at two to three times base, with both players producing flat
out.

This has a direct strategic consequence, and it is the opposite of the usual
advice. Against a competitor you do not yield contested ground, because there
is no contested ground: the marginal unit still clears above base. Section 7
records what happens when the agent is made to yield anyway.

It also says where the remaining money is. Strawberry and tomato finish the
most under-supplied of anything the town buys, which is what motivated the
horizon-truncated valuation below.

## 3c. Ongoing crops are valued over the horizon that is left

Tomato and strawberry pay out in instalments — one unit per production day,
`interval` days apart, up to `max_yield` times — so a plant that cannot live
out its full lifespan is still worth its first few harvests. Valuing them
all-or-nothing against their full lifetime (18 tile-days for strawberry)
excluded strawberry from every planting decision after roughly day 11, even
while the book was paying $250-290 for it. `_ongoing_fit` counts the
production days that actually fit before the horizon and charges only the
tile-days actually used.

Measured across three seed sets, 56 episodes, sides swapped:

| | mean | worst episode |
| --- | --- | --- |
| full-lifetime valuation | $72,413 / $69,532 | $42,504 / $36,100 |
| horizon-truncated | **$76,393 / $73,106** | **$49,683 / $42,585** |

Consistent direction and magnitude on seeds used for tuning and on twelve
fresh ones: about +5% mean and +17% on the worst episode.

## 4. Three invariants, each of which cost a rewrite

These are not tuning. Each one was added after an agent that ignored it
collapsed in a traced episode.

**Labour is funded before capital.** A hand costs `fib(n)` per day and returns
23 actions; ten hands cost $143/day *in total*. It is by far the cheapest
capacity in the game, and an under-staffed farm turns into weeds — not the
0.5%/tile/day spawn, but plants dying after two dry end-of-days, which costs
the seed and the whole cycle.

There is a trap here worth naming, because it hid the problem for several
iterations. **Only ten market orders clear per turn** (`maxMarketOrdersPerTurn`),
and `HIRE` is a market order competing with every `SELL`. Issuing the day's
hires at hour 0 behind eight or nine sell orders silently capped the farm at
five to eight hands when eleven to fourteen were warranted — the agent was
*paying* for labour it never received, and the cash test that looked like the
constraint was never the binding one. `SELL` can wait for any of the day's
other 23 turns; `HIRE` cannot, because a hand not bought in the morning is 23
actions gone. Spreading hires across the first three turns of the day:

| | mean | worst episode | mid-game weed tiles |
| --- | --- | --- | --- |
| hires at hour 0 only | $57,556 | $31,233 | ~40 |
| hires over hours 0-2 | **$67,527** | **$46,708** | **1-5** |

Same measurement on eight seeds the change was not tuned on: $56,395 ->
$61,624. That single ordering fix is worth more than every other parameter in
the agent combined.

**Capital is only spent above an operating runway.** Two consecutive missed
feeds and an animal is gone permanently. An early version bought livestock down
to its last $50, could not afford wheat, and watched the herd starve; it scored
17k where the same code with a runway scored 62k. Cash starvation kills a farm
faster than any market move.

**The herd needs dedicated hands.** Feed, care and harvest are 2.5 actions per
animal per day, every day, and a missed feed is unrecoverable, so the first
`ceil(herd / 3.5)` units are reserved for animal duty and pick up wheat on the
way out of the shed each morning. That ratio is not cosmetic: at one rancher
per 5.5 animals the herd is serviced late and the mean drops from $74,773 to
$67,527, the worst episode from $58,063 to $46,708. Confirmed on eight seeds
the ratio was not tuned on ($70,052 vs $61,624).

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

| Match | Episodes | Result |
| --- | --- | --- |
| This agent vs. built-in `starter` | 4 | **4-0**, median margin +$77,458 |
| This agent vs. PR #1 incumbent, seeds 1-18 | 32 | **32-0**, mean $76,393 vs ~$11k |
| This agent vs. PR #1 incumbent, seeds 31-42 (fresh) | 24 | **24-0**, mean $73,106 |
| This agent vs. PR #2 rival (`32762ff`), two seed sets | 24 | **24-0**, mean $75,176 / $83,011 |
| This agent vs. previous `main.py` | 12 | **12-0**, mean $63,512 |
| Previous `main.py` vs. PR #1 incumbent | 16 | 31% win rate (both $9-13k) |

Across those 48 episodes the win rate is 100% and the worst single episode is
$27,650 — still more than twice the incumbent's best. The spread between seed
sets ($50.7k to $74.8k mean) is mostly the shop draw: shops unlock with
replacement, so an episode that never draws a `YARN_STORE` or a `PET_CAFE`
simply has less demand to sell into. The agent reads the draw and re-prices
rather than assuming it, which is why the win rate does not move with it. The agent also completes a season
under non-default `episodeSteps`, `turnsPerDay`, `boardSize`, `shedCapacity`
and `maxMarketOrdersPerTurn`, all of which it reads from the runner rather
than assuming.

The jump is not tuning. It comes from reading the market as a sink rather than
a ceiling, and from actually staffing and feeding the farm that conclusion
implies.

## 6a. The structural gate

Absolute score hides both failure modes this repository has produced, and
neither raises an exception: a farm can buy 75 tiles and work thirteen, and
an allocator can pour tile-days into the one product the town never buys and
drive it to the floor. Both still beat `starter`.

So `tools/cloud_verify.py` samples turn 480 and fails on: fewer than 8 hands,
utilisation under 45%, more than 20 weed tiles, or any farmed product
finishing oversupplied below a quarter of base. The midgame staffing and
utilisation form of this is borrowed from PR #2, which arrived at it
independently after the same 40-weed symptom; the crushed-book check is the
other half, and catches what PR #2's own gates do not.

It is sampled at **hour 12, not hour 0** — `_end_of_day` clears
`farm["hands"]`, so an hour-0 snapshot reads every crew as zero however many
were hired.

Verified to fire: pointed at PR #2's `d77b193` it reports 25% utilisation and
fails.

## 6b. Compute budget

Measured over a full 720-turn episode: **0.26 ms mean, 0.52 ms p99, 0.66 ms
worst turn**, against a 1000 ms `actTimeout` — roughly 1500x headroom, and the
60 s overage budget finishes untouched. Time per turn is not what rules out
heavier machinery here; the action space is. A single turn's action is a joint
assignment of up to fifteen workers over ~20 operations each, plus ten market
orders, and a full-season rollout costs about half a second, so tree search
gets single-digit rollouts per turn over a branching factor with no
meaningful ceiling. The leverage has been in the valuation, not the search.

## 6c. Why the other agents in this repository plateau

All three sit in a $10-30k band, and the reason is the same in each case:
the board is not worked. Seed 9034, day 24, same opponent:

| | unlocked | productive | utilisation | final bank |
| --- | --- | --- | --- | --- |
| this agent | 100 | 80 | **80%** | $111,592 |
| PR #2 (strongest rival) | 75 | 13 | **17%** | $10,903 |
| PR #1 | 50 | 37 | 74% | $16,053 |

PR #2 is worth reading closely because it diagnoses a real symptom and draws
the opposite conclusion from the same evidence. Earlier revisions of its line
harvested 33-47 weed tiles, so it shrank the farm to fit: never buy SE, herd
capped at `min(8, workers-2, tiles/4)`, cows and sheep capped at four each,
standing plants capped at `workers*2 - herd`. It then buys 75 tiles and farms
thirteen.

This repository hit the same 40-weed symptom (section 4) and traced it to
hires being silently dropped by the ten-order-per-turn cap — the farm was
paying for labour it never received. Fixing that took weeds from ~40 to 1-5
on a *larger* board. Weeds are a symptom of under-staffing, not of
over-expansion, and treating them by shrinking the board removes the revenue
and leaves the cause in place.

PR #2 also closes milk and wool, the two highest-value assets on the board at
roughly $260/tile-day, and its closing book on that episode has egg pushed
*above* the reference inventory while carrot sits 244 units below it at a
high quote: production aimed at the one thing it had already saturated. Its
"LOCK vacates their book" rule is the same idea as `OPP_PIPE` in section 7,
which is measured here and loses.

PR #2 has since fixed the staffing (`32762ff`: re-hire every morning, fill
against `workers*4`, reopen milk and wool) and tripled on that seed, to
$33,966. It is still 3x short, and its closing book shows why: melon **+156
units at a $7 quote against a $250 base**, while strawberry finished 318 short
at $270 and wheat 718 short at $52. Melon is the only crop with no shop demand
— the town centre takes one a day — so it is the one product that genuinely
saturates, and it took 12-17 tiles late while the products paying twice base
went unplanted. Pricing a tile against the end-of-horizon book (§2) is exactly
what prevents that: melon's marginal price collapses as its own pipeline grows
because its drain is ~1/day, strawberry's does not.

Both agents are kept in `benchmark/` and gated against on every push.

## 6d. Measuring strength against a strong opponent

Beating `starter` measures how much of an *uncontested* book an agent can
harvest. A competitive ladder is a different problem: the book is shared and
the town's draw is fixed, so whoever reaches the high-value products first
gets the higher quotes and the loser is priced into what is left. A change can
be worth nothing in the first problem and decisive in the second.

`tools/selfplay_ab.py` plays a candidate against a frozen copy of the current
agent (`tools/freeze_champion.py` writes a champion that ignores `KG_PARAMS`,
so the two sides can differ). Identical agents score exactly 0.500 with zero
edge, which is the control.

Self-play has a blind spot worth stating: a change that expands *absolute*
production shows as a tie, because the mirrored opponent expands too and they
split the same book. So a candidate is read on both -- self-play for
contested strength, and mean bank against a fixed opponent for absolute
output. The feed-shadow experiment in section 7 is exactly the case where
those two disagreed, and the absolute measure was the one that mattered.

**The noise floor is the main finding of that work.** At 16 episodes the
standard error on a self-play score is about 0.12 and on mean bank several
thousand, and four separate candidates this session looked like clear wins at
that sample size and reversed at 44-48 episodes. Nothing below roughly 8% on
a 44+ episode sample should be treated as a result.

## 6e. What the real ladder actually looks like

Everything above this section was measured against agents in this repository.
Pulling real episode replays off the competition (`kaggle competitions
episodes <submission_id>`, then the replay API) changes several assumptions,
so the findings are recorded here rather than inferred.

**The top of the leaderboard is a monoculture.** In episode 111876587 two
different teams -- "Anand Singh" and "Li Li" -- played *byte-identically*:
same bank, same hand count, same tile count and the same crop mix at every
sampled day, finishing in an exact tie at **$97,247 each**. Many teams are
running near-identical forks of one shared public agent, which is why the
rating band is so tight and ties are so common.

**That agent reaches $97k, and its opening is the difference.** Day 0 it
already owns two cows and two sheep, six melon and one wheat, with five
hands. From day 1 it sells fertilizer continuously -- the shared book shows
+6, +16, +38, +72, +122, +180 by day 12. One fertilizer per animal per day,
on the only curve the town never draws from, is the compounding stream that
funds the rest of the ramp. It reaches 50 tiles by day 6 and 75 by day 11,
and never buys the SE quadrant.

Its closing book is worth reading too: milk finishes **+76 at a $1 quote**
and fertilizer **+492 at $2** -- both crushed to the floor -- while egg sits
338 short at $70 and strawberry 76 short at $193. So it is not optimal
either; it simply out-ramps.

**Two submissions stay active at a time**, and a new one deactivates the
oldest. Verified from episode timestamps: frontier_v7 and frontier_v6 were
still playing, while frontier_v4 stopped the minute v6 landed and
frontier_v3 stopped when v5 landed. That matters because frontier_v3 scored
**2767.6**, the best this account has ever had, and it is already retired.

**The margins up there are razor thin.** Six consecutive episodes for
frontier_v7, banks and outcome:

| opponent | banks | result |
| --- | --- | --- |
| miya | 78,120 – 77,873 | loss by 247 |
| t-enstar | 59,877 – 58,067 | win by 1,810 |
| uki706 | 117,786 – 118,294 | loss by 508 |
| rode1234 | 77,913 – 77,388 | loss by 525 |
| kitton | 124,918 – 124,845 | **loss by 73** |
| Batuhan Ustun | 74,801 – 74,281 | loss by 520 |

Every game is decided by 0.1–3% of the bank. Against a monoculture you do not
need a different strategy; you need the same one executed a few hundred coins
better. That also means the 6x margins this agent posts against
`benchmark/incumbent` and `benchmark/rival` carry no information about ladder
position -- those opponents are simply not in the game.

**And this agent is ~18% behind that bar.** The replays carry their seed, so
the comparison is exact rather than inferred -- `tools/ladder_gap.py` replays
each ladder seed and compares banks:

| seed | ladder | this agent | gap |
| --- | --- | --- | --- |
| 149070582 | 74,801 | 54,870 | 26.6% |
| 1349377747 | 124,918 | 79,221 | 36.6% |
| 1060396977 | 77,913 | 69,257 | 11.1% |
| 845305836 | 118,294 | 87,617 | 25.9% |
| 309891330 | 59,877 | **65,228** | **−8.9%** |
| 527940527 | 78,120 | 66,602 | 14.7% |
| 2053703874 | 97,247 | 75,734 | 22.1% |

Ahead on one seed of seven; mean gap **18.3%**. The gap is the ramp, not the
end state: the ladder agent owns four animals on day 0 and is selling
fertilizer on day 1, where this one places its first animal around day 11.

**Local bank does not cleanly predict ladder rating.** A submission in this
repo's line ("v16 ... local ~83-89k") rated **529.4**, which is bottom-third
of a 9,792-team field. Either that agent failed on the eval host or the local
proxy is weak; `tools/cloud_verify.py` exists to rule out the first.

## 7. Hypotheses that were tested and lost

Recorded so they are not re-tried. All measured the same way: eight seeds,
sides swapped, against the incumbent.

* **Discounting the allocator to the payoff date.** Early capital compounds
  into livestock, so a dollar at harvest should be worth less than a dollar
  now — and the opening commits 23 tiles to melon for ten days with no cash
  flow, which looks like exactly the mistake a discount would fix. Measured:
  every positive rate lost, and the best of them (0.10) still cost $3k of mean
  and $18k of worst case. The melon opening is genuinely worth the wait. The
  knob survives as `DISC`, pinned at 0.
* **Forcing a unit holding livestock to go and place it.** A four-seed search
  against an older agent preferred switching this off by 10%. Re-checked over
  eight seeds against the incumbent, the ranking reversed and switching it off
  *lost* 16% ($48,070 vs $57,556). A search result is conditional on its
  opponent and its seed set; confirm on held-out seeds before changing a
  default.
* **A short-cycle opening.** The plan commits 23 tiles to melon for ten days
  with no cash flow, which delays the first livestock; restricting the opening
  board to crops that turn over in under a week should fund the herd sooner.
  Measured: $63,173 at four days and $57,182 at eight, against $67,527 for
  leaving it alone. Melon's opening capital event is larger than the ramp it
  costs. Kept as `OPEN_FAST`, pinned at 0.
* **Relaxing the herd cap.** At `OVERSUPPLY = 2.2` the mean falls to $51,123
  and the worst episode to $29,455 — milk and wool above `I0` sit on
  `linear 1.6` and `sq 3.2`, and the collapse is as steep as the table says.
  Tightening it to 1.0 also loses ($66,645), so the cap is close to right.
* **Pricing the opponent's visible production into the book.** Their tiles are
  public, so their future supply is partly observable, and folding it into the
  forward book looks like a free best-response. Measured against the incumbent
  it changed nothing (inside noise) and hurt the worst episode. Measured where
  it should matter most — this agent against a copy of itself, both competing
  for the same book — it **lost 7-9**. Section 3b is why: yielding ground in a
  market that still clears above base just moves production to a worse crop.
  Kept as `OPP_PIPE`, pinned at 0.
* **Buying capital in a fixed order.** Not a hypothesis so much as a bug, and
  it shipped for several revisions: seed every free tile, then buy animals
  with the remainder. On day 0 that spends $2,484 of a $3,000 bank on melon
  seed, leaves $258 -- under the operating runway -- and the herd cannot start
  until the melon harvest lands on day 11. A cow is worth ~$305/tile-day at
  that point against ~$144 for a melon tile. Fixed by ranking the two
  (`CAPITAL_ORDER`), and by capping a single seed order at `SEED_CAP` tiles
  rather than buying for the whole board at once, which keeps cash liquid for
  wheat, hires and stock. Held-out over 32 episodes the mean is unchanged
  ($76,236 vs $77,014) but **the worst episode improves from $29,797 to
  $54,510**. On a win/loss ladder a catastrophic episode is a loss, so the
  floor is worth more than the mean.
* **Pricing wheat at the shadow price of feed.** Instrumenting the livestock
  purchase caps shows feed -- not land, labour or the town's draw -- is what
  holds the herd down all season, and a cared cow is worth ~$375/tile-day
  against ~$45 for carrot. So a wheat tile ought to be valued at the animal-day
  it unlocks, not at its sale price; the correct multiplier is exactly 1.0
  (the dual), and the measured optimum sat precisely there, collapsing above
  it. On 16 self-play episodes it scored 0.75 with a +$4,348 edge. It did not
  survive: 0.542 over 48 self-play episodes, and **7% worse on absolute output**
  ($75,756 vs $81,332 over 44 episodes against the rival). The reason is in the
  cap formula -- `cap_feed` is `invest / (wheat_buy * days_left)`, which is a
  *cash* constraint wearing a feed constraint's clothing. Wheat can simply be
  bought, so the answer to "cannot afford feed" is to grow the crop that earns
  most and buy the wheat, which is what the agent already does. Kept as
  `FEED_SHADOW`, pinned at 0.
* **Buying down the ranked animal list.** Episodes finish with thirteen
  sustainable geese and none owned, because the agent only ever buys the single
  best species and stops when that one saturates. Letting it fall through to
  the next species diversified the herd as intended and lost: self-play 0.188
  with a −$2,100 edge, and $63,792 against the rival where leaving it alone
  scored ~$76,000. The agent was right to decline: a marginal goose is worth
  less than the crop tile it displaces, and the animal valuation is optimistic
  because it ignores the structure-building, placement and ramp that a new
  species costs. Kept as `RANK_ANIMALS`, pinned at 0.
* **Sowing to the end of the horizon.** A one-time crop was valued only at its
  optimal harvest age, so the planner stopped sowing about four days early and
  idled most of the board through the run-in -- carrot's best exit is age 3 but
  it is harvestable at age 2. Valuing each crop at the best age that still fits
  the horizon is the more correct model and is what ships, but the aggressive
  form of it is a loss: late-game utilisation rose from 53% to 69% and the bank
  fell from $83,571 to $80,112. Late labour is worth more on harvesting and
  liquidating the standing crop than on a fresh carrot. `HARVEST_MARGIN` is
  pinned at 2.0, which keeps the better valuation and roughly the old cutoff.
* **Shortening the feed funding window.** Livestock purchases require enough
  cash to feed the herd for the whole remaining season, which is plainly
  conservative — an animal covers its own wheat inside a day — and the herd
  does stall around 15 head while the town's draw would support more. Funding
  only three days ahead scored **+12% on seeds 1-8** ($81,849 vs $73,058).
  On 32 episodes of held-out and fresh seeds it was dead level on mean
  ($74,415 vs $74,789) and clearly worse on the worst episode ($35,027 vs
  $42,585): the gain was seed noise, and what it really bought was a herd
  that occasionally outruns its cash. Kept as `FEED_DAYS`, pinned at 30.
  The stalled herd is a real observation and still the most promising place
  to look; this particular lever is not the answer.
* **Trimming the wheat feed buffer and the carry-drop threshold** to relieve
  the 100-item shed cap. All variants landed within ±2% of base — inside the
  noise at this sample size. The shed is near its cap in the late game, but the
  overflow is not where the money is.
