# Sealed and Calibrated: a Fresh-Repository Gate for Changing a 12-Hour Gemma 4 Coding Agent

**Subtitle:** 161 verified tasks from 128 unseen repositories, per-task outcomes for ten Gemma 4 agent bundles, a scorer-time model accurate to 2%, and a vLLM tool-parser hang that silently zeroes small-model runs.

## Abstract

In the Gemma 4 Developer Agent competition a change to an agent is judged by one leaderboard draw per day. Each draw takes about 11 hours and scores 58 tasks, and identical bundles score anywhere from 0.15 to 0.18. Most teams therefore tune on 24–48 local tasks. We show this cannot work: with the 13% per-task discordance we measured between agent variants, a paired comparison on 48 tasks never reaches 80% power, whatever the true gain.

We release **SealedGate-161**, a resource built to make these decisions:
- 161 tasks from 128 Python repositories that do not appear in the public set, created between 2025-02 and 2026-05. They are rebuilt in the competition's exact py3.13 sandbox format. A task is kept only if the official verifier passes the gold patch twice and fails the empty patch twice; 45% of buildable candidates failed that check.
- A repository-disjoint tuning split (89 tasks) and a sealed split (72 tasks).
- A paired-run protocol with exact McNemar tests, bootstrap intervals and a power table.
- A virtual clock that lets a lab run six tasks at once yet predicts the scorer's sequential runtime within 1.6% on held-out real-clock runs.
- Per-task outcomes for 746 runs of ten agent bundles (Gemma 4 31B and E4B), calibrated against the leaderboard draws of the same bundles.

The gate's decisions:
- **Temperature.** Gemma's recommended sampling (temperature 1.0, top-k 64) beat temperature 0.2 by +4 of 87 tasks (p = 0.34). The mechanism was consistent: loops fell from 4 to 0 and wrong patches from 37 to 28.
- **Rejected changes.** Trading thinking tokens for tool calls, prompt rules derived from failure analysis, and a sub-agent architecture were all rejected; the last failed the timing check.
- **E4B.** E4B solved 0 of 42 runs on tasks where 31B solved 4–6 of 22.
- **A serving bug.** The gate also caught a defect: vLLM 0.19.1, which the scorer uses, has a Gemma 4 tool-call argument parser that loops forever on some malformed tool calls and freezes the whole server. E4B emits malformed calls on 2–11% of tool calls, against 1–1.7% for 31B. Later vLLM releases guard against it; we give a reproducer and show how often each model triggers it.

## 1. Introduction

A competition agent is a declarative Google ADK bundle (agent.yaml, a system prompt, sampling and budget settings) served by vLLM on 4×L4 GPUs with a 32k context. The hidden scorer runs about 120 tasks from private repositories one after another, under a 12-hour total limit and the bundle's per-task limits (we use 8 minutes and 28 tool calls). The public leaderboard scores 58 of those tasks.

Three properties of this setup make most agent changes untestable on the leaderboard:

1. **Slow.** One submission per day, and about 11 hours per draw.
2. **Noisy.** Three draws of the same zip scored 0.18, 0.15 and 0.15, a spread of about 2 tasks. An independent beta-binomial analysis puts the minimum detectable difference at n = 58 at 0.12–0.19 (jaikwang, *Measuring the Measuring Stick*).
3. **Unforgiving on time.** A bundle that uses 7% more time than a passing one can exceed the 12-hour limit and score nothing. That happened to our v28.

Local evaluation is the obvious answer, but the usual local sets (the public example repositories, or SWE-bench-style tasks on famous libraries) are small, partly memorised, and run on a different clock.

We wanted a gate: a fixed procedure that says, before a submission slot is spent, whether a change is better, whether we could even tell, and whether it fits in 12 hours.

**Contributions.**
1. **SealedGate-161** (§2): the task set, build pipeline, and sealed split.
2. **A paired protocol** (§3.1) with a measured power table, showing how many tasks a decision needs.
3. **A scorer-time model** (§3.2) that turns concurrent lab runs into sequential scorer time.
4. **Calibration** of the gate against the leaderboard (§3.3).
5. **Six gate decisions** with per-task data and mechanisms (§4), including a serving bug that matters to anyone running small Gemma 4 models behind vLLM's tool parser.

