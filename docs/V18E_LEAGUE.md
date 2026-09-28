# V18e research: a league of real public agents, and why V16 loses to strong teams

Status: research, 2026-09-28. Nothing here is submitted.

## 1. Offline tests against recorded opponents mislead

* **Bench:** 175 recent games of current top-100 submissions (`top26_sel.json`,
  `gbt.py`). Our agent takes the non-top seat; the top team replays its recorded moves.
* **Result:** V16 beats the top team's recorded bank in 61% of games (76% against its
  replayed moves); V18d in 63% (79%).
* **Live, V16 went 0-7 against 2600+ teams.** A replayed team cannot react, so it is far
  weaker than the same team live. Such benches cannot certify a win rate against
  strong teams.
* **Our 13 losses to 2600+ teams** (`endgame_hi.jsonl`): we lead by about $5k on days
  12-14, then lose about $1k a day from day 15 to the end (−$13.7k).

## 2. A league of reacting opponents

* **Crawl:** 37k ladder episodes with a 2600+ side (`crawl26.py`).
* **Notebooks:** 299 public notebooks listed, 254 agents downloaded (`nbfetch.py`).
  `nbscreen.py` plays each one against V18d on one seed.
* **Pipe-7:** 15 of 25 early v18a/v18c losses share one opening, reproduced move for
  move by "Pipe-7 Wheat Microstructure" (`idnb.py`, `fullmatch.py`). That opening is
  common to the whole public route-tape family: V16 met it in 90 of 110 ladder games
  (59-31).

**League, both seats, 8 seeds (16 games per pair):**

| Opponent | V18d | V16 | V14 (x6) | V15 |
| --- | --- | --- | --- | --- |
| yhay81 Fieldbook (ShopForge routes) | **1-15, −20.6k** | 2-14, −47.4k | **16-0, +17.3k** | 16-0, +16.3k |
| kaitofukami v58 Known Streams minimax | **2-14, −19.0k** | 1-15, −50.1k | | |
| boatlee v13-r3 top-meta | 8-8, −3.7k | | | |
| kaitofukami v21.1 conditional memory | 8-8, −3.7k | | | |
| ahmed v52 lean flock | 10-6, −0.7k | | | |
| statma tetsutani demand-preserving | 14-2, +3.7k | | | |
| Pipe-7 | 16-0, +8.4k | 24-8, +5.4k | | |
| goodpjw 2749, jaxa 2802, seyitkaan 2820 | 48-0, +8-9k | | | |
| boatlee v16-rc2 | 16-0, +32.7k | | | |

**The matchups form a cycle.** Fieldbook and v58 beat V16, V17, boatlee and kaito-v21 by
$41-50k, but lose 0-16 to Pipe-7 and haideptry, whom V16 beats.

**The mechanism.** V16's first-shop route selector (DSM routes) is the weak point.
Against Fieldbook, V16's money stays near $0 on days 4-8, its land and animal
purchases fail without any error, and it ends with a small farm (for example 2 quadrants,
3 cows, 3 sheep), banking $66k to Fieldbook's $114k. The single-tape V14/V15 line
beats Fieldbook 16-0.

## 3. Next: the V18e candidate

V14's single-tape core plus the V18 fixes (herd swap with wool weight 3, land retry,
land debt), measured on the whole league (`h2h2_x6league.jsonl`).

## 4. Final results (2026-09-28)

**Wider league** (the game is seat-symmetric, so each seed is one distinct game):

| Agent | Distinct games won | Rate |
| --- | --- | --- |
| V14 (x6) | 119 / 136 | 87.5% |
| V14 + herd swap | 99 / 136 | 73% |
| V14 + land fixes | 41 / 80 (first league only) | 51% |

* V14 beats every public family (Fieldbook and v58 8-0) and loses only to V16 and V17
  (3-5, −$1-2k a game).
* The V18 layers transfer badly to V14: the land retry fights V14's own land schedule.

**Top-team route transplant (V19), rejected.**
* 6 of the top 10 teams (M&M&P&Q, DSM, Vadim, DECEM, Mother-Goose, mtmr) use V16's exact
  opening. `buildroutes.py` swapped V16's route library for their current highest-margin
  tapes, one per first shop.
* DSM-only library: 24/64 (−$13.9k a game). Six-team library: 12/64 (−$57.6k a game).
* A top team's strength is its live adaptive logic, which is private, not its tapes.

**Status when the work stopped:** v18c (56618384) and v18d (56621918) are live. No
further submissions.
