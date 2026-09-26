# research/

Start with `../CONTEXT.md`. Rebuild the workspace with
`python research/setup_workspace.py DIR`, then run scripts from inside `DIR`.

## Tools (`tools/`)

| Script | What it does |
| --- | --- |
| `v10/gb.py EPS AGENT OUT` | Replay recorded ladder games (ghosts/) with AGENT in our seat; reports wins and exact reproduction |
| `v10/h2h.py SEEDS AGENTS OPPS OUT` | Live games, AGENTS vs OPPS (pool names); appends jsonl incrementally |
| `v10/fieldsum.py FILES` | Win table per opponent from h2h output |
| `v10/lossdiag10.py`, `lossdiag11.py EPS` | Replay losses; per-product volume and price effects against the opponent |
| `v10/salelog.py EP AGENT ITEMS DAY` | Hour-by-hour sales of both sides in one replay (sale races) |
| `v10/traj.py EPS AGENT` | Cash lead over the game (where a close loss diverges) |
| `v10/bands.py`, `bands11.py`, `bands_time.py` | Results by opponent leaderboard score band (needs the leaderboard csv and KAGGLE_API_TOKEN) |
| `v10/sales.py`, `glut.py`, `mprice.py`, `tprice.py` | Sales and price profiles by product and window |
| `v10/cv.py` | Leave-one-seed-out validation of route overrides |
| `v10/prof.py AGENT OPP SEED` | Per-turn runtime and cash trajectory |
| `v12/labor.py EPS OUT` | Exact replay and labour audit (action mix, composition by day, revenue) |
| `v12/toptape.py OPP N` | Replay top-team tapes against a live opponent (they collapse) |
| `v12/ptest.py`, `ptrace.py`, `pmoney.py` | Planner test, day trace and money breakdown |
| `v12/mkvar.py BASE OUT NAME=VALUE...` | Build a variant by setting module constants |
| `v12/build_rdx.py`, `build.py` | Splice the RDX or tomato-swap layer into a base agent |
| `root/fetchghost.py LIST` | Download recorded ladder games (KAGGLE_API_TOKEN) |
| `root/v9status.py`, `v10status.py`, `v11status.py` | W-L of a submission from the episode API (KAGGLE_API_TOKEN) |
| `root/harvest.py`, `crawl.py` | Crawl ladder episodes and teams |

## Data (`data/`)

* `ladder_replays.json.gz` holds 293 recorded games:
  * v10's 127 ladder games;
  * v11's 98 ladder games;
  * 68 top-10-team games.

  Each game has the seed, names, final banks and both players' actions per turn.
* `episodes/` holds the episode-ID lists and ladder/band JSONs. The seed files
  for live games are `s8`, `s16`, `s24b` and `fresh150`.
* `results/` holds every experiment's output: jsonl rows of
  `{seed|ep, agent, opp, margin, banks}` and ghost-bench reports.

## Opponents (`opponents/`)

These are the public Kaggle agents used as benchmarks, each under the
Apache-2.0 notices inside its file.

| Folder | Agent |
| --- | --- |
| `prv_rain` | the v8/v9 base |
| `q_demand-preserving-turn-sale-` | the v10 base, tetsutani |
| `p_herd-safe-v3-experimental-ri` | Herd Safe v3 |
| `tetsu_demand` | tetsutani, an older version |
| `r_the-shepherds-ledger-herd-` | Shepherd's Ledger |
| `r_kaggriculture-top-2-master` | Master Engine V4 |
| `q_kaggriculture-harvest-ledger` / `r_kaggriculture-harvest-ledg` | Harvest Ledger, old and new |
| `s_ff4p` | Herd Safe Four-Turn Forecast, patched |
| `r_kaggriculture-multi-route-` | Multi-Route, a top-team replay reconstruction |
| others | 7-Turn Rescue, Population-Robust, Fieldcraft, V40 Challenger, Pioneers, "hack" |
