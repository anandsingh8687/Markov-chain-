# Public Gemma 4 agent writeups: what other teams did, and what it means for us

The papers, notebooks and datasets are all public. Other teams' private submissions and per-task scores are not, apart from their public leaderboard numbers.

**Who wrote what.** The authors of the 50 entries are named in the sections below. A few give no real name, only a Kaggle user: f0909172434, zysbnd1, sslasme, kazuhiro3381 and jaikwang.

**What we were able to read.** The notes come from public notebooks, plus small files from these datasets: openloc4, specsuff, how-far-off-replay, Idris (runs, gym and locbench), afterfix, zysbnd1 release slice, robinamirbahar artifacts, shivashankar artifacts and the nairakash files. They are saved under `(scratchpad)/writeups/`.

**What we could not read.**
- jocelyndumlao's adapter datasets return 403.
- debmalya84's task data is 10 GB plus 50 GB of wheels, so I only read its metadata.
- Several notebooks have no saved outputs. Their numbers come from released CSVs, summaries or hard-coded cells, and I mark which below.

---

## 1. Ideas that could raise our average solve rate, strongest evidence first

Reference points:
- **v33t**: v29 prompt, native tools, temperature 1.0, top_k 64, thinking budget 4096, 28 calls, 8 minutes per task.
- **Our noise level**: about 1.4–1.56 tasks per leaderboard draw.
- **Smallest difference we can detect**: about 0.10 for one paired run on 87 tasks (using jaikwang's noise model).
- **Lab numbers**: lab 22 means v33t vs v29 on 87 tasks; lab 24 means v33t vs v34 on 68 tasks.

| # | Idea | Sources and numbers | Strength | In v33t? | Test we could run |
|---|---|---|---|---|---|
| 1 | **Temperature 1.0 / top_k 64 with thinking on** | **Idris (0.24 team):** v19 0.18 → v24 0.24, one leaderboard draw each, only sampling changed.<br>**Ours:** 34 vs 30 of 87 paired (p 0.34); loops 4→0, but empty patches 15→18 and timeouts 8→12.<br>**toasterson:** loop study 3/6 vs 1/6; once 3–4 copies of a call are in context, temperature 1.0 alone does not break the loop.<br>**Against:** sslasme 19 vs 19 of 41 (one run). zysbnd1 tested temperature 1.0 at the commit step only: +0.006, an unrelated test. philgear's contrary result changed several things at once, so it says nothing. | Moderate. The direction is consistent; no single test is significant. | Yes | For the paper only: run v29 on the 68 sealed split-B tasks (one arm, about half a lab). We already have v33t on those tasks from lab 24. Pooling with lab 22 gives about 155 paired tasks. If the gain holds, it becomes our one result that no one else has. |
| 2 | **Empty patches come mostly from the call budget; force the first edit earlier** | **zysbnd1 (284 tasks, 704 runs):** 44 of 53 empty runs had every edit refused once the 28-call budget was spent, and 6 of them held a passing tree. Empty runs made their first edit at median call 28, resolved runs at 9.5. Forced commits rescue about 40% of empties on borderline tasks but only 4–6% on tasks never solved. Removing the injected commit instruction cost 7.6 points, but that was measured on forced commits, not a deployed agent.<br>**Idris:** 12/46 tasks hit the call cap, 7 of them inside 5 minutes; late first edits almost never resolve.<br>**shivashankar:** first edit at turn 11 (resolved) vs 18 (unresolved); nothing that went past 26 calls resolved.<br>**Ours:** v27 data. v32 had 3 empties vs 5–6; v34 had 8 vs 12, but its timeouts rose 7→11 and solves stayed flat. | Moderate for the mechanism, weak for the solve gain. My estimate is +1 to 2 tasks per 87. v34 shows empties tend to turn into timeouts or wrong patches, not solves. | Partly. The v29 prompt has no hard rule to edit by call N. v32 had empty-patch rules but was not built on v33t. | **CPU first:** in lab 22/24 v33t traces, count the 13 empties whose edits came after counted call 28, and find each run's first-edit call. **GPU, only if more than half are refused late:** v35 = v33t plus only v32's empty-patch rules ("edit as soon as the change is known; by call ~18 make your best edit"). Run v35 and v33t together on split A (87 tasks). Gate: 5 or more fewer empties, solves not lower, predicted time at most 1.0x. Do not add a "[call N/28]" counter prefix: sslasme found it broke tool calls on 15/40. |
| 3 | **Runs that hit the time cap are worth nothing; a slightly shorter cap is safe** | kazuhiro: 0/105 timeouts solved (0/31 even with a non-empty patch). specsuff: 0/74. Idris: 2 of 21 budget-exhausted runs resolved. zysbnd1: 20 vs 8 minutes changed nothing (+0.006, 193 tasks paired). Ours: all 12 v33t timeouts were also unsolved by v29.<br>**Against:** cutting harder hurts. meteorkid's Flexon bundle at 8→4 minutes scored 0.08; toasterson's 5.5-minute cap scored 0.12 vs 0.15 (single draws). | Strong that solves are not lost; this buys time margin, not solves. | No (8 minutes) | **No GPU:** from lab 22/24 v33t traces, list the solves that finished after 6, 6.5 and 7 minutes of predicted scorer time. If none or one, cap at 7 minutes to protect the 12-hour limit; v33t predicts +0.9 to 2.8% over v29, which had only a few percent margin. |
| 4 | **Context overflow and compaction** | jasonwold: 29/120 and 18/89 31B runs overflowed; 0/47 resolved. toasterson: 12/95 base runs died from overflow. sslasme: compaction erased the problem statement in 127/178 runs (33% vs 53% solved, confounded). | Moderate, correlational. | Partly: the harness compacts at 14336. | **CPU:** count overflow errors and compactions in v33t traces. If there are 5 or more, try one rule capping tool output (for example "pipe long output through head/tail -n 60"). |
| 5 | **Parallel attempts / best-of-2** | zysbnd1: best-of-2 with a perfect picker is +3.9 to 4.4 points. jasonwold: about +3 points. sslasme: temperature-1.0 retries rescue about 10% of failed tasks per attempt. Idris: best of 3 is +25% over one run. No team has a working way to pick the better attempt, and it costs twice the compute. | Strong that the ceiling is small. | No | **Do not build v31p.** Even with a perfect picker the gain is about our 4-point gate, and we lack the time margin. |
| 6 | **Quote-safe edits (fixing edit-argument corruption)** | sslasme: 16.5–21.9% of edit_file calls were mangled by quotes; sed/heredoc cut that to 0.4%, but solves were 17–18 of 41 (no gain). toasterson: parser failures 9.0%→1.9%, solves 47 vs 46. kazuhiro: fixing missing edit arguments did not move solves. | Strong that this does not help. | n/a | **CPU only:** measure the edit_file error rate in our traces, so the paper can report it. |
| 7 | **Raising the call cap** | Our v34 (32 calls): 21 vs 20 of 68. sslasme hard set: 40 calls 8/40 vs 11 and 9 of 40. meteorkid: 28→40 gave 0.15 vs 0.13 (single draw). Idris v25 (40 calls) has no score. | Moderate negative. | No (28) | None. Closed. |
| 8 | **Fine-tuning with LoRA** | Idris: adapters 13/46 and 9/46 vs 18/46 for the base model (25 empties in the second). sslasme: SWE-smith distillation 3–8 of 14 vs 13/14 for base; on-policy training stopped loops but gave 17/41 and leaderboard 0.15. earlco: adapters 2→3 of 8, 6→5 of 16, and one collapse 6→0. shivashankar's adapter was effectively zero and never tested alone. | Strong negative for a quick fine-tune; three independent teams. | No | **Do not try.** For the paper, cite these three as the answer to "LoRA not tried". |
| 9 | **Better localisation tools or a reranker** | GemmaLoc: even oracle localisation gave 24 vs 21 of 65 (not significant). sslasme: forced locator put a gold file in the top 3 on 37/41 tasks yet solved 19/41, same as baseline; graph tools were called 0 times. Ours: wrong-file failures are 3 of 19. OpenLoc-4, FreshLoc, prena, MutaLoc and CodeGraph-Loc measure localisation only, never solves. | Strong that this is not our bottleneck. | n/a | None. Small point: search_similar_code is clearly worse than BM25/grep (GemmaLoc hit@10 0.31 vs 0.50; tomashby). If our tool list includes it, dropping it is free, but there is no evidence it changes solves. |
| 10 | **Prompt rules (checklists, contract audit, archetype hints, self-tests)** | earlco: +0 to 2 per 16 tasks, inside their own 5–7 spread. AfterFix: checklist −1, trace prompt −2 of 24. sslasme: test-first 17/41 (14 of 30 self-passing patches failed the hidden tests); repeating the problem statement 16/41 and leaderboard 0.10. Ours: v32 +1 (noise). | Strong that individual rules are below our noise level. | n/a | None, beyond the empty-patch rule in row 2. |
| 11 | **Cheap pitfalls to check (anecdotal)** | (a) Installed site-packages shadowing the repo under test (SFD httpx, one task; manimaran). (b) Skills whose scripts run from a temporary copy can't see /workspace (woochangho, 15/15 calls). (c) disallow_transfer_* keys in agent YAML abort the submission (manimaran). (d) LiteLLM reserves max_output_tokens out of the 32k context (shivashankar). | Weak; each is a single report. | (b) and (c) don't apply: we use no skills and no such keys. | **CPU:** grep our traces for `dist-packages` in pytest/traceback paths. |
| 12 | **Stop after the tests first pass** | zysbnd1: median 40–48% of calls come after the first passing tree, yet only 1–2 failed runs were ever green at an intermediate tree. | Moderate as a time/token saving; nothing on solves. | Partly (v30 "stop after one submit") | Only if row 3 shows we need margin: a rule "when the issue example and the related tests pass, run git diff and submit". |

**Bottom line for the main track:** I found no well-evidenced idea we haven't tried that is worth more than about 1–2 tasks per 87. v33t's mean looks at or above par: independent replays of public temperature-0.2 recipes average about 0.136, roughly 8 of 58 (meteorkid). The cheap next steps need no GPU: rows 2, 3, 4 and 11, all checked from existing traces. The only GPU candidates are v35 (the empty-patch rule) and, for the paper, v29 on split B.

## 2. What the strongest teams and papers show about methods

- **Leaderboard scores.** The 0.22–0.24 scores fit best-of-many draws from bundles that average about 0.17. jaikwang estimates a 26–46% chance that a 0.17 bundle shows 0.22 or more in 5 tries. The one 0.24 team that disclosed its method (Idris) got its jump from sampling alone. The other three 0.24 teams (Yurnero, Yike Xu, SAVE) disclose nothing. Runs on public dev tasks overstate the leaderboard: toasterson about 2x, sslasme about 2x, debmalya claims 3x without a table, ours 37% vs about 17%.
- **Fine-tuning.** Every measured attempt lost or broke even: Idris, sslasme, earcho's three adapter screens (earlco), and shivashankar. Training on other models' trajectories (off-policy) collapses. Training on the model's own successful runs (on-policy) removes loops but does not add solves. The 12B model is about half of 31B (Idris 9 vs 18 of 46; sslasme 10 vs 19 of 41).
- **Localisation is not the bottleneck.** jasonwold: right place, wrong fix is the most common 31B failure (58 of 96 failed runs). sslasme: 42% wrong logic, 21% wrong file. GemmaLoc: oracle localisation did not significantly raise solves. Ours: 10 of 19 failures were right file, wrong logic.
- **Self-checking is unreliable.** Self-written tests are falsely confident (sslasme: 14 of 30 self-passing patches failed hidden tests). "It runs and is stable" is not correctness (AfterFix: all 48 wrong repairs were stable). Wrong patches are "sealed": 0/45 resolved at any fork point, and even Qwen committing from those contexts got 0/78 (zysbnd1). Retrying in the same context is wasted calls; only a fresh sample helps.
- **Breaking loops.** Thinking on every step is the fix: repeated calls fell from 593 to between 1 and 117 (kazuhiro), and repeats went from 20/20 to 0/20 in toasterson's replay probe. Temperature 1.0 helps prevent loops but cannot break one already in context. Sub-agents, critics and context resets did not help: sslasme scouts 5/24 vs 11/24, SFD a null result, philgear 0.06, our v31a. The positive loop-breaking claims (CCR) are simulated.
- **Budgets.** The call cap binds, not the clock (zysbnd1: 8 vs 20 minutes made no difference). Timeouts score nothing. Step cost is about 29–30 ms per completion token plus a fixed cost per call, and prompt length is free; four teams found this independently (kazuhiro, Idris, toasterson, us). Outcome is mostly a property of the task: 79–83% of variance is between tasks (zysbnd1). Patch size predicts difficulty (jaikwang: odds ratio 0.53 per doubling of gold lines; sslasme: 68% solved at 5 lines or fewer, 15% above 40).
- **Common problems in weak entries.** Simulated or hard-coded results: toposearch, vivy, CCR, graphnav, yssirdangou, philgear's LoRA, sovereign. Task-specific hints leaking into the dev set: shivashankar. Mock backends: amiraziz. Judges are likely to discount these, so verifiability will separate entries.

## 3. Paper-track landscape

**Overall Best Paper ($15k).** This prize is crowded with strong, reproducible entries:
1. **zysbnd1, "Task or Trajectory?"** 704 runs, 3,925 forced-commit episodes, 4 models, confidence intervals clustered by task, and every table reproduced with the standard library only. Probably the favourite.
2. **sslasme, "Beyond Localization".** 35 campaigns, 23 leaderboard submissions, fine-tuning, and an unseen benchmark. This is the closest to our paper, and it reaches several of our conclusions first.
3. **toasterson, "Where a 32k Coding Agent Loses Its Score".** Pre-registered, a 149-task held-out set, a 12-hour risk model, and a warning that clock emulation can flip comparisons.
4. Also strong: jaikwang (noise model, consensus labels), Idris ("Git History as a Gym"; 0.24 team, fine-tuning, gym), kazuhiro (timing), GemmaLoc, specsuff.

Our timing model duplicates kazuhiro, toasterson and Idris. Our negative results duplicate sslasme. Our failure breakdown duplicates jasonwold, sslasme and zysbnd1. **Do not target Overall.**

**Best New Resource ($10k).**
- **debmalya84 RepoGraph-Verified** is the direct rival: 221 "private-like" tasks from 102 repos in the exact competition format, with snapshots, graphs and wheels. It is checked with the official verifier, and it is harder than ours (median gold patch 27 lines vs 12 on the public tasks). Its weakness: its claimed leaderboard calibration (about 0.3x) and its agent results have no tables.
- **toasterson's held-out set:** same SWE-rebench-leaderboard source and dates as ours, so tasks may overlap; it adds a builder for sound environments.
- **Idris's gym:** 366 tasks, but from public libraries that ship in the sandbox.
- **sslasme rb41/H40:** task ids only; 14 of rb41's 41 tasks are in our set.
- Retrieval-only entries: OpenLoc-4, FreshLoc-129, MutaLoc, CodeGraph-Loc.
- Label sets: specsuff, jaikwang.

**Best New Application ($10k).** The only entries that fit are medium or weak: AfterFix (SQL data recovery with 31B), earlco (synthetic finance repair), TRACE. Our work is not an application, so this prize does not fit us.

**Where we are distinctive:**
1. The only controlled, full-run, paired test of temperature on 31B with thinking on (87 tasks, possibly 155 with split B), with the mechanism measured: fewer loops and wrong patches, more empties and timeouts. Idris has one leaderboard draw; sslasme has one run on 41 tasks; zysbnd1 tested the commit step only.
2. Measured calibration of our eval set against the leaderboard across about 5 bundles and repeat draws (v29, v30, v32, v33t, v34), with a sealed A/B split. debmalya has no such table.
3. A timing predictor validated within 0.8% against real-clock runs, including the v28 bundle that broke the 12-hour limit. This is the gate's 12-hour risk check, not a new timing finding.

**Recommendation: target Best New Resource.** The angle is "a decision gate, not just a test set". Release the 161 verified unseen-repo tasks in competition format together with:
- the paired-run protocol and our MDD/McNemar stats tooling;
- the timing predictor;
- per-task outcomes for all configurations we ran (including the E4B 0/43 results);
- the leaderboard draws, showing the eval set ranks configurations correctly and predicts 12-hour risk.

Use the temperature study as the worked example of the gate. To get ahead of reviewers:
- **Difficulty.** Report patch-size and statement-sufficiency profiles; apply specsuff's Axis-1 rule to our 161 tasks on CPU. Explain the 37% vs 17% gap honestly, and compare with debmalya's harder distribution.
- **Cross-dataset validity.** Show agreement on the 14 tasks we share with rb41 and on the zysbnd1 tasks with 8-run difficulty labels.
- **Licensing.** Make sure the task snapshots or build scripts are actually releasable; a resource without data loses to debmalya.

## 4. The five most useful references

1. **zysbnd1, "Task or Trajectory?"** (dataset `zysbnd1/task-or-trajectory-release-slice`): the best evidence on empty patches as a call-budget artifact, sealed wrong patches, and the small best-of-2 ceiling. It also overlaps our candidate pool, with 8-run difficulty labels per task.
2. **sslasme, "Beyond Localization"** (dataset `sslasme/gemma4-paper-certified-benchmarks`): our closest competitor. It has the largest set of negative results (fine-tuning, scouts, test-first, graph tools, 40 calls) and a temperature-1.0 null result we must address. We share 14 tasks.
3. **debmalya84/repograph-verified-swe-tasks:** the main rival for Best New Resource, and possibly a second, harder sealed gate if we attach its wheels to a lab kernel.
4. **toasterson, "Where a 32k Coding Agent Loses Its Score"** (dataset `toasterson/gemma4-agent-paper-release`): the 2x calibration of local results against the leaderboard, a 12-hour risk model, the warning about constant-clock and Ollama emulation, and the loop study.
5. **Idris, "Git History as a Gym"** (datasets `muhammedidris28/gemma4-agent-runs` and `muhammedidris28/git-history-gym`): the origin of the temperature-1.0 result, paired fine-tuning losses, and evidence that the call cap binds early. He is the only 0.24 team that discloses its method.

For the noise statistics in our paper, also cite jaikwang's "Measuring the Measuring Stick" (beta-binomial noise model; MDD 0.12–0.19 at n=58).

Files referenced:
- `/home/user/Markov-chain-/gemma_agent/STATUS.md`
- `/home/user/Markov-chain-/gemma_agent/research_1026_sampling.md`
- `(scratchpad)/writeups/`