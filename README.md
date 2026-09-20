# Kaggriculture agent

A finite-horizon agent for the [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture)
competition, derived from the shipped interpreter rather than from any public
leaderboard solution.

`main.py` is the whole submission: one file, standard library only, no
dependency on `kaggle-environments` at runtime.

## The short version

The shared order book is a **sink, not a ceiling**. The town centre and up to
eight shop instances remove on the order of 120 units/day, which is more than a
100-tile farm supplies, so inventory sits below the reference level all season
and the quote sits *above* base — carrot ends a measured episode at **$186**
against a $35 base. Absorption is not the binding constraint; tile-days and
worker-actions are.

The agent therefore equalises marginal revenue per tile-day against a forward
model of the book, reading this episode's actual shop draw to price demand.
Under that valuation a fed-and-cared cow or sheep is worth ~$260/tile-day
against ~$55 for carrot, so the plan is livestock-led — melon for the opening
capital event, carrot and wheat through the middle, a herd capped at the town's
own draw for each product.

Full reasoning, the measured numbers, and the engine facts the plan depends on:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Measured

720 turns, `kaggle-environments==1.32.7`, sides swapped, strict mode:

| Match | Episodes | Result |
| --- | --- | --- |
| vs. built-in `starter` | 16 | **16-0**, ~$62k vs ~$3.5k |
| vs. `benchmark/incumbent` (PR #1), seeds 1-8 | 16 | **16-0**, mean $74,773 vs ~$11k |
| vs. `benchmark/incumbent`, seeds 11-18 (held out) | 16 | **16-0**, mean $70,052 |
| vs. `benchmark/incumbent`, seeds 21-28 (held out) | 16 | **16-0**, mean $50,709 |
| vs. the previous `main.py` in this repo | 12 | **12-0**, mean $63,512 |

For reference, the previous `main.py` in this repository won 31% against that
same incumbent, with both sides finishing between $9k and $13k.

## Layout

```
main.py                     the submission -- stdlib only, `agent` last
agent.py                    import alias for notebooks and tooling
benchmark/incumbent/        previous best agent; the regression gate
tools/cloud_verify.py       verification gates (see below)
tools/search_params.py      coordinate search over the agent's tunables
tools/build_submission.py   tarball with main.py at the archive root
docs/ARCHITECTURE.md        why the agent does what it does
.github/workflows/deploy.yml  verify on every push, submit only from main
```

## Cloud-only

Nothing here is built, tested or submitted from a workstation. A clean GitHub
Actions runner is provisioned on every push; the agent is verified inside it;
only a verified artifact reaches a submission slot.

`tools/cloud_verify.py` covers the ways a submission dies before a slot is
spent:

1. byte-compilation;
2. **entrypoint resolution** — `kaggle-environments` loads a file submission by
   taking the *last callable in the module namespace*, not the one named
   `agent`, so a helper defined below `agent` silently becomes the submission.
   This is asserted explicitly; it cost a rewrite to discover;
3. import and a cold-start action on a minimal observation;
4. a full 720-turn self-play episode with the agent's own exception guard
   **disabled**, so a planner bug surfaces instead of being swallowed;
5. per-turn latency against the 1s `actTimeout`, gated on the overage budget's
   low-water mark;
6. strength against the built-in `starter` *and* against
   `benchmark/incumbent` — beating the starter is table stakes and says nothing
   about ladder position.

## Parameter search

`main.py` reads an optional `KG_PARAMS` JSON override at import time; it is
unset on the evaluator, so the baked-in defaults are what ship. That lets
`tools/search_params.py` run a coordinate search without editing the agent and
without any chance of leaking into a submission.

## Credentials

Kaggle credentials are **not** stored in this repository. Add `KAGGLE_USERNAME`
and `KAGGLE_KEY` as GitHub Actions repository secrets
(Settings → Secrets and variables → Actions). Submission runs only from `main`,
or from a `workflow_dispatch` with `submit: true`, and only after the gates
pass.
