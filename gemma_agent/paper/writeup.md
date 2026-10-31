# SealedGate-161: a Calibrated Fresh-Repository Gate for Changing a Gemma 4 Coding Agent

**Subtitle:** 161 verified tasks from 128 unseen repositories, per-task outcomes for thirteen Gemma 4 agent bundles, a sequential-runtime model accurate to 2%, and a vLLM tool-parser hang that silently zeroes small-model runs.

## Abstract

Coding-agent changes are often accepted on a few dozen local tasks. At the 13% per-task discordance we measured between agent variants, a paired comparison on fewer than 60 tasks cannot detect any gain with 80% power. The Gemma 4 Developer Agent leaderboard is no escape: one 58-task, 11-hour draw per day, and repeats of one bundle span 0.15–0.18.

We release **SealedGate-161**:
- 161 tasks from 128 Python repositories outside the public set, each verified twice in the competition's py3.13 sandbox (45% of buildable candidates' gold patches failed there), split by repository into tuning (89) and sealed (72) halves;
- a paired protocol sized by a power table;
- a virtual clock that predicts sequential real-clock runtime within 1.6% on a held-out kernel;
- per-task outcomes for 1,019 runs of thirteen Gemma 4 31B and E4B bundles, calibrated against the leaderboard; per-task solve rates match an independent lab's (r = 0.95).

What the gate found:
- vLLM's Gemma 4 tool parser up to 0.20.2 (the scorer pins 0.19.1) loops forever on some tool-call strings, freezing every request; it ended 41 of our 86 E4B runs.
- Gemma's recommended sampling (temperature 1.0, top-k 64) beat temperature 0.2 by +4 of 87 tasks (p = 0.34), with a clear mechanism: loops 4 → 0, wrong patches 37 → 28.
- ADK's default compaction drops the verbatim issue: runs that compacted before any edit solved 11 of 88, the others 43 of 67.
- More calls for less thinking, failure-derived prompt rules, a sub-agent and E4B (1 solve in 57 runs) were rejected.

## 1. Introduction

A competition agent is a declarative Google ADK bundle (agent.yaml, prompt, sampling and budgets) served by vLLM on 4×L4 GPUs with a 32k context. The hidden scorer runs about 120 tasks from private repositories one after another, under a 12-hour total limit and the bundle's per-task limits. Our base bundle, v29, uses temperature 0.2, a 4096-token thinking budget, 28 tool calls, 80 turns and 8 minutes per task. The public leaderboard scores 58 of those tasks.

Three properties of this setup make most agent changes untestable on the leaderboard:

1. **Slow.** One submission per day, and about 11 hours per draw.
2. **Noisy.** Three draws of the same zip scored 0.18, 0.15 and 0.15. An independent beta-binomial analysis puts the minimum detectable difference at n = 58 at 0.12–0.19 (jaikwang, *Measuring the Measuring Stick*).
3. **Unforgiving on time.** Our v28 projected only 1.3% slower than v29 on the same tasks, yet exceeded the 12-hour limit and scored nothing.

The usual local sets (public example repositories, famous libraries) are small, partly memorised, and run on a different clock. We wanted a gate: a fixed procedure that says, before a slot is spent, whether a change is better, whether we could even tell, and whether it fits in 12 hours.

**Contributions.** New here: the parser hang (§4.6), evidence that verification certifies a build, not a task (§2.1), the largest paired sampling test (§4.1), compaction timing (§4.4) and a gate-sizing rule (§3.1). Timing structure, ~2× local inflation and negative results confirm others'. The procedure carries over to any slow, noisy, time-limited agent benchmark.

## 2. The resource

### 2.1 Construction

