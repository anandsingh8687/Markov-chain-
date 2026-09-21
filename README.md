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
| vs. built-in `starter` | 4 | **4-0**, median margin +$77,458 |
| vs. `benchmark/incumbent` (PR #1), seeds 1-18 | 32 | **32-0**, mean $76,393 vs ~$11k |
| vs. `benchmark/incumbent`, seeds 31-42 (fresh) | 24 | **24-0**, mean $73,106 |
| vs. `benchmark/rival` (PR #2 `32762ff`), two seed sets | 24 | **24-0**, mean $75,176 / $83,011 |
| vs. the previous `main.py` in this repo | 12 | **12-0**, mean $63,512 |

Even with two copies of this agent on both sides of the book, every product
the town buys finishes *under*-supplied at two to three times base price. The
market is not the ceiling — see `docs/ARCHITECTURE.md` §3b.

For reference, the previous `main.py` in this repository won 31% against that
same incumbent, with both sides finishing between $9k and $13k.

## Layout

```
main.py                     the submission -- stdlib only, `agent` last
agent.py                    import alias for notebooks and tooling
benchmark/incumbent/        PR #1 agent; regression gate
benchmark/rival/            PR #2 agent, the strongest rival; regression gate
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
6. a **structural check** at turn 480 — staffing, tile utilisation, weed
   count, and whether any farmed product has been crushed below a quarter of
   base. Score alone hides a farm that buys 75 tiles and works thirteen, or
   an allocator that saturates the one product the town never buys;
7. strength against the built-in `starter` *and* against both
   `benchmark/incumbent` (PR #1) and `benchmark/rival` (PR #2) — beating the
   starter is table stakes and says nothing about ladder position. A
   submission that loses to an agent already sitting in this tree is a
   regression whatever it scores against the starter.

## Measuring against a strong opponent

Beating `starter` measures how much of an *uncontested* book an agent can
harvest. A ladder is a different problem — the book is shared and the town's
draw is fixed, so whoever reaches the high-value products first gets the
higher quotes. `tools/selfplay_ab.py` plays a candidate against a frozen copy
of the current agent (`tools/freeze_champion.py`); identical agents score
exactly 0.500, which is the control.

Read both numbers. Self-play measures contested strength but is blind to any
change that expands absolute production, because the mirrored opponent expands
too and they split the same book. Mean bank against a fixed opponent measures
that. They disagreed on the feed-shadow experiment, and the absolute measure
was the one that mattered (`docs/ARCHITECTURE.md` §6d, §7).

**The noise floor matters more than any single result here.** At 16 episodes
the standard error on a self-play score is ~0.12; four candidates this session
looked like clear wins at that size and reversed at 44-48 episodes. Treat
nothing under ~8% on a 44+ episode sample as a result.

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
