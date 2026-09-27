# v17 plan: from a better seller to a bigger, demand-matched economy

## Where we stand (2026-09-27)

* Leaderboard: #1 3102, #10 about 2890, #100 2629. v14 2460 (118 games).
* By opponent band, v14 is 35-8 below 2400, 20-16 at 2400-2500, 12-17 at
  2500-2600 and **0-10 at 2600+** (mean −$9k).
* v11-v14 all improved *selling order and small trades* in mirror matches
  against copies of the public route tape. That band tops out around 2500-2600.
  The 2600+ teams are not tape copies, and they beat us on economy size.

## What the top-10 teams do (138 player-games at 2750+ in the replay pack)

* **Land:**
  * north-east on day 6, south-west on day 9, south-east on day 9-10.6
    (DSM, Vadim, DECEM, Mother-Goose, mtmr);
  * the land order is fixed by the engine (NE $1,000, SW $2,000, SE $4,000);
  * the tape buys NE on day 6 and SW on day 11, and never SE.
* **Revenue** (`research/tools/v12/econ.py`, DSM vs Majkel, game 112777759):
  * **wool $65.4k** (313 units at $209), milk $28k, strawberries $27k,
    melons $13k, fertilizer $13k, wheat $13k, tomatoes $9k;
  * our v14 in a typical game: strawberries $35k, milk $20k, fertilizer $18k,
    wheat $17k, melons $17k, **wool $9k**.
* **Labour goes to animals.** Worker actions a game (DSM against us):
  * FEED 476 / 334, CARE 483 / 404, COLLECT_FERTILIZER 570 / 368,
    FERTILIZE 252 / 118, BUILD_PASTURE 27 / 14;
  * PASS 284 / 546: we leave nearly twice as much labour idle.

## The engine economics behind it

* Every animal needs FEED (1 wheat) every day or it escapes after 2 days.
  CARE on a fed day adds +1 to the next production. Every animal also offers
  one COLLECT_FERTILIZER a day.
* With full care:

  | Animal | Output | Value a day |
  | --- | --- | --- |
  | Sheep | 4 wool / 3 days | ~$267 + $44 fertilizer |
  | Cow | 3 milk / 2 days | ~$240 + $44 |
  | Goose | 2 eggs / day | ~$100 + $44 |

  Each costs about 3-4 worker actions a day. That is roughly **$100 per worker
  action, against about $23 for wheat.**
* **Demand caps everything.** Every 4 turns each unlocked shop removes 1 unit of
  each product it buys (2 for single-product shops: YARN_STORE for wool,
  PET_CAFE for carrots). The town centre removes 1 of each product a day.
  * Demand is therefore 6 a day per multi-product shop, 12 per single-product
    shop, plus 1 a day from the town centre.
  * Selling above demand pushes inventory past I0, and the glut curves are
    steep: wool sq×3.2, milk and strawberries linear×1.6. Selling below demand
    earns a scarcity premium.
  * Both players sell into the same books.
* Hires cost fib(n) for the n-th of the day. Hands 1-10 cost $143 a day in
  total; hands 11-14 cost $89, $144, $233 and $377 each. **Labour efficiency
  decides the size of the farm.** DSM runs four quadrants on about 11 hands.

## v17 design: demand-matched herd expansion (HERD)

Keep v14 (tape + all layers). Add a layer that:

1. **Estimates demand and supply per animal product** (wool, milk, eggs) every
   day:
   * demand from the unlocked shops, as above;
   * our supply from our herd;
   * the rival's supply from the recovered flow (`_FX_STATE[...]['flow']`,
     already computed).
2. **Buys the south-east quadrant early** (day ~10-12, cash permitting) and
   builds pastures and coops there. It buys the animal with the highest
   marginal value (price response × output − feed − labour) while that value is
   positive: sheep in yarn towns, cows where milk demand is unmet, geese for
   eggs.
3. **Runs an animal crew:**
   * FEED, CARE, COLLECT_FERTILIZER and HARVEST, on a fixed short tour of
     adjacent pasture tiles next to the shed;
   * idle tape hands first (PASS turns), then extra hires only while the
     marginal hire cost stays below the herd's marginal value;
   * feed is PICKUP wheat from the shed, bought with BUY_PRODUCT WHEAT
     (a deep book, log glut).
4. **Sells** through MDX-style peak sales, capped at the day's demand.

Evaluation, in order:
* replays against tape copies (the 72/85/118 live sets, 98, 127, `eps_hi`;
  these copies do not collapse);
* closed-loop games against v14 and public agents (absolute bank matters: the
  top teams bank $110-140k);
* the ladder.

Replays against top teams are **not** valid: their recorded plans collapse when
we deviate (median bank $110k → $77k; `gbtop.py`, `spec_top.txt`).

## Longer track (v18+)

A full demand-matched planner that schedules land, crops and herds for the whole
game from the same model, with an efficient labour router (the gap to DSM's
~$130k banks). HERD is its first building block.

## Progress log

### Rejected on the way (2026-09-27)