## 2. The resource

### 2.1 Construction

**Candidates.** We started from 420 candidates from 302 repositories in the SWE-rebench family: the SWE-rebench leaderboard set, SWE-rebench-V2 and SWE-rebench, all CC BY 4.0. Filters:
- task created after 2025-02;
- at most two tasks per repository;
- the gold fix touches at most 3 Python source files and at most 150 lines;
- at most 1.8% of the repository's functions are `async def`, because the sandbox's test runner is unreliable with async-heavy suites;
- no famous or public-example repositories.

**Build.** Each candidate is rebuilt for the competition sandbox by four parallel CPU Kaggle kernels:
- a bare mirror is snapshotted at the base commit;
- a uv-managed Python 3.13 environment is created and frozen;
- cp313 wheels are downloaded for offline installation;
- the official verifier then runs four times: gold patch, empty patch, gold, empty.

A task is kept only when the gold patch passes 2 of 2 and the empty patch fails 2 of 2.

**Where candidates were lost.** 124 failed to build: dependency resolution under py3.13, async share above the limit, or wheels over 1.5 GB. Another 133 of the 296 buildable candidates (45%) had a gold patch that did **not** pass in the competition's environment, and 2 failed the check for other reasons. Anyone reusing SWE-rebench rows with this harness without verification is therefore scoring against a large share of unsolvable tasks.

**Task text.** Problem statements are PR-style, mirroring the competition's format:
- for 160 of 161 tasks, the PR title and body (87 from the GitHub API, 73 from SWE-rebench-V2);
- 1 falls back to the issue text.

Hints are blank, and the fail-to-pass and pass-to-pass test lists are withheld from the agent, as on the scorer.

### 2.2 Profile

| Property | Value |
|---|---|
| Tasks / repositories | 161 / 128 |
| Task dates | 2025-02-02 … 2026-05-12 |
| Gold patch, changed source lines | median 22 (IQR 8–43, max 141) |
| Gold source files | median 1, max 3 |
| Repository stars | median 851, 90th percentile 6,038 |
| Splits | A 89 (tuning) / B 72 (sealed), split by repository with a fixed seed |
| Interface-dependent tasks | 6 flagged; excluded from comparisons |
| Gold verification time | median 49 s |
| Licences | MIT 68, Apache-2.0 33, BSD 28, MIT-0/Unlicense 6, MPL-2.0 1, unclear 25 |

Solve rate barely depends on patch size in this range. Across all 31B runs it was:

| Gold lines | 0–10 | 11–30 | 31–80 | 81+ |
|---|---|---|---|---|
| Solve rate | 0.38 | 0.39 | 0.24 | 0.35 |

The set is easier than the hidden one (§3.3).

### 2.3 Lab harness

A Kaggle 4×L4 kernel serves the competition model with the competition's vLLM settings, compaction configuration and tool set. It runs six tasks at once, each in its own docker-like sandbox built from the task snapshot and its wheel set, and grades with the official verifier.

Because six concurrent tasks slow each other, the lab does not use wall time for the 8-minute limit. It uses a **virtual clock**: each LLM step is charged

0.115 s + 28.55 ms × completion tokens + 0.335 s per 1k uncached prompt tokens,

plus 25.4 s after each history compaction, plus measured tool time. The agent is stopped when virtual time reaches the bundle's limit. §3.2 describes how these constants were fitted.

### 2.4 What we release

- **Tasks:**
  - `tasks.jsonl` (competition schema) and `tasks_meta.jsonl` (source, dates, licence, F2P/P2P lists, verification log);
  - split files;
  - repository snapshots and wheel sets for the 136 tasks with an open-source licence;
  - for the 25 tasks with unclear licences, the repository URL and base commit, with the build script to recreate them.
