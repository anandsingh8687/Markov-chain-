# Kaggriculture project: context for a new contributor (human or LLM)

This file is the entry point. It says what the goal is, what every version is,
what was tried and measured, what failed, and how to reproduce any of it.
Everything referenced here is on this branch (`claude/kaggriculture-global-optimum-px3eg4`).

## 1. Goal and status

* **Competition:** Kaggle "Kaggriculture" (`kaggle-environments==1.32.7`). Two
  players run farms for 720 turns (30 days × 24 hours) and share one market. The
  higher final bank wins. The ladder rates submissions with a TrueSkill-like
  rating.
* **Goal:** the top 100 (and ideally the top 10).
* **Status, 2026-09-26:** team rank ~530 of ~10,000.

| Rank | Score |
| --- | --- |
| 10 | ~2,900 |
| 100 | ~2,650 |
| 200 | ~2,550 |
| 300 | ~2,500 |

Our submissions (Kaggle submission IDs):

| Version | Submission | Peak / latest rating | Notes |
| --- | --- | --- | --- |
| v3-v7 | 56327971, 56337503, 56352174, 56369266, 56398661 | — | earlier agents, see `versions/v3`, `v6`, `v7` |
| v8 | 56503612 | ~2,260 | public route-tape base + counter D |
| v9 | 56525155 | 2,296 → ~2,205 | + morning-hire reserve, Herd Safe opening |
| v10 | 56540053 | **2,511** → ~2,380 | stronger public base (tetsutani) + level-2 counter D |
| v11 | 56560456 | ~2,385 | + late-game early selling |
| **v12** | **56575662** | pending (submitted 2026-09-26 09:25 UTC) | + opponent-aware selling (RDX) |

Ratings drift down as the field improves. v10 fell from 2,511 to ~2,380 in a
day while other teams shipped improved copies of the same public base.

## 2. Game mechanics that matter

The engine source is in the kaggle-environments package:
`envs/kaggriculture/kaggriculture.py`.

**Board and land**

* A 10×10 farm with four 5×5 quadrants. NW is owned from the start.
* Extra quadrants are bought in the order NE, SW, SE for $1,000, $2,000 and
  $4,000.
* The shed sits at the centre. Its 4 access tiles are the inner corners of the
  quadrants: (4,4), (5,4), (4,5), (5,5). PICKUP, DROP and PLACE only work there.
* The shed holds 100 items; anything above that is discarded at midnight.

**Workers**

* The farmer persists across days. Hands are hired each day and wiped at
  midnight.
* The n-th hire of a day costs fib(n): 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89,
  144, 233, 377 and so on. The first ~10 hands are cheap; after that wages
  explode.
* At midnight every inventory drops into the shed automatically.
* Each unit does one action per turn: move, PLANT, WATER, HARVEST, FEED, CARE,
  COLLECT_FERTILIZER, FERTILIZE, DIG, BUILD_PASTURE, BUILD_COOP, PLACE, PICKUP,
  DROP or PASS.

**Market**

* At most **10 market orders per turn**, and HIRE is one order per hand.
* Unit actions resolve before market orders, so seeds bought on turn t can only
  be planted from turn t+1.
* A PLANT request fails for everyone if the day's PLANT requests for a crop
  exceed the seeds held.
* The market runs in **per-unit lockstep**: both players' order queues are
  processed unit by unit, so the order of our market list matters. "Counter D"
  optimises that order.
* Prices depend on the market's inventory against I0 = 10,000:
  * Shortage ("hinge") raises tomato, carrot and egg prices fast once more than
    ~T units are missing.
  * Oversupply crashes strawberry and milk linearly. Wool and melon crash
    quadratically. Egg and wheat fall only logarithmically, so they are
    forgiving.
* Each unlocked shop drains 1 of each of its products every 4 turns: 6 a day,
  or 12 a day for single-product shops (yarn store, pet cafe). The town centre
  drains 1 of each product a day.
* A new shop unlocks every 3 days, up to 8 shops, drawn with replacement. The
  shop RNG is shared with weed spawning, so **the town layout depends on both
  players' actions**. Any change after day ~15 reshuffles later shops, which
  makes benchmarks noisy.

**Crops and animals**

* Plants die after 2 consecutive unwatered days, and the planting day counts
  as unwatered.
* Non-ongoing crops (wheat, carrot, melon) gain yield from waterings inside a
  window and rot after `max_yield_day + 1`.
* Ongoing crops (tomato, strawberry) produce a fixed number of times. When
  fertilized, each production gives 2 units, up to a cap of 4 held.
* Animals escape after 2 unfed days. With daily care, yields are about:
  * cow: 1.5 milk a day;
  * sheep: 1.33 wool a day;
  * goose: 2 eggs a day.
* Every animal also gives 1 fertilizer a day.
* The last turn that processes actions is 718.

## 3. The agent lineage (v8-v12)

