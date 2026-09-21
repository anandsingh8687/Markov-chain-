# Markov-chain —

Cloud-only global-optimum agent for
[Kaggriculture](https://www.kaggle.com/competitions/kaggriculture).

Derived from the official interpreter and published economic tables. The
previous tree in this repository was deleted and replaced.

```
main.py                        self-contained submission (stdlib only)
agent.py                       import alias
tools/cloud_verify.py          verification gate — GitHub Actions runner only
tools/build_submission.py      packages submission.tar.gz (main.py at root)
docs/ARCHITECTURE.md           derivation and engine facts
.github/workflows/deploy.yml   provision → verify → gate → submit
```

## Objective

The ladder scores **win / loss / tie**. The coin margin is discarded. Unsold
goods are worth zero. The horizon is 720 turns. The shared book collapses
premium goods to $1; eggs and wheat absorb. That is the game.

## Policy (short)

1. **BOOTSTRAP (turns 0–72, or 0–48 vs a carrot farm)** — carrots only.
   Early cash is a multiplier.
2. **EXPAND (to 240)** — buy land, stand up geese (the only scalable asset),
   plant melon into remaining **uncontested** book capacity.
3. **COMPOUND (240–500)** — KKT water-fill: equalise revenue **per tile-day**,
   subtract the opponent's **replant flow**, add town-shop drain.
4. **HARVEST (500–650)** — no new long-cycle assets.
5. **LIQUIDATE (650–720)** — backward induction; unsold stock is `-inf`.

Labour is a 3-turn linear assignment. `FEED` consumes wheat from the worker's
inventory (engine fact). Collapse of >15% over 12 turns pivots the mix.

Win probability is dual-NAV from turn 300: lock a lead by vacating their
book (eggs absorb; uncontested melon stays), or contest a deficit.
Opponent occupancy is a flow from plant day 0, not the standing field.
Coop tiles are reserved before planting. Liquidation reserves against
their dump, not only town drain.

## Cloud-only

Nothing in this repository is meant to be executed on a workstation. Every
push to `main` or `cursor/**` provisions a runner, installs
`kaggle-environments==1.32.7`, and runs the gate there.

Gates, in order:

1. Parse / import / cold-start action shape
2. 720-turn self-play (catches exceptions and the 1s `actTimeout`)
3. ≥60% vs the built-in `starter` (score floor $18k)
4. ≥50% vs a cloud-only carrot-scaler (score floor $20k)
5. 2–0 vs the frozen PR #1 agent in `benchmark/rival/` (score floor $16k)

## Submission

The evaluator loads **`main.py` at the archive root** and calls `agent(obs)`.

Repository secrets (Settings → Secrets and variables → Actions):

| Secret | Source |
| --- | --- |
| `KAGGLE_USERNAME` | Kaggle username |
| `KAGGLE_KEY` | Kaggle → Account → Create New API Token |

The `submit` job is bound to a `kaggle` environment. It runs only on `main`
(or `workflow_dispatch` with `submit: true`), never from a pull request, and
aborts at 5/5 daily submissions. Commit messages containing `[no-submit]` skip
the ladder. Only the latest 2 submissions are scored.