- **Code:** the build pipeline, lab kernel generator, virtual-clock predictor (`timepred.py`), paired statistics (`stats.py`) and the analysis behind every table here (`paper/analysis.py`, standard library only).
- **Outcomes:** `outcomes.csv`, one row for each of the 746 runs (lab, bundle, model, task, outcome, calls, tokens, predicted scorer seconds), plus the leaderboard draws.
- **Bundles:** the ten agent bundles that were compared.

We do not redistribute competition data (harness files, docker shims); the lab mounts them from the competition's own input.

## 3. The protocol

### 3.1 Paired comparison and its power

Every comparison runs both bundles on the same tasks in the same kernel. We report:
- the number of tasks only the base solved and only the candidate solved;
- an exact McNemar test;
- a 95% paired bootstrap interval of the difference.

Across our four 31B comparisons, 13% of tasks were discordant: one arm solved the task and the other did not. Simulating exact McNemar tests at that discordance (α = 0.05 two-sided, power 0.8):

| Paired tasks | Smallest gain detectable (solve-rate points) |
|---|---|
| 24 or 48 | none: power never reaches 0.8 |
| 87 | 12 |
| 155 | 9 |
| 300 | 7 |
| 600 | 5 |

Since the leaderboard scores about 0.45× our eval-set rate (§3.3), a 9-point gate gain is about 4 leaderboard points, or 2.4 of 58 tasks. That is roughly what separates the 0.18 and 0.22 clusters.

**Rule.** The gate never accepts a change on solves alone below this resolution. It accepts small or null solve effects only when they come with a clear mechanism (fewer loops, fewer empty patches) and no time cost. It rejects changes that cost time.

### 3.2 Scorer time

**Fit.** We fitted the per-step cost model on 1,433 LLM steps from two kernels that ran tasks sequentially on the real clock, as the scorer does (lab 17: v28, v29, and v29 with 36 calls).

**Accuracy.** Predicted mean task time was within −0.6% to +0.4% of measured in-sample. On a later held-out real-clock kernel with a different architecture (v31a, a sub-agent solver), it was +1.6%.

**What we learned from the fit:**
- Prompt length is almost free thanks to prefix caching.
- Completion tokens and history compactions are what cost time.
- v28's projected 11.5 h for 120 tasks was enough to fail the real scorer, while v29's 10.2–11.4 h passed three times. We therefore treat a projected 11.0 h as the safety line.
- v29 with 36 calls projects to 12.2 h, so the gate rejected it before it could waste a slot.

### 3.3 Calibration against the leaderboard

| Bundle | Eval-set solves | Rate | Leaderboard draws | Leaderboard / eval |
|---|---|---|---|---|
| v29 (temperature 0.2) | 51/147 | 0.35 | 0.18, 0.15, 0.15 | 0.46 |
| v30 (thinking 2048) | 20/60 | 0.33 | 0.15 | 0.45 |
| v32 (failure-derived prompt) | 10/24 | 0.42 | 0.13 | 0.31 |
| v33t (temperature 1.0) | 54/155 | 0.35 | *(pending)* | |

The eval set is easier than the hidden set: the leaderboard scores about 0.45× our rate. This is consistent with toasterson's and sslasme's reports of about 2× inflation for local sets.

The gate ranks v29 and v30 as equal, and so do their draws. v32's high gate rate rests on only 24 tasks and was not confirmed by its single draw, which shows why we now require ≥ 87 paired tasks.

Five draws of three bundles cannot establish rank correlation, and we make no claim about it. What the calibration does give is an exchange rate, and a demonstration that a 24-task gate overstates.

## 4. What the gate decided

All comparisons exclude the six interface-dependent tasks. Each row gives counts of the n paired tasks solved by each arm.

