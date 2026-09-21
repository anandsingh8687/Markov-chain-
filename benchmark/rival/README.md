# Rival benchmark

`main.py` here is the agent from PR #2 (`cursor/flow-lock-ramp-2233`, commit
`d77b193`) — the strongest agent this repository has produced other than the
current `main.py`, and the one to beat if anything here is to count as an
improvement.

It is kept alongside `benchmark/incumbent/` (PR #1, which PR #2 is stacked on
and beats 10-2) so the strength gate measures against a moving target rather
than only against the built-in `starter`, which finishes around $3.5k and
proves nothing.

## Why it plateaus, recorded so the mistake is not repeated

PR #2 diagnosed a real symptom — earlier revisions of its line harvested
33-47 weed tiles — and treated it by shrinking the farm: never buy the SE
quadrant, cap the herd at `min(8, workers-2, tiles/4)`, cap cows and sheep at
four each, and cap standing plants at `workers*2 - herd`.

Measured on seed 9034 at day 24, against the same opponent:

| | unlocked tiles | productive tiles | utilisation | final bank |
| --- | --- | --- | --- | --- |
| current `main.py` | 100 | 80 | **80%** | $111,592 |
| PR #2 | 75 | 13 | **17%** | $10,903 |
| PR #1 | 50 | 37 | 74% | $16,053 |

PR #2 buys 75 tiles and farms thirteen of them. Weeds are a symptom of
under-staffing, not of over-expansion: the fix is to get the hands the farm
is already paying for (see `docs/ARCHITECTURE.md` §4, where hires were being
silently dropped by the ten-order-per-turn cap), not to shrink the board to
fit the labour that arrived.

It also closes milk and wool entirely, which are the two highest-value assets
on the board at roughly $260/tile-day, and its closing book on that episode
has egg pushed *above* the reference inventory while carrot sits 244 units
below it at a high quote — production aimed at the one thing it had already
saturated.
