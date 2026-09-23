# Rival benchmark

`main.py` here is the agent from PR #2 (`cursor/flow-lock-ramp-2233`, commit
`32762ff`) — the strongest agent this repository has produced other than the
current `main.py`, and the one to beat if anything here is to count as an
improvement. Refresh it whenever that branch moves.

It is kept alongside `benchmark/incumbent/` (PR #1, which PR #2 is stacked on
and beats 10-2) so the strength gate measures against a moving target rather
than only against the built-in `starter`, which finishes around $3.5k and
proves nothing.

## History, and where it still loses

`d77b193` shrank the farm to fit its labour and worked 13 of 75 tiles.
`32762ff` fixed that — it re-hires every morning, fills tiles against
`workers*4`, and reopens milk and wool — and it is a real improvement:
utilisation 17% -> 55-76%, and seed 9034 went from $10,903 to $33,966.

It is still 3x short, and the closing book says why. After `32762ff` farms
seed 9034:

| Product | Inventory vs I0 | Quote | Base | |
| --- | --- | --- | --- | --- |
| Melon | **+156** | **$7** | $250 | crushed to the floor |
| Strawberry | −318 | $270 | $120 | unfarmed, 2.2x base |
| Wheat | −718 | $52 | $25 | under-farmed |
| Milk | −132 | $260 | $160 | under-farmed |

The allocation is inverted. Melon is the one crop with no shop demand at all
— the town centre takes one a day and nothing else — so it is the only
product that genuinely saturates, and it took 12-17 tiles late. Strawberry
has four of the eight shop types buying it and finished 318 units short at
more than twice base, with zero tiles.

That is what pricing a tile against the *end-of-horizon* book prevents
(§2): melon's marginal price collapses as soon as own pipeline grows because
its drain is ~1/day, while strawberry's drain keeps its marginal price high.

## Why the first revision plateaued, recorded so the mistake is not repeated

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

PR #2 bought 75 tiles and farmed thirteen of them. Note that at turn 480 on
that seed it had **twelve hands** — hiring was not the binding constraint
there, the `workers*2 - herd` plant cap was. Weeds are a symptom of
under-staffing (see `docs/ARCHITECTURE.md` §4, where hires were being
silently dropped by the ten-order-per-turn cap), but capping the board is not
the cure for them: it removes the revenue and leaves the cause in place.

It also closed milk and wool entirely, the two highest-value assets on the
board at roughly $260/tile-day. `32762ff` reopens them.
