# SealedGate-161: a Calibrated Fresh-Repository Gate for Changing a Gemma 4 Coding Agent

**Subtitle:** 161 verified tasks from 128 unseen repositories, per-task outcomes for fourteen Gemma 4 agent bundles, a sequential-runtime model accurate to 2%, and a vLLM tool-parser hang that silently zeroes small-model runs.

## Abstract

Coding-agent changes are often accepted on a few dozen local tasks. At the 13% per-task discordance we measured between agent variants, a paired comparison on fewer than 60 tasks cannot detect any gain with 80% power. The Gemma 4 Developer Agent leaderboard is no escape: one 58-task, 11-hour draw per day, and repeats of one bundle span 0.15–0.18.

We release **SealedGate-161**:
- 161 tasks from 128 Python repositories outside the public set, each verified twice in the competition's py3.13 sandbox (45% of buildable candidates' gold patches failed there), split by repository into tuning (89) and sealed (72) halves;
- a paired protocol sized by a power table;
- a virtual clock that predicts sequential real-clock runtime within 1.6% on a held-out kernel;
- per-task outcomes for 1,397 runs of fourteen Gemma 4 31B and E4B bundles, calibrated against the leaderboard; per-task solve rates match an independent lab's (r = 0.95).

What the gate found:
- Our one adopted change did not replicate: Gemma's recommended sampling (temperature 1.0, top-k 64), +4 of 87 tuning tasks (p = 0.34) with a mechanism (loops 4 → 0) and outside support, went −4 of 68 sealed and tied over 155 (51 against 51, CI −8..+8; empty patches 16 → 27), as the power table warned: 87 tasks resolve only 11 points.
- vLLM's Gemma 4 tool parser up to 0.20.2 (the scorer pins 0.19.1) hangs on some tool-call strings, freezing every request; it likely ended 41 of 86 runs in one E4B lab.
- ADK's default compaction drops the verbatim issue: runs that compacted before any edit solved 11 of 88, the others 43 of 67.
- More calls for less thinking, failure-derived prompt rules, a sub-agent, an issue-anchored bundle (+5, then +1 and too slow) and E4B (12 solves in 231 runs) were rejected.

## 1. Introduction

A competition agent is a declarative Google ADK bundle (agent.yaml, prompt, sampling and budgets) served by vLLM on 4×L4 GPUs with a 32k context. The hidden scorer runs about 120 private-repository tasks sequentially under a 12-hour total limit; the public leaderboard scores 58 of them. Our base bundle, v29, uses temperature 0.2, a 4096-token thinking budget, 28 tool calls, 80 turns and 8 minutes per task.