Every shipped version from v8 on is built on a public Apache-2.0 lineage. Its
upstream notices are kept inside each file, and credits are in
`THIRD_PARTY_NOTICES.md`.

* **Route-tape chassis.** At turn 144 a router picks one of 41 pre-recorded
  720-turn "route tapes" (per-unit command sequences) from the first two shops.
  The workers replay the tape. The tapes are very efficient: about 42% of
  worker turns are moves, the same share as the top-10 teams.
* **Reactive layers on top**, almost all about *selling*:
  * RACE and RACEPX: reservation-based race selling;
  * COURIER;
  * CARROT swap: wheat to carrot when the carrot price pays;
  * HERD;
  * V219: a day-18 tomato annex on the SE plot when 3 or more tomato shops are
    open;
  * V233: a sheep annex;
  * WHEAT BUY-FIRST;
  * the lead-sellers FLOWPX, DAWNPX, MODELPX and the EV window;
  * BUYDIP;
  * SHIELD-MILK;
  * counter D (best-response market ordering);
  * same-item SELL compaction;
  * queue hole-closure.
* **Our additions:**
  * v8: level-2 counter D.
  * v9: the morning-hire reserve (fixed a day-1 cash crunch that caused
    −$28k collapses) and the Herd Safe 8/3 opening.
  * v11: late-game look-ahead for the lead-sellers.
  * v12: RDX.

Per-version write-ups: `docs/V8.md` to `docs/V12.md`, and `docs/V10_RESEARCH.md`
(the research log).

## 4. How to evaluate (read this before changing anything)

1. **Replays of real ladder games are the best proxy for the ladder.** Download
   our ladder episodes, then replay each with a candidate in our seat and the
   opponent's recorded actions. The original agent reproduces **exactly**
   (98/98). This measures a change against the *actual current population*.
   * Tools: `research/tools/v10/gb.py`, and `tools/ghost_bench.py` for the
     older 412-game archive.
2. **Live games against public agents** (`research/tools/v10/h2h.py`) use
   opponents that *react*. Early selling looks bad there (it loses 1-3 more
   games in 24), but live ladder data showed the replays were right:

   | Opponent score | v10 live | v11 live |
   | --- | --- | --- |
   | 2400-2500 | 4-15 | 11-17 |
   | 2300-2400 | 7-6 | 21-6 |

   Treat live public-agent games as a sanity check, not the objective.
3. **Always confirm on a second, independent sample.** We use v11's 98 and
   v10's 127 ladder games. Gains of ±2 in 100 are noise.
4. **Map every game to the opponent's leaderboard score**
   (`research/tools/v10/bands.py`, `bands_time.py`). The rating is decided by
   the band just above us.
5. After any change, check runtime (`research/tools/v10/prof.py`, about 2 ms a
   turn) and that `agent` is the last module-level callable. Kaggle loads the
   last callable.

## 5. What the data says

* **Nearly every opponent from 2,400 to 2,700 runs the same route tape as we
  do:** land on days 6 and 11, 12 melons, 33 strawberries, the same herds.
  They differ only in their layers.
  * Most of our losses are **close sale races** (−$10 to −$1,500) on the same
    volumes. The rival sells its batch (for example 18 strawberries) at once,
    one hour before us, and takes the top of the price curve.
  * `research/tools/v10/salelog.py` shows this hour by hour.
* **Tomatoes are the recurring big-loss pattern.** Unmet tomato demand builds
  to about 330 units by day 27-29, and the price climbs to $160-290. Stronger
  copies grow tomatoes on their own land from day 11-18.
* **Top-10 teams (for example DSM, 126-1) are adaptive planners.**
  * Same labour mix as us (42% moves), but 3 plots by day 10, 3.7 by day 14,
    ~18 animals by day 10, 8-14 tomatoes, geese, and about one more hand a day.
  * Their recorded plans **collapse** when replayed against a different
    opponent: 11 of 12 fell to $3k-80k.
  * So a library of top-team plans does not work, and neither does copying
    their plan into our tape.
* The shipped route tapes cannot reallocate crops mid-game. Workers follow
  fixed scripts, so a layer can only swap one tile action for another at the
  same turn. It can never add a step.

## 6. Tried and rejected (numbers in the docs)