| Idea | Result |
| --- | --- |
| Sheep ranch on SE with a 3-hand crew (RNC, `research/tools/v12/rnc_layer.py`), 2+ yarn stores | −$33k in both test games: hands 13-15 cost fib(12-14) = $233-610 **each per day**. Extra labour cannot pay; value must come from redeploying the existing ~12 hands. |
| Carrot swap threshold `V9_CARROT_RATIO` 1.3 / 1.5 / 1.7 (v14 uses 2.0), 203 live games | 125 / 138 / 138 won against 139; paired −$242 / −$11 / −$5 |
| Benchmarking against top-team ghosts (`gbtop.py`) | invalid: ghost banks collapse from $110k to $77k when we deviate |

**Market facts at day 22 of v14's 118 live games** (price ÷ base):
* wool is glutted unless the town has 2+ yarn stores (3-4 stores: $200-240 all game);
* milk is glutted after day 18;
* tomatoes (1.05-1.53×), carrots (1.06-1.61×) and eggs (1.0-1.16×) are under-supplied.

### Planner (`agents/v17/planner.py`), measured by takeover

`agents/v17/hybrid.py` plays v14 until turn T0, then hands over to the planner.
`research/tools/v12/hbench.py` compares its bank with pure v14 on the same seeds
(s8, 4 seeds, against v14):

| Version | Takeover day 29 | 28 | 25 | 21 |
| --- | --- | --- | --- | --- |
| old circuit2 prototype | | −10,274 | −16,838 | −26,956 |
| v0 (tend, harvest, sell) | −1,876 | −2,931 | | |
| + last-day water/fertilize before harvest, delivery, hiring | −501 | −2,386 | −10,689 | |
| + dollar-valued jobs in engine order, zones, two-pass assignment, ongoing-harvest urgency | −650 | −2,706 | −8,881 | −16,502 |
| + route dispatcher (per-quadrant serpentine stretches, one per unit, idle units help) | −939 | −2,875 | −11,342 | −16,582 |
| + **shed-capacity-aware selling** (the midnight drop was overflowing: up to 110 units discarded a night) | −924 | −2,255 | −6,988 | −10,719 (d15 −10,462) |
| + deliver cargo during the day (≥15 units, or from hour 20) | −1,020 | **−1,880** | **−5,740** | **−10,435** (d15 −15,074) |

Remaining gaps, from the traces (`hops.py`, `hunit.py`, `hjob.py`):
* the planner walks about 1.7× more than the tape;
* it produces less wheat and carrots in the last 5 days: the tape replants on a
  choreographed cycle, and uses fertilizer;
* the fertilizer economy and selling timing need work.

The planner has to reach parity from early takeovers before it can replace v14.

## v18 (2026-09-27 evening): planner status and the zero-sum lesson

Numbering: ChatGPT's frontier line deployed v15 (56588731), v16 (56599604, **2513.8, rank
185**, our best live score) and v17 (56605749, weak). The planner in `agents/v17/` is
therefore **v18**.

**What v16 is** (83 ladder games, `bands12.py`, `oppprof.py`):
* NE on day 6, then SW and SE on day 8 (a top-team opening);
* 10 cows, 8 geese, 8 sheep, 16 melons;
* bank median $95k;
* 22-1 against <2400, 19-8 against 2400-2500, 13-15 against 2500-2600 (13 of the
  15 losses by more than $3k), 0-5 against 2600+ (−$12k to −$15k).

Our v14 is 2460.

**Planner milestones since the v17 log** (8 seeds against v14; "vs v14" = our bank
minus v14's bank on the same seed):

| Change | d6 | d9 | d15 | d21 | d25 |
| --- | --- | --- | --- | --- | --- |
| hire cap 11 (hands 12-13 cost $144-233/day each) | | | −4,737 (4 seeds) | −4,334 | −3,640 |
| investment module: land (6/8/10), demand-sized roles, build + buy + place animals | −42,012 → −12,300 (4 seeds) | −4,496 (4 seeds) | | | |
| on 8 seeds | −21,685 | −12,324 | −7,690 | | |
| animals valued with ~$40/day of fertilizer, top-team herd minimums | −17,624 | | | | |
| labour loads recalibrated (animal 3, crop 1.5, 22 turns a hand) | −17,872 | −22,967 | −6,221 | | −2,711 |

**The zero-sum lesson.** Measured as the ladder counts it (our bank − rival bank), the
planner loses far more: −$78k from day 6, −$23k from day 15 and −$5k from day 25, 0/8
won. When it takes over, the v14 rival's bank rises by $10-80k.

Sizing production to "our share of demand" hands the contested markets to the rival.
In a zero-sum game, once we produce at least as much of a product as the rival, one
more unit still raises the margin, because it lowers the rival's price too. That is
why the tape (and the top teams) overproduce contested products.

The planner's objective must be the **margin**, not its own profit. Its production
choices must value "revenue + damage to the rival's price", and its selling must
compete for the top of each curve. Next steps, in order:
1. value production competitively, from the rival's observed supply;
2. restore tape-level volumes of the contested products;
3. only then diversify into unmet demand.
