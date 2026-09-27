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