The leaderboard cannot test most agent changes. It is **slow** (one draw per day), **noisy** (jaikwang's beta-binomial analysis, *Measuring the Measuring Stick*, puts the minimum detectable difference at n = 58 at 0.12–0.19) and **unforgiving on time** (our v28 projected 1.3% slower than v29, yet exceeded 12 hours and scored nothing).

The usual local sets (public examples, famous libraries) are small, partly memorised, and run on a different clock. We wanted a gate: a fixed procedure that says, before a slot is spent, whether a change is better, whether we could tell, and whether it fits in 12 hours.

**Contributions.** New here: the parser hang (§4.6), evidence that verification certifies a build, not a task (§2.1), the largest paired sampling test (155 tasks; a tuning-split lead did not replicate, §4.1), compaction timing (§4.4) and a gate-sizing rule (§3.1). Timing structure, ~2× local inflation and negative results confirm others'. The procedure carries over to any slow, noisy, time-limited agent benchmark.

## 2. The resource

### 2.1 Construction

**Candidates.** 420 candidates from 302 repositories in the SWE-rebench family (CC BY 4.0), filtered to: created after 2025-02; at most two tasks per repository; gold fix within 3 Python source files and 150 lines; at most 1.8% `async def` functions (the sandbox runs async suites unreliably); no famous or public-example repositories.

**Build.** Four CPU Kaggle kernels snapshot each repository at its base commit, freeze a uv-managed Python 3.13 environment with offline cp313 wheels, and run the official verifier on gold, empty, gold, empty. A task is kept only when gold passes and empty fails both times.

**Where candidates were lost.** 124 were dropped at build time (89 above the async limit, 29 failing dependency resolution under py3.13, 6 with wheels over 1.5 GB). Of the 296 buildable, 133 (45%) had a gold patch that did **not** pass in the competition's environment, 1 was flaky and 1 passed with the empty patch (`rejects.jsonl`). toasterson (93 of 239 built) and sslasme (294 of 1,440 kept) report similar losses. Verification certifies a build, not a task: on 105 candidates both toasterson's pipeline and ours checked, verdicts disagree on 18 (17%). Any port must re-verify in its target sandbox.

**Task text.** As in the competition, problem statements are PR-style (title and body; issue text for one task), hints are blank and the fail-to-pass and pass-to-pass lists are withheld.

### 2.2 Profile

| Property | Value |
|---|---|
| Tasks / repositories | 161 / 128 |
| Task dates | 2025-02-02 … 2026-05-12 |
| Gold patch (median) | 22 changed non-test lines (IQR 8–43, max 141); 1 source file (max 3) |
| Splits | A 89 (tuning) / B 72 (sealed), by repository, fixed seed |
| Interface-dependent tasks | 6 SWE-rebench-V2 `_interface` variants; never run |
| Licences | MIT 68, Apache-2.0 33, BSD 28, MIT-0/Unlicense 6, MPL-2.0 1, unclear 25 |

### 2.3 Lab harness

A Kaggle 4×L4 kernel serves the model with the competition's vLLM settings, compaction and tools, runs six tasks at once in docker-like sandboxes, and grades with the official verifier. Because concurrent tasks slow each other, the 8-minute limit is enforced on a **virtual clock**: each LLM step is charged

0.115 s + 28.55 ms × completion tokens + 0.335 s per 1k uncached prompt tokens,

plus 25.4 s after each history compaction, plus measured tool time; runs stop at the bundle's virtual-time limit.

### 2.4 What we release

- **Tasks:**
  - `tasks.jsonl` (competition schema, SWE-bench field names), `tasks_meta.jsonl` (source, dates, licence, F2P/P2P lists, verification log), `rejects.jsonl` and split files;
  - repository snapshots and code graphs for the 136 openly licensed tasks, rebuild recipes for the other 25, and cp313 wheels for all 161.
- **Code:** build pipeline, lab generator, clock predictor, paired statistics and the analysis behind every table.
- **Runs:** `outcomes.csv` (1,397 runs: outcome, calls, tokens, virtual and predicted seconds, malformed calls), leaderboard draws, 989 graded trajectories, `crosswalk.csv` (overlap with other sets) and all fourteen bundles.

Competition data (harness files, docker shims) is mounted from the competition's input, not redistributed. RepoGraph-Verified (debmalya84; 221 tasks) is larger and harder and ships snapshots and wheels, but no agent outcomes or calibration; toasterson's set ships ids and rebuild scripts, sslasme's ids only.

## 3. The protocol

### 3.1 Paired comparison and its power

Both bundles run on the same tasks in the same kernel; we report tasks only one arm solved, an exact McNemar test and a 95% paired bootstrap interval, as Miller (2024, *Adding Error Bars to Evals*) recommends. Across our first four 31B comparisons, 13% of tasks were discordant. Exact McNemar power at that discordance (α = 0.05 two-sided, power 0.8):

| Paired tasks | Smallest gain detectable (solve-rate points) |
|---|---|
| 24 or 48 | none: 3–6 tasks differ, too few even if all favour the candidate |
| 87 | 11 |
| 155 | 9 |
| 300 | 7 |
| 600 | 5 |

The table depends only on the discordance d, so it holds for any paired agent comparison: a gain Δ needs about 8d/Δ² tasks (within 5% of exact), and at d = 0.13 nothing is detectable below 60 tasks, the size of many comparisons published here (earlco 16, AfterFix 24, sslasme 41, Idris 46). Unchanged bundles rerun disagreed on 5 of 60 tasks (v29), 11 of 87 (v33t, split A: 34 against 29 solves) and 9 of 68 (split B: 20 against 17).

**Rule.** Below this resolution, solves alone never justify a change. Our first rule let a visible mechanism (fewer loops or empty patches) plus outside evidence stand in for significance; it adopted temperature 1.0, which then tied over 155 tasks (§4.1). Now split-A evidence only earns a sealed-split run, where the candidate must meet criteria fixed beforehand, time included (§3.2), or the base stays.

### 3.2 Scorer time

**Fit.** The per-step cost model is fitted on 1,441 LLM steps (64 compactions) from two kernels that ran the same 12 public competition tasks sequentially on the real clock, as the scorer does (v28, v29, and v29 with 36 calls); only the constants are redistributable.

**Accuracy.** Predicted mean task time was within −0.6% to +0.4% of measured in-sample, and +1.6% on a held-out kernel (v31a, a sub-agent architecture).

As kazuhiro, Idris and toasterson also found, prompt length is almost free under prefix caching. A projection is 500 s plus 120 × the mean predicted task time. v29 projected 10.2 h and 11.4 h in two runs and passed the scorer three times; v28 (+1.3%, same kernel) failed. The gate therefore fails a candidate projected more than 3% above the current bundle on the same tasks and warns on any increase; 36 calls (+20%) failed without spending a slot.

### 3.3 Calibration against the leaderboard

| Bundle | Eval-set solved runs | Rate | Leaderboard draws | Leaderboard / eval |
|---|---|---|---|---|
| v29 (temperature 0.2) | 51/147 | 0.35 | 0.18, 0.15, 0.15 | 0.46 |
| v30 (thinking 2048) | 20/60 | 0.33 | 0.15 | 0.45 |
| v32 (failure-derived prompt) | 10/24 | 0.42 | 0.13 | 0.31 |
| v33t (temperature 1.0) | 54/155 | 0.35 | 0.17, 0.13, 0.15 | 0.43 |

Eval-set runs predate v35 and §4.1's split-B arm. The leaderboard scores 0.43× our rate over all eight draws, the ~2× local inflation toasterson and sslasme also report, so §3.1's 9 points is about 4 leaderboard points: our best draw (0.18) against the many teams at 0.22. The gate and draws cannot separate v29, v30 and v33t; v32's draw did not confirm its 24-task rate. Eight draws of four bundles give an exchange rate, not a rank correlation.

**External check.** On 27 tasks shared with zysbnd1's dev pool (8 Gemma 31B runs each, independent harness), per-task solve rates agree at r = 0.95 (bootstrap CI 0.89–0.99), at similar levels (0.43 there, 0.39 here).

## 4. What the gate decided

Base and Candidate count paired tasks solved.

| Change (base → candidate) | n | Base | Candidate | Base only / candidate only | Δ tasks (95% CI) | p |
|---|---|---|---|---|---|---|
| Thinking 2048 + terse thoughts (v29 → v30) | 60 | 21 | 20 | 4 / 3 | −1 (−6..+4) | 1.00 |
| Failure-derived prompt + thinking 2048 (v29 → v32) | 24 | 9 | 10 | 1 / 2 | +1 (−2..+4) | 1.00 |
| Thinking 2048 + 32 calls (v33t → v34), split B | 68 | 20 | 21 | 5 / 6 | +1 (−5..+8) | 1.00 |
| Temperature 0.2 → 1.0, top-k 64 (v29 → v33t), split A | 87 | 30 | 34 | 3 / 7 | +4 (−2..+10) | 0.34 |
| Same, split B | 68 | 21 | 17 | 5 / 1 | −4 (−9..+0) | 0.22 |
| Same, pooled | 155 | 51 | 51 | 8 / 8 | 0 (−8..+8) | 1.00 |
| Issue in instruction, shell-only reads (v33t → v36), pooled; too slow | 155 | 46 | 52 | 8 / 14 | +6 (−3..+15) | 0.29 |
| 31B → E4B as deployed (v33t → s3), split A | 87 | 29 | 6 | 25 / 2 | −23 (−32..−14) | <0.001 |

### 4.1 Sampling: adopted on split A, tied on 155

Gemma's recommended sampling (temperature 1.0, top-p 0.95, top-k 64, thinking on) against temperature 0.2:

| Outcome (temperature 0.2 → 1.0) | Split A (87) | Sealed B (68) | Pooled (155) |
|---|---|---|---|
| Solved | 30 → 34 | 21 → 17 | 51 → 51 |
| Wrong patch | 37 → 28 | 29 → 30 | 66 → 58 |
| Empty patch | 8 → 13 | 8 → 14 | 16 → 27 |
| 8-minute timeout | 8 → 12 | 9 → 6 | 17 → 18 |
| 80-turn loop | 4 → 0 | 1 → 1 | 5 → 1 |

On split A its loops fell 4 → 0 at equal tokens and 0.9–2.8% more predicted time. §3.1 said +4 of 87 could not be significant; we adopted it anyway on that mechanism and outside evidence: Idris's leaderboard jump from 0.18 to 0.24 changing sampling alone, and +3 of 129 tasks in Ayush's replay (discussion 746250).

The pre-registered split-B arm reversed the sign; only the empty-patch rise replicated. Per split, temperatures differed on fewer tasks than v33t's reruns (10 and 6 against 11 and 9). Pooled, they tie; the interval (−8..+8 tasks) excludes a 9-point gain, not split A's lead. Neither the draws (mean 0.150 against v29's 0.160) nor sslasme's 41 tasks (19 against 19) resolve it. A plausible mechanism, outside support and +4 of 87 did not make a gain; shifted failure kinds are not solves. As pre-registered, v33t and v29 stay our finals.

### 4.2 Budgets: thinking tokens cannot be traded for calls

v34 halves the thinking budget to fund 4 more tool calls. On the sealed split it solved 21 against 20 at equal tokens (timeouts 7 → 11, empties 12 → 8); per task, empties mostly became wrong patches (6) or solves (3) while 5 solves became timeouts or empties: more calls reshuffled outcomes without a net gain.

### 4.3 Prompts and architecture: below resolution, or too slow

**Prompt rules.** v30 (terse thoughts, batched searches) came from failure analysis of public-repo runs; v32 (edit as soon as the change is known, check every call site) from the gate's own split-A failures. They moved solves by −1 and +1, far below resolution. v32 reached its mechanism (3 zero-length patches against 5–6) at 9% more tokens; submitted against the gate, it drew 0.13, the family's joint lowest.

**Sub-agent solver.** v31a puts a solver inside an `AgentTool`, avoiding history compaction, and failed the timing check: 353 s per task against v29's 301 and 337 s in the two real-clock kernels, as the uncompacted context lengthened every step.

### 4.4 Context: the issue does not survive compaction

sslasme showed that ADK compaction erases the problem statement in 71% of runs (33% against 53% solved). Our harness compacts at 14,336 prompt tokens with ADK's default summarizer; 141 of v33t's first 155 runs compacted. We add when it strikes relative to the first edit:

| First compaction vs first edit (v33t) | Runs | Solved |
|---|---|---|
| No compaction | 14 | 11 |
| First edit before compaction | 53 | 32 |
| Compaction before first edit | 76 | 11 |
| Compaction, never edited | 12 | 0 |

Difficulty confounds this (hard tasks explore longer), but half of all runs edit without the verbatim issue. The harness exposes the issue as session state (`problem_description`), so a bundle can template it into its instruction, which is never compacted. sslasme's run of this fix (`v3_anchor`) lost (16 against 19 of 41; draw 0.10). v35 repeats it on v33t over 87 paired split-A tasks under a rule fixed in advance, and fails: 28 solves against 34 and 29 in two v33t runs, at 1.03× time. v36, which also routes every read through capped shell slices, solved 34 at equal time but hit the call cap more often (42 against 32 runs), failing that rule too; its +5 earned a pre-registered split-B gate: ≥ +6 pooled (below §3.1's resolution) at ≤ 1.02× v33t's time. Split B's +1 (pooled p = 0.29) met that bar; v36 projected 1.049× and was never uploaded.

### 4.5 Model size: E4B does not reach the board

E4B, eligible for a bonus prize, decodes about 2.5× faster (90 against 36 tokens/s single-stream). With the same bundle, E4B solved 0 of 22 tasks with 28 calls and 0 of 23 with 40, where 31B v29 solved 4.

E4B patches were mostly wrong (37 of 45 runs), not empty. A redesigned bundle (s3: no list-argument tools, a fixed command recipe, 5 minutes on E4B's clock) solved 6 of 87 split-A tasks to v33t's 29, patching 81; temperature 0.3 (s4) solved 5.

### 4.6 A vLLM parser hang that freezes the scorer

41 of the first E4B lab's 86 runs made no model call: vLLM stopped logging and `/metrics` stopped answering.

**Cause.** vLLM 0.19.1's Gemma 4 tool parser (`vllm/tool_parsers/gemma4_tool_parser.py`) parses arguments of the form `key:<|"|>value<|"|>` with hand-written loops. In `_parse_gemma4_array`, a bare value that starts at an unmatched `]` is read as empty without advancing the index, so the loop never ends. The parser runs in the API server's event loop, so one bad response freezes every request. Others measured this parser corrupting arguments (sslasme, toasterson); corruption costs a call, a hang ends every remaining task.

**How it is reached.** The array branch is entered when a value starts with `[`, as when a model leaves code outside the string delimiters (`new_string:<|"|>x<|"|> y = {"k": [f(a[i]) for i in r]}` hangs the parser), or by a well-formed nested list whose string contains `]` (`k:[[<|"|>a]b<|"|>]]`), which exposes list-typed tools such as `get_code_subgraph`.

**How often.** Our reproducer hangs on 19 of 5,000 random short argument strings. Malformed calls (keys outside the tool's schema) do not predict it: 31B bundles had 0.6–1.6% and never hung in 28,459 traced calls; E4B had 0.4% and 5.1% at 28 and 40 calls and froze after 516. s3 and s4 never triggered the guard in 174 runs. The freezing response was never logged; the attribution rests on the reproducer.

**Fix.** Advancing the index when a bare value is empty fixes it; vLLM does so from 0.21.0. Our lab generator applies that guard (`--guard-gemma4-parser`; 0 of 20,000 fuzz inputs hang) and logs would-be hangs. The scorer cannot be patched, so small-model bundles should avoid list-argument tools and long code-bearing arguments.

## 5. Related work

- **Benchmarks.** SWE-bench and SWE-bench Verified established repository-level issue resolution; SWE-rebench (Badertdinov et al., 2025), our source, mines fresh, decontaminated tasks.
- **Within the competition.** toasterson warns that constant-clock emulation can flip comparisons, so our clock is fitted to real sequential runs. Our call-budget and prompt-rule rejections agree with sslasme, zysbnd1, earlco and AfterFix; zysbnd1 shows empty patches are mostly a call-budget artifact. We did not test fine-tuning, which Idris, sslasme, earlco and shivashankar found to lose.

## 6. Limitations

- **Few repeats, one model family.** Only v29 (split A) and v33t (each split) were rerun unchanged; 8%, 13% and 13% of tasks flipped, about as many as between 31B arms in §4. Split B has now decided three questions in two labs, weakening its seal. The §4 decisions hold for Gemma 4 under ADK on 4×L4; the procedure transfers, the decisions may not.
- **Overlap.** 62 tasks are in toasterson's held-out candidates (52 kept by both pipelines), 27 in zysbnd1's dev pool and 26 in sslasme's lists (`crosswalk.csv`); results on them are not independent.
- **Verifier.** We cannot redistribute the competition's verifier; elsewhere, grade from the released F2P/P2P lists (not yet re-validated).

## 7. Reproducibility

Attached: notebook output `anandsingh8687/sealedgate-161` (tasks and environments), dataset `anandsingh8687/sealedgate-161-runs` (outcomes, `lb.csv` with submission refs, trajectories, bundles, code) and notebook `anandsingh8687/sealedgate-161-companion`, which regenerates every table with `code/paper/analysis.py` (standard library, fixed seeds) and reproduces the hang with `code/lab/parser_hang/repro.py` against the vLLM 0.19.1 wheel. `code/lab/make_lab.py` reruns any comparison on Kaggle's 4×L4 with §2.3's clock; runs are stochastic, so reruns should agree within §3.1's discordance, not task for task.
