# markov-chain-

Agent and cloud-only CI/CD for [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture).
Derived from the competition rules and published economic tables; no public
leaderboard solution was consulted.

```
main.py                        self-contained submission agent (stdlib only)
agent.py                       import alias
tools/cloud_verify.py          verification gate — runs on the GH Actions runner
tools/build_submission.py      packages submission.tar.gz (main.py at archive root)
benchmark/incumbent/           the agent currently on the ladder, as a sparring partner
docs/ARCHITECTURE.md           the derivation, with the numbers
.github/workflows/deploy.yml   provision → verify → gate → submit
```

## The objective is not what it looks like

The evaluation page is explicit: *"The actual coin difference in a match does
not affect the rating change—only the win, loss, or tie outcome matters."*

So the target is `P(my bank > their bank)`, not `E[my bank]`. Opponent cash and
tiles are public, so the agent measures its edge directly and prices variance
accordingly: shed variance when ahead late, buy it when behind.

A second consequence shapes the whole strategy — the market book is **shared**.
Premium goods collapse to the $1 floor within 60–160 units, so taking that
capacity before the opponent is worth as much as the cash it earns.

## Global optimum, not local

Tile-days are scarce and the market is the ceiling. The optimal allocation
satisfies

```
price_p(I0 + X_p) / tdpu_p  =  mu      for every produced p
```

— equalise revenue **per tile-day**, not price per unit — with `mu` the shadow
price of a tile-day, bisected so demand exhausts supply. See
`docs/ARCHITECTURE.md` for why a flat price floor is the local optimum and what
it costs.

## Cloud-only by construction

Nothing here is meant to run on a workstation. Every push provisions a clean
runner and runs the full gate there. `tools/cloud_verify.py` is the only place
episodes are executed.

The gate covers the three ways a submission dies, before a slot is spent:

1. **Import/load error on the eval host** → `Error` submission
2. **Uncaught exception mid-episode** → forfeited episode
3. **Turn over the 1s `actTimeout`** → forfeited episode

…then checks strength on two fronts:

- **≥60% vs. the built-in `starter`** — proves it is not broken.
- **≥50% vs. the incumbent** — proves submitting is an *improvement*. This is
  the gate that matters. Beating `starter` is table stakes; it says nothing
  about the ladder.

## Submission format

The engine loads **`main.py` at the archive root** and calls `agent(obs)`. A
file named `agent.py` submitted on its own is rejected as an `Error`, which is
why `agent.py` here is only an import alias.

## Setup

Two repository secrets, under **Settings → Secrets and variables → Actions**:

| Secret | Where it comes from |
| --- | --- |
| `KAGGLE_USERNAME` | your Kaggle username |
| `KAGGLE_KEY` | Kaggle → Account → **Create New API Token** → the `key` field of `kaggle.json` |

The `submit` job is bound to a `kaggle` environment, so you can additionally
require a manual approval there before anything reaches the ladder.

## Submission policy

Kaggriculture allows **5 submissions/day** and scores only the **latest 2**. An
unguarded submit-on-every-push burns the quota and evicts a good ladder agent
with an untested one, so:

- verification and both strength gates must pass first
- pull requests never submit
- a commit message containing `[no-submit]` skips submission
- a preflight reads the day's submission count and aborts at 5/5
- only pushes to `main` can reach the ladder
- `workflow_dispatch` submits only when `submit: true` is ticked