| Idea | Result | Where |
| --- | --- | --- |
| Per-layout route overrides | −$45 to −$215 a game on held-out seeds (overfit) | V10_RESEARCH |
| Tomato annex gate at 1 or 2 shops | −$566 / −$325 a game; replays 368 vs 379 | V10.md |
| Tomato swap (Roxy's method) on day-18 wheat replants | −$2.2k a game (7 scattered tiles, 4.4 tomatoes a plant, crew walking) | V11.md, `research/v12/tomato_swap_layer.py` |
| Copying top-team tapes, raw or through our layers | collapses | V10_RESEARCH, V11.md |
| Foreman planner (greedy dispatcher) | ~$62k against v9's $96k | V10_RESEARCH |
| Circuit planner v12 (`agents/planner/`) | ~$44k against v11's ~$95k after 12 rounds (see §7) | V11.md |
| Late selling tuned on replays only | great on replays, loses 3-5 games in 24 to reactive agents | V12.md |
| v13 sweep of single settings on v12 (a1-a12) | no gain beyond noise | V13.md |
| MDX aimed one hour before the rival's earliest dump | 78-79/98 against a fixed 5am's 81 | V13.md |
| Annexes, patient seller, race tweaks, carrot ratio | small or negative | V9.md, V10_RESEARCH |

## 7. The adaptive planner (long-term track)

* `agents/planner/circuit.py`: dated, shop-adjusted targets for land, animals
  and crops (based on DSM's opening), and the farm design.
* `agents/planner/circuit2.py`: an executor that plans each worker's day exactly
  every morning, as nearest-neighbour tours from the quadrant corners closed
  when a worker's turns run out, with one unit per tour. It also has:
  * strict cash priorities: sell, hire, seeds, feed, then investments only with
    tomorrow's wages and feed kept back;
  * herd sizes set by market demand (shop drain minus the opponent's visible
    output);
  * budgeting of the 10 order slots per turn;
  * smart watering and a tour cap.
* **Status:** zero drought deaths, but ~$44k against v11's ~$95k.
* **Open issues:**
  * work capacity: 19-21 tours are needed but only about 12 hands are
    affordable;
  * crops missed at harvest;
  * product mix and market timing.
* Tools: `research/tools/v12/ptest.py`, `ptrace.py`, `pmoney.py`, `labor.py`
  (labour audit of any replay).

## 8. Current work (v13)

* **Live on 2026-09-26 13:28 UTC:**
  * v12 is 2446.3 (rank 391, 49-23), v11 2362.7, v10 2379.5; rank 100 is 2642.7.
  * Replayed on v12's 72 live games (out of sample), v13 wins 59 to v12's 49.
  * Band results are in `docs/V13.md` §7.
* **v13 candidate: `candidates/v13/main.py` (not submitted).** It is v12 plus
  the MDX layer. From day 18, at 5am and 5pm, MDX sells the whole shed stock of
  strawberries, milk and wool, first in the market queue. Full numbers are in
  `docs/V13.md`:
  * replays: 183/225 against v12's 172, +$168 a game paired;
  * older 412-game archive: 386 against 382;
  * 16/16 against v12;
  * −1 to −3 games in 16 against reactive public agents (the same pattern as
    v11).
* Why it works: late in the game the tape's harvests reach the shed at
  midnight. v12 trickled them out from mid-morning, while tape copies sold the
  batch at the peak and we sold into their crash. Quotes only recover by the
  daily drain, so the first seller wins.
* The single-knob sweep over v12's selling stack (a1-a12) found nothing. Its
  two "+1 win" variants won back the same $13 game.
* Next ideas:
  * the Harvest Ledger / Shepherd's Ledger weakness of early selling;
  * RDX v2: predict the rival's dumps from its visible harvests;
  * growing tomatoes mid-game;
  * the planner.

## 9. Repository map

```
main.py                      live submission (v12)
versions/v3..v12/main.py     every version we built or shipped (v3/v6/v7 = earlier account submissions)
versions/experimental/       key experiments: v11m, w_s0f360, v12r (RDX on v10), r11_2_6, v10g2 (tomato gate 2), v12a (tomato swap)
candidates/                  v10c, v10d (= v10), v11, v12 as tested
agents/planner/              circuit planner (v12 research); agents/foreman/ older planner
research/opponents/          public benchmark agents (Apache-2.0, notices inside each file)
research/tools/              analysis and benchmark scripts (see research/README.md)
research/data/               episode ID lists, per-experiment results (.jsonl), 293 recorded ladder games (ladder_replays.json.gz)
research/setup_workspace.py  rebuilds the working layout the tools expect
research/v12/                tomato swap and RDX layers (standalone)
docs/                        per-version write-ups and research logs
tools/                       CI tools (ghost_bench, cloud_verify, fetch_ghosts)
benchmark/                   CI gates (incumbent = v11, rival = public base) and the 412-game ghost archive
```

## 10. Reproduce anything

```bash
pip install kaggle-environments==1.32.7
python research/setup_workspace.py /tmp/ws && cd /tmp/ws
python v10/gb.py eps_v11_all.txt pool/v12/main.py out.jsonl            # replay 98 current ladder games
python v10/h2h.py v10/s24b.txt v12 prv_rain,s_ff4p out.jsonl       # live games: seeds file, agent names, opponent names (pool/<name>)
```

To download new ladder games or submit, set `KAGGLE_API_TOKEN` in the
environment. **Never commit a token.** Submission:
`kaggle competitions submit kaggriculture -f main.py -m "..."`.