| Change (base → candidate) | n | Base | Candidate | Base only / candidate only | Δ (95% CI) | p |
|---|---|---|---|---|---|---|
| Thinking 2048 + terse thoughts (v29 → v30) | 60 | 21 | 20 | 4 / 3 | −1 (−6..+4) | 1.00 |
| Failure-derived prompt rules (v29 → v32) | 24 | 9 | 10 | 1 / 2 | +1 (−2..+4) | 1.00 |
| Temperature 0.2 → 1.0, top-k 64 (v29 → v33t) | 87 | 30 | 34 | 3 / 7 | +4 (−2..+10) | 0.34 |
| Thinking 2048 + 32 calls (v33t → v34), sealed split B | 68 | 20 | 21 | 5 / 6 | +1 (−5..+8) | 1.00 |
| 31B → E4B (v29 → s1), tasks run before the hang | 22 | 4 | 0 | 4 / 0 | −4 (−8..−1) | 0.12 |
| v29 → v30 on an older public-repo dev set | 73 | 32 | 30 | 5 / 3 | −2 (−8..+3) | 0.73 |

### 4.1 Sampling: temperature 1.0 is the one change with a mechanism

On split A, Gemma's recommended sampling (temperature 1.0, top-p 0.95, top-k 64, thinking on) solved 34 tasks against 30 for temperature 0.2. Completion tokens were the same (8.9k per task), and predicted scorer time rose only 0.9–2.8%.

| Outcome | Temperature 0.2 | Temperature 1.0 |
|---|---|---|
| Solved | 30 | 34 |
| Wrong patch | 37 | 28 |
| Empty patch | 8 | 13 |
| 8-minute timeout | 8 | 12 |
| 80-turn loop | 4 | 0 |

The higher temperature broke all four repetition loops and turned nine wrong patches into other outcomes. Some of those became solves; others ran out of budget. Every timeout under temperature 1.0 was on a task temperature 0.2 also failed.

On its own the gain is not significant at n = 87, and §3.1 says it could not be. We adopted it because:
- the mechanism is visible;
- time stays inside the safety line;
- it agrees in direction with the only other paired evidence: a public team's leaderboard jump from 0.18 to 0.24 when changing sampling alone, and +3 of 129 tasks in a public local replay.

A second split-B arm is running to pool 155 tasks.

### 4.2 Budgets: thinking tokens cannot be traded for calls

v34 halves the thinking budget and spends the time saved on 4 more tool calls. On the sealed split it solved 21 against 20, with the same tokens. Timeouts went from 7 to 11 and empty patches from 12 to 8. The extra calls turned empty patches into timeouts, not solves.

Raising the call cap to 36 instead projected to 12.2 h on the real-clock kernel (lab 17) and was rejected on time alone.

### 4.3 Prompts and architecture: below resolution, or too slow

**Prompt rules.** Two prompt revisions came from the gate's own failure analysis:
- v30: terse thoughts and batched searches;
- v32: edit as soon as the change is known, and check every call site.

They moved solves by −1 and +1, which is all the power table can resolve at n = 60 and n = 24. v32 did achieve its mechanism (3 empty patches against 5–6) but cost 9% more tokens. We submitted it anyway, against the gate's time warning, and its draw (0.13) was the lowest of the family.

**Sub-agent solver.** v31a puts a solver inside an `AgentTool`, which avoids history compaction. It failed the timing check: 353 s per task against 319 s on the same 12 real-clock tasks. The uncompacted context made every step slower and longer, which outweighed the compaction savings.

### 4.4 Model size: E4B does not reach the board

The bonus prize for E2B/E4B made the small model tempting: it decodes about twice as fast per sequence (65 against about 35 tokens/s). With the same bundle and sampling, E4B solved 0 of 22 tasks with 28 calls and 0 of 22 with 40, on tasks where 31B solved 4 (temperature 0.2) and 6 (temperature 1.0).

E4B patches were mostly wrong (37 of 45 runs), not empty. Its failures were basic: shell syntax such as `head - 5`, `grep` on a directory without `-r`, and edits whose old text did not match.

### 4.5 A serving bug the gate found by accident

Half of the E4B runs made no model call at all and timed out. The kernel's metrics show what happened:
- at 12:33 UTC, vLLM stopped logging and `/metrics` stopped answering;
- the machine sat at a load average of 1.0 for three hours;
- every task started after that point waited for a response that never came.