**Candidates.** 420 candidates from 302 repositories in the SWE-rebench family (CC BY 4.0), filtered to: created after 2025-02; at most two tasks per repository; gold fix within 3 Python source files and 150 lines; at most 1.8% `async def` functions (the sandbox's runner is unreliable on async suites); no famous or public-example repositories.

**Build.** Four CPU Kaggle kernels snapshot each repository at its base commit, freeze a uv-managed Python 3.13 environment with offline cp313 wheels, and run the official verifier on gold, empty, gold, empty. A task is kept only when gold passes and empty fails both times.

**Where candidates were lost.** 124 were dropped at build time (89 above the async limit, 29 failing dependency resolution under py3.13, 6 with wheels over 1.5 GB). Of the 296 buildable, 133 (45%) had a gold patch that did **not** pass in the competition's environment, 1 was flaky and 1 passed with the empty patch (`rejects.jsonl`). toasterson (93 of 239 built) and sslasme (294 of 1,440 kept) report similar losses. Verification certifies a build, not a task: on 105 candidates both toasterson's pipeline and ours checked, verdicts disagree on 18 (17%). Any port must re-verify in its target sandbox.

**Task text.** As in the competition, problem statements are PR-style: the PR title and body for 160 tasks, the issue text for one. Hints are blank and the fail-to-pass and pass-to-pass lists are withheld from the agent.

### 2.2 Profile

| Property | Value |
|---|---|
| Tasks / repositories | 161 / 128 |
| Task dates | 2025-02-02 … 2026-05-12 |
| Gold patch, changed non-test lines | median 22 (IQR 8–43, max 141) |
| Gold source files | median 1, max 3 |
| Splits | A 89 (tuning) / B 72 (sealed), split by repository with a fixed seed |
| Interface-dependent tasks | 6 SWE-rebench-V2 `_interface` variants; never run |
| Licences | MIT 68, Apache-2.0 33, BSD 28, MIT-0/Unlicense 6, MPL-2.0 1, unclear 25 |

### 2.3 Lab harness

A Kaggle 4×L4 kernel serves the model with the competition's vLLM settings, compaction and tools, runs six tasks at once in docker-like sandboxes, and grades with the official verifier. Because concurrent tasks slow each other, the 8-minute limit is enforced on a **virtual clock**: each LLM step is charged

0.115 s + 28.55 ms × completion tokens + 0.335 s per 1k uncached prompt tokens,

plus 25.4 s after each history compaction, plus measured tool time. The agent is stopped when virtual time reaches the bundle's limit. §3.2 describes how these constants were fitted.

### 2.4 What we release

- **Tasks:**
  - `tasks.jsonl` (competition schema, SWE-bench field names), `tasks_meta.jsonl` (source, dates, licence, F2P/P2P lists, verification log), `rejects.jsonl` and split files;
  - repository snapshots and code graphs for the 136 openly licensed tasks, rebuild recipes for the other 25, and cp313 wheels for all 161.
- **Code:** build pipeline, lab generator, clock predictor, paired statistics and the analysis behind every table.
- **Runs:** `outcomes.csv` (1,019 runs: outcome, calls, tokens, virtual and predicted seconds, malformed calls), leaderboard draws, 668 graded trajectories, `crosswalk.csv` (overlap with other sets) and all fourteen bundles (s4 awaiting its lab).

We do not redistribute competition data (harness files, docker shims); the lab mounts them from the competition's own input. RepoGraph-Verified (debmalya84; 221 tasks) is larger and harder and also ships snapshots and wheels, but no agent outcomes or calibration; toasterson's set ships ids and rebuild scripts, sslasme's ids only.

## 3. The protocol

### 3.1 Paired comparison and its power

Both bundles run on the same tasks in the same kernel; we report the tasks only one arm solved, an exact McNemar test and a 95% paired bootstrap interval, as Miller (2024, *Adding Error Bars to Evals*) recommends. Across our four 31B comparisons, 13% of tasks were discordant. Computing exact McNemar power at that discordance (α = 0.05 two-sided, power 0.8):

| Paired tasks | Smallest gain detectable (solve-rate points) |
|---|---|
| 24 or 48 | none: 3–6 tasks differ, too few even if all favour the candidate |
| 87 | 11 |
| 155 | 9 |
| 300 | 7 |
| 600 | 5 |

The table depends only on the discordance d, so it holds for any paired agent comparison: a gain Δ needs about 8d/Δ² tasks (within 5% of exact), and at d = 0.13 nothing is detectable below 60 tasks, the size of many comparisons published here (earlco 16, AfterFix 24, sslasme 41, Idris 46). Unchanged bundles run twice disagreed on 5 of 60 tasks (v29) and 11 of 76 (v33t: 34 against 29 solves).

At the leaderboard's ~0.43× exchange rate (§3.3), a 9-point gain is about 4 leaderboard points (2.3 of 58 tasks), roughly the gap between our best draw (0.18) and the many teams at 0.22.

**Rule.** Below this resolution the gate never accepts a change on solves alone: it needs a visible mechanism (fewer loops or empty patches, new failures only on tasks the base also failed), outside evidence pointing the same way, and no time failure (§3.2).

### 3.2 Scorer time

**Fit.** We fitted the per-step cost model on 1,441 LLM steps (64 of them compactions) from two kernels that ran the same 12 public competition tasks sequentially on the real clock, as the scorer does (v28, v29, and v29 with 36 calls); those runs are not redistributable, so only the fitted constants are released.

**Accuracy.** Predicted mean task time was within −0.6% to +0.4% of measured in-sample, and +1.6% on a held-out kernel with a different architecture (v31a, a sub-agent solver).

As kazuhiro, Idris and toasterson also found, prompt length is almost free under prefix caching; a completion token costs about 29 ms, a compaction 25.4 s. A projection is 500 s plus 120 × the mean predicted task time. v29 projected 10.2 h and 11.4 h in two runs of those 12 tasks and passed the scorer three times; v28, 1.3% above v29 in the same kernel, failed. The gate therefore fails a candidate projected more than 3% above the current bundle on the same tasks and warns on any increase; 36 calls (+20%) failed without spending a slot.

### 3.3 Calibration against the leaderboard

| Bundle | Eval-set solved runs | Rate | Leaderboard draws | Leaderboard / eval |
|---|---|---|---|---|
| v29 (temperature 0.2) | 51/147 | 0.35 | 0.18, 0.15, 0.15 | 0.46 |
| v30 (thinking 2048) | 20/60 | 0.33 | 0.15 | 0.45 |
| v32 (failure-derived prompt) | 10/24 | 0.42 | 0.13 | 0.31 |
| v33t (temperature 1.0) | 54/155 | 0.35 | 0.17, 0.13, 0.15 | 0.43 |

The leaderboard scores 0.43× our rate over all eight draws (0.43–0.46 for v29, v30 and v33t), the ~2× local inflation toasterson and sslasme also report. The gate ranks v29 and v30 equal, as do their draws; v32's high rate rests on 24 tasks and its draw did not confirm it. Eight draws of four bundles give an exchange rate, not a rank correlation.

**External check.** On 27 tasks shared with zysbnd1's dev pool (8 Gemma 31B runs each, independent harness), per-task solve rates agree at r = 0.95 (bootstrap CI 0.89–0.99), at similar levels (0.43 there, 0.39 here).

## 4. What the gate decided

Each row gives counts of the n paired tasks solved by each arm.

| Change (base → candidate) | n | Base | Candidate | Base only / candidate only | Δ tasks (95% CI) | p |
|---|---|---|---|---|---|---|
| Thinking 2048 + terse thoughts (v29 → v30) | 60 | 21 | 20 | 4 / 3 | −1 (−6..+4) | 1.00 |
| Failure-derived prompt + thinking 2048 (v29 → v32) | 24 | 9 | 10 | 1 / 2 | +1 (−2..+4) | 1.00 |
| Temperature 0.2 → 1.0, top-k 64 (v29 → v33t) | 87 | 30 | 34 | 3 / 7 | +4 (−2..+10) | 0.34 |
| Thinking 2048 + 32 calls (v33t → v34), sealed split B | 68 | 20 | 21 | 5 / 6 | +1 (−5..+8) | 1.00 |
| 31B → E4B (v29 → s1), tasks before the server hang (§4.6) | 22 | 4 | 0 | 4 / 0 | −4 (−8..−1) | 0.12 |

### 4.1 Sampling: temperature 1.0, the one change adopted

On split A, Gemma's recommended sampling (temperature 1.0, top-p 0.95, top-k 64, thinking on) solved 34 tasks against 30 for temperature 0.2. Completion tokens were the same (8.9k per task), and predicted time rose 0.9% and 2.8% in the two kernels (`timepred.py`).

| Outcome | Temperature 0.2 | Temperature 1.0 |
|---|---|---|
| Solved | 30 | 34 |
| Wrong patch | 37 | 28 |
| Empty patch | 8 | 13 |
| 8-minute timeout | 8 | 12 |
| 80-turn loop | 4 | 0 |

Temperature 1.0 prevented all four loops (toasterson found it cannot break one already in context) and cut wrong patches by nine; every one of its timeouts was on a task temperature 0.2 also failed. The gain is not significant at n = 87, and §3.1 says it could not be. We adopted it for the mechanism, a time cost inside the 3% line (all three draws finished inside the 12-hour limit; their mean, 0.150 against v29's 0.160, cannot resolve 4 tasks either), and outside evidence: Idris's leaderboard jump from 0.18 to 0.24 changing sampling alone, and +3 of 129 tasks in Ayush's replay (discussion 746250); sslasme's single 41-task run, below that 60-task floor, saw no change (19 against 19). A v29 arm on split B is scheduled to pool 155 paired tasks.

### 4.2 Budgets: thinking tokens cannot be traded for calls

v34 halves the thinking budget and spends the time saved on 4 more tool calls. On the sealed split it solved 21 against 20, with the same tokens. Timeouts went from 7 to 11 and empty patches from 12 to 8, but per task the empties mostly became wrong patches (6) or solves (3), while 5 solves became timeouts or empties: more calls reshuffled outcomes without a net gain.

### 4.3 Prompts and architecture: below resolution, or too slow

**Prompt rules.** v30 (terse thoughts, batched searches) came from failure analysis of public-repo runs; v32 (edit as soon as the change is known, check every call site, thinking 2048) from the gate's own split-A failures. They moved solves by −1 and +1, far below the power table's resolution. v32 reached its mechanism (3 zero-length patches against 5–6) at 9% more tokens. We submitted it anyway, against the gate (no outside support); its draw (0.13) was the family's lowest.

**Sub-agent solver.** v31a puts a solver inside an `AgentTool`, which avoids history compaction. It failed the timing check: 353 s per task against v29's 301 and 337 s in two kernels on the same 12 real-clock tasks. The uncompacted context made every step longer (more completion tokens per call).

### 4.4 Context: the issue does not survive compaction

sslasme showed that ADK compaction erases the problem statement in 71% of runs (33% against 53% solved). Our harness compacts at 14,336 prompt tokens with ADK's default summarizer; 141 of v33t's 155 runs compacted. We add when it strikes relative to the first edit:

| First compaction vs first edit (v33t) | Runs | Solved |
|---|---|---|
| No compaction | 14 | 11 |
| First edit before compaction | 53 | 32 |
| Compaction before first edit | 76 | 11 |
| Compaction, never edited | 12 | 0 |

Difficulty confounds this (hard tasks explore longer), but half of all runs edit without the verbatim issue. The harness exposes the issue as session state (`problem_description`), so a bundle can template it into its instruction, which is never compacted. sslasme's single run of this fix (`v3_anchor`) solved 16 against 19 of 41 and drew 0.10. v35 repeats it on v33t over 87 paired split-A tasks under a rule fixed in advance, and fails: 28 solves against 34 and 29 in two v33t runs, at 1.03× time. v36, which also routes every read through capped shell slices, solved 34 at equal time but hit the call cap more often (42 against 32 runs) and failed the rule too.

### 4.5 Model size: E4B does not reach the board

A bonus prize made E4B tempting: it decodes about 2.5× faster per sequence (about 90 against 36 tokens/s single-stream). With the same bundle and sampling, E4B solved 0 of 22 tasks with 28 calls and 0 of 23 with 40, on tasks where 31B solved 4 (temperature 0.2) and 6 (temperature 1.0).

E4B patches were mostly wrong (37 of 45 runs), not empty. A redesigned bundle (s3: no list-argument tools, a fixed command recipe, 5 minutes) with §4.6's parser guard solved 1 of 12 smoke tasks, where 31B solved 2–3.

### 4.6 A vLLM parser hang that freezes the scorer

41 of the 86 E4B runs made no model call: at 12:33 UTC vLLM stopped logging and `/metrics` stopped answering.

**Cause.** vLLM 0.19.1's Gemma 4 tool parser (`vllm/tool_parsers/gemma4_tool_parser.py`) parses arguments of the form `key:<|"|>value<|"|>` with hand-written loops. In `_parse_gemma4_array`, a bare value that starts at an unmatched `]` is read as empty without advancing the index, so the loop never ends. The parser runs in the API server's event loop, so one bad response freezes every request. Others measured this parser corrupting arguments (sslasme, toasterson); corruption costs a call, a hang ends every remaining task.

**How it is reached.** The array branch is entered when a value starts with `[`, as when a model leaves code outside the string delimiters: `new_string:<|"|>x<|"|> y = {"k": [f(a[i]) for i in r]}` hangs the parser. So does a well-formed nested list whose string contains `]` (`k:[[<|"|>a]b<|"|>]]`), which exposes list-typed tools such as `get_code_subgraph`.

**How often.** Our reproducer hangs on 19 of 5,000 random short argument strings. Malformed calls (keys outside the tool's schema) do not predict it: every 31B bundle had 1.0–1.7% and never hung in 16,263 traced calls; E4B had 0.4% and 5.1% at 28 and 40 calls and froze after 516. The freezing response was never logged; the attribution rests on the reproducer.

**Fix.** Advancing the index when a bare value is empty fixes it; vLLM does so from 0.21.0 (0.20.2 still loops). Our lab generator applies that guard (`--guard-gemma4-parser`; 0 of 20,000 fuzz inputs hang) and logs would-be hangs. The scorer cannot be patched, so small-model bundles should avoid list-argument tools and long code-bearing arguments.

## 5. Related work

- **Benchmarks.** SWE-bench and SWE-bench Verified established repository-level issue resolution; SWE-rebench (Badertdinov et al., 2025), our source, mines fresh, decontaminated tasks.
- **Within the competition.** jaikwang models leaderboard noise; toasterson warns that constant-clock emulation can flip comparisons, so our clock is fitted to real sequential runs. Our call-budget and prompt-rule rejections agree with sslasme, zysbnd1, earlco and AfterFix; zysbnd1 shows empty patches are mostly a call-budget artifact. We did not test fine-tuning, which Idris, sslasme, earlco and shivashankar found to lose.

## 6. Limitations

- **Few repeats, one model family.** Only v29 and v33t were run twice (8% and 14% of tasks flipped). The §4 decisions hold for Gemma 4 under ADK on 4×L4; the procedure transfers, the decisions may not.
- **Overlap.** 62 tasks are in toasterson's held-out candidates (52 kept by both pipelines), 27 in zysbnd1's dev pool and 26 in sslasme's lists (`crosswalk.csv`); results on them are not independent.
- **Verifier.** We cannot redistribute the competition's verifier; elsewhere, grade from the released F2P/P2P lists (not yet re-validated).

## 7. Reproducibility

Attached: notebook output `anandsingh8687/sealedgate-161` (tasks and environments), dataset `anandsingh8687/sealedgate-161-runs` (outcomes, `lb.csv` with submission refs, trajectories, bundles, code) and notebook `anandsingh8687/sealedgate-161-companion`, which regenerates every table with `code/paper/analysis.py` (standard library, fixed seeds) and reproduces the hang with `code/lab/parser_hang/repro.py` against the vLLM 0.19.1 wheel. `code/lab/make_lab.py` reruns any comparison on Kaggle's 4×L4 with §2.3's clock; runs are stochastic, so reruns should agree within §3.1's discordance, not task for task.
