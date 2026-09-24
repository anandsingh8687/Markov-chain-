# Kaggriculture v9

`main.py` is the submission. It is a single file, standard library only, and
`agent` is the last callable in it.

v8 and v9 build on the strongest public agent, prvsiyan's *The Soil Remembers Rain*
(Apache-2.0), and add:

* **Counter D** (shiiin9). Each turn it picks the order of our market orders by
  solving the engine's per-unit lockstep exactly against a rival that plays our
  own list.
* **Sale-race horizon 44.**
* **Level-2 counter D** (new in v8). Counter D is public, so v8 also models a
  rival running it, and picks the ordering that is best against the worse of the
  two rival models.
* **Cheaper opening** (v9, from Herd Safe v3): buy 8 / sell 3 wheat instead of 20 / 15.
* **Morning-hire reserve** (new in v9). It keeps enough cash for the next
  morning's hires. A $1 end-of-day balance used to cost 2 hands, then the cow,
  then the herd: v8's two biggest ladder losses. See [docs/V9.md](docs/V9.md).

Credits: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The full evidence and
the experiments that failed are in [docs/V8.md](docs/V8.md).

## Measured

`kaggle-environments==1.32.7`, 720 turns, real ladder seeds. Each seed is counted
once, because games are deterministic.

**Ladder:** v8 went 79-15 over its first 94 games (rated 2188.9, still climbing).
**v9 against the same real opponents:** 362 of 412 ghost games won, against 357
for v8 (mean margin +$3,255 against +$2,632). All four of v8's collapse games flip to wins by
more than $17k.

| Test | v8 lineage | For comparison |
| --- | --- | --- |
| **210 real v7 ladder games, opponent replayed from its recorded tape** | **185 won** (v7 won 61, tied 39) | base 169, tetsutani 155 |
| the 110 of those that v7 lost | **87 turned into wins** | base 77, tetsutani 58 |
| vs the user's v7, 20 seeds | 20-0, +$1,938 | |
| vs the user's v3, 44 seeds | 44-0, +$4,502 | |
| vs the base (prvsiyan), 16 seeds | 15-1, +$380 | |
| vs tetsutani demand (counter D), 16 seeds | 16-0, +$1,168 | |
| vs the level-1 build (counter D + 44), 16 seeds | 14 W, 2 T, 0 L | |

The ghost replay cannot react to v8, so it flatters any agent somewhat. The
closed-loop rows are the check on that.

## Layout

```
main.py                        v9, the submission
THIRD_PARTY_NOTICES.md         upstream credits (Apache-2.0)
docs/V8.md, docs/V9.md         evidence, method, what failed, what next
benchmark/incumbent/           the live v8 file; gate: the build must not lose to it
benchmark/rival/               the unmodified public parent; gate: must beat it
benchmark/ghosts/              412 real ladder opponents (v3-v8) as replayable tapes
benchmark/ladder/              real ladder banks by seed (tools/ladder_gap.py)
benchmark/legacy/              PR #1 / PR #2 agents, for the scratch agent's tools
tools/cloud_verify.py          loader, import, strict self-play, latency, structure, strength
tools/ghost_bench.py           replay real ladder opponents against an agent
tools/fetch_ghosts.py          refresh the ghosts from the Kaggle episode API
tools/build_submission.py      tarball with main.py at the archive root
agents/scratch/                the from-scratch agent this repo started with (research)
.github/workflows/deploy.yml   verify on every push, submit only from main
```

## Cloud-only

Nothing is built, tested or submitted from a workstation. On every push a clean
GitHub Actions runner runs these checks:

1. `tools/cloud_verify.py`:
   * byte-compile
   * last-callable entrypoint
   * cold-start import
   * a strict 720-turn self-play
   * latency against the 1s `actTimeout`
   * a structural check at turn 480
   * strength against the built-in starter
2. 4 seeds against `benchmark/incumbent`, the live v8 file.
3. 4 seeds against `benchmark/rival`, the public parent.
4. `tools/ghost_bench.py` on the 40 most recent real v7 games. v7 won 3 of them;
   v8 wins 35. The gate is 75%.

Only a push to `main` without `[no-submit]`, or a manual run with
`submit: true`, reaches the submission job. A daily-quota preflight guards that
job, because only the latest 2 submissions are scored, and each new one evicts
the oldest.

## Credentials

**A `KGAT_...` token authenticates only through `KAGGLE_API_TOKEN`.** The
legacy `KAGGLE_USERNAME` + `KAGGLE_KEY` pair is rejected for that kind of token.
Store the token as the repository secret `KAGGLE_API_TOKEN`, and never commit
it.