**Cause.** vLLM 0.19.1's Gemma 4 tool parser (`vllm/tool_parsers/gemma4_tool_parser.py`) parses arguments of the form `key:<|"|>value<|"|>` with hand-written loops. In `_parse_gemma4_array`, a bare value that starts at an unmatched `]` is read as empty without advancing the index, so the loop never ends.

**How it is reached.** The array branch is entered when an argument value starts with `[`. That happens when a model leaves code outside the string delimiters, for example by writing plain quotes, which E4B often does. Real code is enough: `new_string:<|"|>x<|"|> y = {"k": [f(a[i]) for i in r]}` hangs the parser.

**Why it freezes everything.** The parser runs inside the API server's event loop, so one bad response freezes every request.

**How often it can happen.** Our reproducer (released) hangs on 19 of 5,000 random short argument strings. We also counted tool calls whose parsed arguments are malformed (unknown keys, or keys with quotes in them):

| Run | Malformed calls |
|---|---|
| E4B, 28 calls | 1.9% |
| E4B, 40 calls | 10.9% |
| 31B v29 | 1.0% |
| 31B v33t | 1.5–1.7% |
| 31B v34 | 1.5% |

31B never hung in about 14,000 traced tool calls, while E4B hung within about 520.

**Fix.** Advancing the index (or aborting) when a bare value is empty fixes it, and later vLLM releases do this. Until the scorer moves past 0.19.1, small-model bundles should be designed to minimise malformed calls: fewer and shorter code-bearing arguments, and no long-context drift. Small-model runs that end in "Notebook Threw Exception" or exceed the time limit should be read with this failure in mind.

## 5. Related work

- **Benchmarks.** SWE-bench and SWE-bench Verified established repository-level issue resolution. SWE-rebench (Badertdinov et al., 2025) supplies continuously mined, decontaminated tasks; our candidates come from it. We add re-verification in the target sandbox (45% attrition) and calibration against a hidden board.
- **Statistics.** Miller (2024, *Adding Error Bars to Evals*) argues for paired tests and power analysis in LLM evaluation; we apply them to agent bundles under a time limit.
- **Within the competition:**
  - jaikwang models leaderboard noise;
  - toasterson pre-registers a held-out set and a 12-hour risk model, and warns that constant-clock emulation can flip comparisons; our virtual clock is fitted to real sequential runs for that reason;
  - debmalya84 releases 221 harder competition-format tasks without agent outcome tables;
  - zysbnd1, sslasme and Idris report many of the same negative results (fine-tuning, call caps, prompt rules) on other task sets, which our sealed-split results corroborate;
  - Idris first reported the sampling result on the leaderboard.
- **Serving.** Later vLLM releases guard the array parser against this case (0.32.0 aborts with "made no progress … malformed input"), but the competition scorer pins 0.19.1, where it still applies.

## 6. Limitations

- **Easier than the hidden set.** The eval set is easier than the hidden set (§3.3). Rates should be converted with the measured ratio, not compared directly.
- **One run per arm.** Each arm was run once. Repeat runs would separate task difficulty from sampling noise, which matters at temperature 1.0.
- **Few leaderboard draws.** Five draws calibrate a ratio, not a ranking.
- **Possible overlap.** Tasks drawn from the SWE-rebench leaderboard may overlap with other teams' held-out sets from the same source.
- **Licences.** 25 tasks have unclear licences and are released as rebuild recipes rather than snapshots.
- **E4B evidence.** The E4B result comes from 22 tasks before the server hang.

## 7. Reproducibility

Every table is regenerated by `python paper/analysis.py --meta tasks_meta.jsonl` from the released `outcomes.csv` and `lb.csv`, using only the standard library. The parser hang is reproduced by `lab/parser_hang/repro.py` against the vLLM 0.19.1 wheel. The lab kernel generator (`lab/make_lab.py`) rebuilds any comparison on Kaggle's 4×L4 from the released tasks and bundles.
