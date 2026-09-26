# Kaggriculture v12

**v12** (`main.py`) is v11 plus opponent-aware sale timing (RDX) and a late-selling retune; see [docs/V12.md](docs/V12.md). **v11** was v10 plus later-game lead-selling: from day 18 the base's
lead-sellers look 12 turns ahead instead of 8, except for strawberries. It wins
the late sale races against agents running the same route tape: 24-0 against v10,
and 80 of v10's 111 real ladder games replayed against v10's 72. See
[docs/V11.md](docs/V11.md). The v10 notes follow.

`main.py` is the submission. It is a single file, standard library only, and
`agent` is the last callable in it.

v10 is built on tetsutani's *Demand-Preserving Turn Sale Timing* (Apache-2.0,
2026-09-24), the strongest public agent at release. That base is itself the same
route-tape lineage as v8 and v9 (prvsiyan's *The Soil Remembers Rain*), with
newer selling and ordering layers. v10 adds two pieces from v9:

* **Level-2 counter D** in place of the base's level-1 counter D. It orders the
  market list against both a plain rival and a rival running counter D itself,
  which is exactly a copy of the public base. Against that mirror, v10 goes
  13-1-2 on 16 seeds, where the unmodified base ties every game.
* **Morning-hire reserve** from v9, as a safety net: it keeps enough cash for the
  next morning's hires.

| | v9 | v10 |
| --- | --- | --- |
| 412 real ladder opponents replayed (ghosts) | 362 won, +$3,255 | **379 won, +$3,460** |
| vs 8 public opponents, 64 games | 57 won, +$1,293 | 58 won, +$2,104 (base) |
| head to head | | 14 of 16 won |

See [docs/V10.md](docs/V10.md) for the release and
[docs/V10_RESEARCH.md](docs/V10_RESEARCH.md) for what was tried towards the top 10.
Credits: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

v9 and v8 notes (the hire reserve, counter D, the cheaper opening) are in
[docs/V9.md](docs/V9.md) and [docs/V8.md](docs/V8.md). The tables below are the
v8/v9 measurements.

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
main.py                        v12, the submission
THIRD_PARTY_NOTICES.md         upstream credits (Apache-2.0)
docs/V8.md .. docs/V12.md       evidence, method, what failed, what next
candidates/                    v10c / v10d builds as tested
benchmark/incumbent/           the previous live file (v10); gate: the build must not lose to it
benchmark/rival/               the unmodified public parent (tetsutani); gate: must beat it
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
