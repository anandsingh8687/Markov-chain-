# Strategy 10-18: merged plan
# One plan for public LB ≥ 0.25 (stretch 0.30) by 2026-12-02

**Summary**
- **Where we stand.** We are at the level of the best public recipes, not behind them. Every public bundle that was scored at least twice with identical files averages 8.75–10.3 of the 58 public tasks. v29 averages 10.0 (draws of 11 and 9). The 0.22 and 0.24 entries on the board are each team's best of many draws. The teams at 0.22 have a median of 11 submissions; v29 has 2 draws. [F]
- **Honest outlook.** No lever with evidence behind it adds the +5 tasks a true average of 0.25 needs. My central estimate for the final bundle is an average of about 11 tasks (0.19), with an 80% range of 10 to 12.3.
  - Chance the public board shows ≥0.25 at least once: about 20–50%, around 35% in the middle case.
  - Chance it shows ≥0.30 (18 tasks): about 0.2–2%.
  - Chance it shows ≥0.22: about 0.9.
  - Upside: if the two-attempt design gains ≥5 points on the new eval set, the average is about 12.5 and the chance of showing 0.25 rises to 0.7–0.9.
  - Sources: `merge_plan/mixture_out.txt`, `merge_plan/odds_out.txt`.
- **The lever is time and compute per task, not prompt wording.**
  - Inside the 12 h limit, the number of tool calls is what runs out.
  - 14% of v29's time is wasted.
  - The scorer's 4 GPUs run one generation stream, about a quarter of what they can generate at once.
  - So the plan is: first recover the waste (v31a), then spend a second parallel stream on a second, different attempt and pick between the two with a simple rule (v31p).
- **Method change.** Measurement gets fixed first. Each test is then judged only on what it can actually detect. The eval set checks mechanisms, time and big regressions. Repeat leaderboard draws pick between the last two candidates.

Grades: **[F]** = checked in files (in this pass or earlier ones), **[I]** = inference.

## 1. Diagnosis

| # | Finding | Evidence | Grade |
|---|---|---|---|
| 1 | We are at the ceiling of the public recipes. | Repeat draws with identical files (`strat/forum/nbtxt/dariushafshar__gemma-4-lb-58-tasks-bronze-is-a-124-team-tie.txt:893-922`): Budget-Fit 11,11,11,10,8,10,10 (mean 10.14); the "0.22" V10 bundle 13,7,9 (mean 9.67), plus 9 and 10 reported in comments (kozykappa notebook, line 19); SuperAgent-V8 8,12,11 (10.33). v29: 11, 9. One draw varies by 1.43–1.78 tasks (SD; same notebook, line 861). | F |
| 2 | The 0.22/0.24 entries are best-of-many-draws. | Leaderboard 10-18: 2 teams at 0.24 (16 and 7 submissions), 27 at 0.22 (median 11), 108 at 0.20, 341 at 0.18. With a true average of 10, P(≥13 in one draw) is 4–9%, so over 11 draws it is 36–63%. A team averaging 12 with 10 draws would show ≥0.24 80% of the time and ≥0.25 34% of the time (`odds_out.txt` §3). Nobody shows 0.25. That fits no rival having a true average much above 12. | F (counts), I |
| 3 | Our 10 h + 15 h test cycles kept returning noise because the lab cannot see the effects we test. | The fastapi/rich lab only detects changes of ≥8 of 73 tasks. Only 19 of its 73 tasks ever change between runs. Its ranking contradicted the leaderboard: v26t vs v29 was 20 vs 21 in the lab but 5 vs 10 on the leaderboard. Every change we tested was expected to move +1–3 tasks. (`strat/evidence_review`) | F |
| 4 | The binding constraint is time per task under 12 h. | v29 takes 318.6 s/task on the real clock; v28 took 343.4 s and failed the 12 h limit. On the same 12 tasks the gap was only 6.9 s (`throughput/seq_out.txt`). 51% of v29 runs end because they hit the 28-call cap. On 129 public tasks, 25 calls vs 50 calls solved 36 vs 50 (topic 746250): each 1% more calls gives about 0.47% more solves. | F |
| 5 | 14% of the clock is wasted, and about ¾ of the GPUs' generation capacity sits unused. | History summarizing ("compaction"): 1.21 events × 25.1 s = 30.4 s/task. Calls after `submit_patch`: 13.8 s/task. Generation speed is 34.5 tokens/s with 1 stream, 62 with 2, and 124–137 total with 6 (`throughput/{compaction_out,kmodel_out,vllm_conc_out}.txt`). | F |
| 6 | On the hidden tasks, most failures are probably "never edited" or "edited the wrong place". | Estimated split: 30–40% never edited, 25–35% wrong location, 25–40% wrong logic. In the lab, v29 produced an empty patch in 40 of 218 runs (18%). | I (lab rate F) |
| 7 | Several levers are blocked or have negative evidence. | **LoRA:** an adapter solved 2/32 vs 4/32 for the base model; a rank-16 bundle ran past 12 h; LoRA generates about 11% slower (749191). **12B model:** 4 scorer exceptions, no scored run. **Sampling several answers at once:** the config schema rejects `candidate_count`. **ParallelAgent in the main session:** crashes (ADK issue #7324; our v24 crashed on 7/48). **Graph tools:** all 21 semantic searches returned nothing (746250). **Stronger models:** only +4–5 of 124 tasks (747168). | F |

Checked in this pass:
- **Workers inside an `agent_tool` are never compacted and see the task.** The sub-agent runs in a fresh Runner with no compaction config, and the parent's session state is copied in, so `{problem_description}` is available (`wh31/.../google/adk/tools/agent_tool.py:203-262`).
- **The scorer's vLLM limits the reply length instead of rejecting long prompts.** A 29,808-token prompt was served with `max_output_tokens` 8192 (`lab16aout/lab/v29/r0/traces/trace_rich_3944.json`). So the real ceiling is the 32k context, and about 5% of v29-sized runs would exceed it without compaction.
- **Public and private scores come from the same 12 h run, and the 12 h includes server start-up** (host, `oct15/forum/topic_745805.json`).

Two research claims are corrected:
- The evidence review's "+3 tasks from the 0.22 prompt structure", which was Plan 2's main lever, is refuted by row 1. Without the author's own selected draw, byte-identical V10 files average 8.75.
- Plan 1's 8-run factorial prompt screen cannot find anything. With 2 runs per arm, the eval set only detects a difference of 5.6–6.9 points (n=150, 12–18% of tasks flipping between identical runs; `merge_plan/power.py`). Each factor's expected effect is only 0.3–1.4 points.

**What separates us from 0.22/0.24:** the number of draws (2 vs a median of 11) and luck, not a better recipe. **What separates us from a real 0.25:** +5 tasks on the average (+50%), which nobody has shown.

## 2. The plan

### Rules for every test
1. Each GPU run answers one question. Its pass/fail rule is written before launch.
2. The eval set decides only what it can measure:
   - time (precise);
   - crashes and context overflow;
   - mechanism numbers: the two-attempt "oracle" gain (precise to about ±1 point) and the empty-patch rate;
   - large solve-rate changes (it can only detect differences of about 6–10 points).
   It never chooses between bundles that are within about 3 tasks of each other.
3. Between the last two candidates, leaderboard draws decide. Six draws each detect a difference of about 1.75 tasks (one-sided α 0.1, 80% power, SD 1.43).
4. Nothing is submitted if it is slower than v29 on the same tasks under the corrected clock, except planned smoke tests. v29 has at most about 5% time margin.

### Levers, ranked by expected gain per cost and by evidence

Gains are in tasks out of 58, with the 80% range in brackets.

| Rank | Lever | Expected gain | Evidence | Cost | Decision |
|---|---|---|---|---|---|
| 0 | Eval set from repos the model hasn't seen, plus a corrected lab clock and a stats tool | Enables everything else | F: the current lab does not predict the leaderboard | 2–3 days, ~20 CPU-h, ~14 GPU quota-hours to calibrate | Do first |
| 1 | **v31a**: the v29 solver wrapped in an `agent_tool` (no compaction, no post-submit loops), with explicit tool-argument examples. The ~38 s/task freed becomes +4 calls (v31a32). | +0.5 (−0.3, +1.3) | F: waste measured; F: no compaction inside `agent_tool`; I: calls-to-solves rate of 0.47 | ~1 day, ~9 quota-h, 1 smoke submission | Do; new base |
| 2 | **v31p**: a lead agent runs two attempts in parallel (an `agent_tool` wrapping a ParallelAgent). Attempt A is the v31a solver at temperature 0.2 in `/workspace`. Attempt B is a "read tests and callers first" variant at temperature 0.8 in a git worktree at `/tmp/wt_b`. Pick rule: a non-empty patch beats an empty one; between two non-empty patches, take the smaller. If both are empty, the lead makes one forced edit. | +1.0 over v29 (−1, +2.5); this includes lever 1's gain, so don't add them | F: 2 streams give 1.8× the tokens; F: 0/15 crashes offline; F (lab): picking the better of two runs perfectly gains +5.5 points, and the simple pick rule keeps 55% of that; I: draw-to-draw variance implies a 2–3 task ceiling for best-of-2. Against: in vanductan's public runs, the second seed solved nothing the first missed. | 3–4 days, ~25 quota-h, 1–2 smoke submissions | Main bet, behind gates |
| 3 | **v31t**: shorter thinking (budget 2048 plus a "keep thoughts short" rule) with more calls in the same time | +0.4 (−0.8, +1.5) | F: v30 used 6% fewer tokens; F: thinking budget 2048 solved as many as 4096 on 129 tasks (746250) | 0.5 day, ~8 quota-h | Fallback if lever 2 fails; otherwise built into the workers |
| 4 | Worker B's extra habits: read the tests and one caller before editing; check where sibling features are registered; find tests with `git ls-files`, then run `pytest -k` | +0.3 (−0.5, +1.0) | F: 18.7% of failed runs missed a second file the reference fix changed; 24% ran pytest on a path that doesn't exist. Against: V10, which has these habits, averages about 9.7. | ~0 extra GPU | Built into lever 2 |
| 5 | Repeat draws of the best bundle | Raises the displayed score only | F: best-of-draws math | Submission slots | Phase 3 |
| 6 | Run lab evaluations on the TPU with vLLM | Doubles measurement capacity | Not verified | ≤1 day + 4 TPU-h | Optional |
| – | 4-factor prompt factorial | Too small to detect | Detection limit far above expected effects | 35–56 quota-h | Drop |
| – | Rebuilding the 0.22 prompt structure as the main lever | ~0 | F: V10 repeat draws | – | Drop |
| – | LoRA / distillation | +0.3 to +0.5 | F: negative results; 11% slower generation; our traces contain no thinking text | 60–130 quota-h | Drop (reopen conditions in §5) |
| – | 12B model | – | F: never scored | – | Blocked |
| – | 3 or more parallel attempts | Less than 2 attempts | F: each attempt gets only 65–77% of v29's budget; best-of-3 adds just 2.5 points over best-of-2 in the lab | – | Drop unless v31p has ≥25 s/task to spare |
| – | Graph tools | ~0 | F: 746250 | – | Keep banned |

### Phases

**Phase 0: build the instruments and v31a (10-18 → 10-23)**

Deliverables:
- **D0.1 `evalset-v1`** (private Kaggle output/dataset):
  - ≥120 valid tasks (the reference fix passes 2 out of 2 checks, an empty patch fails 2 out of 2) from ≥80 repos, at most 2 per repo;
  - tasks created on or after 2025-02-01, in repos with at most 1.8% async functions;
  - PR-style task text where available; issue-style tasks are flagged and reported separately;
  - our own approximate code graphs, and a `tasks_meta.jsonl` file;
  - split by repo into A (60%, for tuning) and B (40%, sealed: nobody reads its runs).
- **D0.2 Corrected lab clock** in `gemma_agent/lab/labworker.py`, plus a new `timepred.py` that predicts scorer seconds per task from traces:
  - 0.25 s per call + 0.0286 s per generated token + 0.335 s per 1k uncached prompt tokens + 25.1 s per compaction + measured tool time;
  - slowdown factors of 1.11 / 1.23 / 1.35 for 2 / 3 / 4 parallel streams.
- **D0.3 `gemma_agent/lab/stats.py`**:
  - paired bootstrap, exact McNemar test, pooling of repeat runs;
  - a per-run dashboard: solve rate, empty-patch %, call-cap %, % of patches touching the reference fix's files, overflow, and time per task at p50/p90/p95;
  - for two-attempt bundles: A alone, B alone, oracle (A or B), and the picked result.
- **D0.4 `make_lab.py` changes**:
  - a `--data-dir` option;
  - a separate wheels directory and TMPDIR per task;
  - the docker-like sandbox manager;
  - grading of the extra patches `/tmp/a.diff` and `/tmp/b.diff`.
- **D0.5 `gemma_agent/bundle_v31a/`.**
- **D0.6 `gemma_agent/bundle_v31p/`**, filled in from `strat/parallel_arch/bundle_atpar`.

Leaderboard: v29 again on 10-19 (third baseline draw); v31a on 10-21 (first scorer test of the `agent_tool` path).

**Phase 1: calibrate the eval set and test the time-reuse levers (10-24 → 10-30), ~26 quota-h**
- lab21: v26t on the eval set → gate G1.
- lab22: v31a32 → gate G2a.
- lab23: v31p, 4 tasks at a time → gate G2b.
- Leaderboard: v31a ×2, v31a32 ×2, v29 ×1. v31p's first draw on 10-29 if G2b passes.
- Optional: TPU probe (≤4 TPU-h). Go only if it reaches ≥150 tokens/s total with 8 requests at once and ≥99% of tool calls parse.

**Phase 2: one tuning round and confirmation (10-31 → 11-13), ~40–45 quota-h**
- If G2b passed: lab24 runs v31p2 against v31p on split A. v31p2 is one bundled change aimed at G2b's weakest number:
  - if A alone lost more than 2 points, shorter thinking so each attempt gets more calls;
  - if A and B fail on the same tasks, a more different B.
- If the oracle gain failed: lab24 runs v31t against v31a32 on split A.
- lab25 (week of 11-07): the winning candidate ×2 and v29 ×1 on the sealed split B, plus 20 split-B tasks one after another on the real clock → gate G3.
- Leaderboard: one draw a day, shared between the two best bundles. Once each has 3 draws, allocate by Thompson sampling (draw from each bundle's estimated distribution, submit the one that comes out best). Each finalist needs ≥3 draws by 11-13.

**Phase 3: exploit (11-14 → 12-01)**
- Submit the champion daily. Submit the runner-up only while its estimated mean is within 0.5 task of the champion's.
- Freeze on 11-21: no new bundles after that.
- Keep GPU only for incidents (for example, a champion draw times out: cut 2 calls and re-check timing).
- Pick the final submissions on 12-01 (policy in §5).

### Gates

| Gate | Date | What is measured | Go if all hold | If not |
|---|---|---|---|---|
| G0a | 10-19 | CPU only | `timepred.py` is within ±5% of measured seconds per task for each lab17 kernel and bundle (v28, v29 ×2, v29c36). v31a passes `official_check`. The fake-model harness test passes 30/30 with 0 "No function call event" errors. A scripted case where the solver calls `submit_patch` anyway does not end the task with an empty patch. | Fix before any GPU run |
| G0b | 10-20 | lab19: v31a on lab17's 12 tasks, one at a time, real clock | 12/12 finish; 0 compaction events; ≤1 post-submit call per task; predicted mean ≤ v29's prediction on the same tasks − 25 s; real mean ≤ 303 s (0.95 × 318.6); 0 context errors; empty patches ≤ v29's count + 1 | The 10-21 slot goes to v29; fix and rerun once |
| G1 | 10-25 | Full eval set: v29 (lab20) vs v26t (lab21) | ≥120 valid tasks (≥100 acceptable); v29 solves 10–30%; v29 beats v26t by ≥5 points with the paired 95% interval above 0 | Use the eval set only for time, crash and mechanism checks; decide finalists with ≥6 leaderboard draws each |
| G2a | 10-26 | lab22 v31a32 vs lab20 v29 | Predicted time ≤ 1.00× v29 on average and p90 ≤ 1.05× (paired); overflow ≤ 5%; solve rate no more than 4 points below v29; empty-patch rate ≤ v29's | v31a with 28 calls stays the base |
| G2b | 10-28 | lab23 v31p vs lab20 v29 | 0 "No function call event"; overflow ≤ 3%; predicted time ≤ 1.00× v29 on average and p95 ≤ 1.10×; oracle (A or B) beats A alone by ≥3 points; picked result ≥ v29 + 2 points; A alone ≥ v29 − 4 points; empty-patch rate of the picked result ≤ 0.6× v29's | Oracle gain under 2 points: drop best-of-2 and run v31t. Only time fails: shrink once (call caps of 22 per worker, thinking 2048) and rerun on split A |
| G3 | 11-13 | Sealed split B, pooled A+B, and the leaderboard | Candidate ≥ v29 + 2 points on B; pooled ≥ +3 points with the 95% lower bound ≥ −1; real-clock mean ≤ v29's prediction on the same tasks; ≥3 leaderboard draws, 0 timeouts, mean ≥ v29's leaderboard mean | Champion = v31a32 if its leaderboard mean ≥ v29's; otherwise v29 |

### Budget

| Week (quota resets Saturday 00:00 UTC) | GPU quota-hours | Use |
|---|---|---|
| Until 10-23 | ~9 of ~13 left (lab17/18 used 8.47 wall-hours ≈ 17 quota-h since 10-17; check the Kaggle page) | lab19 2.2, lab20 7 |
| 10-24 | ~26 | lab21 7, lab22 7, lab23 ~12 (2 streams per task) |
| 10-31 | ~20–26 | lab24, plus one repeat run |
| 11-07 | ~16–20 | lab25 split B ~12, real clock ~4 |
| 11-14 → 12-01 | 0–30 reserve | Incidents only |
| **Total** | **~75–110 of ~193** | |

Other resources:
- TPU: 0–4 h. RunPod: $0. Kaggle CPU: ~20 h.
- About 38–40 submission slots from 10-19 to 11-30: ~4 v29, ~10 v31a/v31a32, ~8 v31p/v31p2, 14–16 champion, plus spares. Each needs your approval; approving a week's batch at a time avoids losing slots.

## 3. The first 72 hours (10-18 21:00 → 10-21 21:00 UTC)

Setup: `SP=/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad`, `R=/home/user/Markov-chain-/gemma_agent`. This machine has only 3.1 GB of free disk, so snapshots are never downloaded here; everything heavy stays on Kaggle.

**Hours 0–8 (CPU)**
1. Prepare the eval-set build inputs.
   - Copy `$SP/strat/evalset/scripts/*` and `candidates_v1.json` to `$R/evalset/`.
   - Write `split_cands.py`, which splits the candidates by repo into `cand_a.json` and `cand_b.json` (210 each).
   - Port `goldcheck.sh` to `goldcheck_kaggle.sh`, reading its paths (PY, OFFICIAL, IMG, DOCKER, SETUP) from environment variables.
   - Stage `$SP/ebi/`: the scripts, `cand_{a,b}.json`, `strat/evalset/dl/*.parquet` (~215 MB), `compdata/{image313,docker,sandbox}` (~47 MB) and `$R/official/run_official.py`.
   - Run `kaggle datasets create -p $SP/ebi` (private, ~270 MB).
2. Write `$R/evalset/make_build_kernel.py --part a|b`.
   - Kernel metadata: internet on, the competition attached as a source (for the wheelhouse), `evalset-build-inputs` attached as a dataset.
   - Kernel steps:
     - `uv python install 3.13`, then install the wheelhouse with `--no-deps`;
     - `python -I build.py cand_a.json /kaggle/working/evalset lb_test.parquet,v2_py_post.parquet,rebench_test_0.parquet,rebench_test_1.parquet --jobs 4`;
     - `goldcheck_kaggle.sh` twice, then delete every task that doesn't pass gold 2/2 and fail empty 2/2;
     - `emit_tasks.py ... --ps pr --no-nodes`, then `make_graph.py` per kept task, and write `tasks_meta.jsonl`.
   - Push both: `kaggle kernels push -p /tmp/eb_a`, then `kaggle kernels push -p /tmp/eb_b`. Expect about 7–10 h each.
3. Write `$R/lab/timepred.py` and check it against the lab17a/b traces (gate G0a, timing part).

**Hours 8–24 (10-19, CPU)**
4. Edit `labworker.py` and `make_lab.py` (D0.2, D0.4) and write `stats.py`. Check them by reproducing lab18's v29-vs-v30 result (32 vs 30 of 73).
5. Build `bundle_v31a`:
   - **Lead:** `agent_tool: sub_agents/solver.yaml`, plus `get_status` and `submit_patch`. Prompt: "Call solve once with request 'go'. Then call submit_patch. Then reply DONE." Sampling: temperature 0.2, `max_output_tokens` 1024, `thinking_budget` 256.
   - **Solver:** the v29 prompt with `Issue: {problem_description}` added. Its last step becomes "end with a 3-line report". Add explicit argument examples for `edit_file` and `read_file`. Tools: v29's list without `submit_patch`. Sampling: v29's, but `max_output_tokens` 6144. `output_key: solver_report`.
   - **`eval_config.yaml`:** 240 s, 28 calls, 8 min, 80 turns.
6. Check v31a offline:
   - `$SP/wh31/venv/bin/python -I $R/official_check.py $R/bundle_v31a`
   - `python -I $SP/strat/parallel_arch/compile_check.py $R/bundle_v31a`
   - fake-model harness test ×30 with `$R/official/fake_llm.py` (new scenarios: `agenttool_solo`, `solver_calls_submit`).
   → gate G0a.
7. **Leaderboard 10-19 (needs your approval):** v29 unchanged (`dist/v29/submission.zip`), the third baseline draw.

**Hours 24–48 (10-20)**
8. **lab19 (GPU ~2.2 quota-h):** `python $R/lab/make_lab.py --bundles v31a=$R/bundle_v31a --tasks @$SP/lab17_ids.txt --out /tmp/lab19 --slug gemma-agent-lab19 && kaggle kernels push -p /tmp/lab19`. This runs one task at a time on the real clock, on the 12 lab17 tasks → gate G0b.
9. Check the two build kernels. Rerun failed tasks. A third CPU kernel, `evalset-merge`, reads both outputs as kernel sources and writes the combined layout with the seeded A/B split.
10. Build `bundle_v31p` from `bundle_atpar`:
    - Worker caps written into the prompts: 24 calls each. Shared `max_tool_calls` 52, `max_turns` 140, 8 min.
    - Worker B: thinking budget 2048, starts with `git -C /workspace worktree add -f /tmp/wt_b HEAD`, and sets `PYTHONPATH=/tmp/wt_b/src:/tmp/wt_b` itself.
    - The lead saves `/tmp/a.diff` and `/tmp/b.diff`, applies the pick rule from the levers table, then calls `submit_patch`.
    - Offline: run `repro_parallel.py` 30 times on the final shape with 0 crashes required, and confirm the lab clock sees the branches inside the `agent_tool`.

**Hours 48–72 (10-21)**
11. **Leaderboard (approval):** v31a's first draw, if G0b passed.
12. Smoke-test the eval set on CPU: 5 gold patches and 5 empty patches through `make_lab` using the new data directory.
13. **lab20 (GPU ~7 quota-h):** `make_lab.py --bundles v29=$R/bundle_v29 --tasks @evalset_all.txt --data-dir /kaggle/input/evalset-merge --concurrency 6 --virtual-clock --vc-per-call 0.25 --vc-per-token 0.0286 --vc-per-compaction 25.1 --out /tmp/lab20 --slug gemma-agent-lab20`. This is the first half of calibration; v26t runs on 10-24 after the quota reset.

GPU in these 72 h: about 9.2 quota-hours. Approvals needed: 2 submissions (v29, v31a) and 2 GPU runs (lab19, lab20). The GPU runs are measurement tools rather than candidates; without them, no gain smaller than about 3 tasks can be confirmed.

## 4. What we stop doing
1. Deciding anything from the fastapi/rich lab beyond crash checks.
2. Deciding from a single run or a single leaderboard draw, including "this rule fixed task X" and rules written from individual traces.
3. Testing changes whose expected effect is below what the test can detect: +1–3-task prompt tweaks and Plan 1's 8-arm factorial.
4. Treating the 0.22 structure as the missing piece (Plan 2's v31). Its repeat draws average no better than v29.
5. LoRA, distillation, 12B, 3+ parallel attempts and graph-tool work, until a reopen condition (§5) is met.
6. Prompt rules that only fix tool mechanics. They cut corrupted calls from 48 to 8 with no change in solves.
7. Using the old lab clock, which reads 25–35% too fast and ignores compaction.
8. Submitting anything slower than v29 on the same tasks (v28 lost a slot this way), except planned smoke tests.
9. Leaving a submission slot empty. With no candidate ready, the slot goes to the current best bundle.
10. New bundles after 11-21.

## 5. Risks, fallbacks, and how the final submissions are picked

| Risk | Probability (I) | Caught by | Fallback |
|---|---|---|---|
| The eval set fails calibration | ~30% | G1 | Eval set used only for time, crash and mechanism checks; finalists decided by ≥6 leaderboard draws each; skip the tuning round |
| Fewer than 100 valid tasks | ~20% | D0.1 | Add tasks from the SWE-rebench-V2-PRs reserve (about +1 day) |
| The `agent_tool` path breaks on the scorer | 10–15% | v31a's draw on 10-21 | v29L: the same lean prompt without the wrapper (compaction stays); cancel v31p |
| v31p runs past 12 h on the scorer | ~15% after G2b | v31p's first draw | Shrink the workers (22 calls, thinking 2048) and re-check the predicted time; otherwise champion = v31a32 |
| The two attempts fail on the same tasks (oracle gain under 2 points) | ~30% | G2b | v31t (shorter thinking, more calls) |
| Context overflow without compaction | ~5% of tasks | Dashboard | Workers' `max_output_tokens` 6144, outputs cut with `head`; even on overflow the `/workspace` diff is submitted (`agent_runner.py:1026-1078`) |
| The host changes the harness or time rules | ~20% | Weekly check of forum topics 749597 and 748287 | Re-run the G0b/G2 timing on the new harness before the next submission |
| Approval or quota lag | – | – | Approve a week's slots at a time |

Reopen conditions:
- **LoRA:** a scored public LoRA bundle beats its own non-LoRA version by ≥2 tasks over ≥2 draws each, and generation is no more than 5% slower.
- **12B:** any 12B submission is reported as scored, and a split-A run at the same time cap matches v29.

**Final-submission policy (12-01)**
1. Only scored runs are eligible. A run that shows a public score finished, and its private score comes from the same run.
2. Estimate each bundle's mean from its leaderboard draws (standard error 1.43/√n) combined with its eval-set estimate, weighted by precision. No single draw counts on its own.
3. If the best bundle leads the runner-up by at least one standard deviation of that estimate, pick 2 runs of the best bundle. That gives two independent private draws, and Kaggle normally counts the better of the two selected [I]. Otherwise pick one run from each of the top two bundles.
4. Bundles with fewer than 3 draws, or with any timed-out draw, are ineligible unless nothing else qualifies.
5. Lock the choice on 12-01. The last new submission goes in around 11-30, because scores take 15–27 h.

**Why the private leaderboard rewards the true average.** Against 300–500 teams near 10 tasks, a rough simulation (`merge_plan/private_rank.py`) puts our median private rank at:
- about 100–166 with a true average of 10;
- 42–68 at 11;
- 13–21 at 12;
- 4–6 at 13.

**Files** (in `(scratchpad)/`):
- `strat/merge_plan/odds.py`, `odds_out.txt` (leaderboard odds and the rival limit)
- `strat/merge_plan/mixture.py`, `mixture_out.txt` (odds across the plan's outcomes)
- `strat/merge_plan/power.py` (what each test can detect; the calls-to-solves rate)
- `strat/merge_plan/private_rank.py` (private-leaderboard rank)
- `lab17_ids.txt` (the 12 tasks for lab19)
# Critique
**Verdict: the plan is sound in direction but mis-sized, and its decision machinery repeats our old mistake.** Its diagnosis holds: the public recipes average about 10 tasks, the lab doesn't predict the leaderboard, and time per task is the binding limit. But three things undercut it. The main bet, v31p, has a measured ceiling of about +1 task and is over the time limit as specified. Its gates can't detect the effects they are meant to judge. And v31a carries harness hazards the plan doesn't test for. As written, it spends about 70 GPU quota-hours and about 3 weeks of slots on a lever worth roughly +0.5 to +1 task, decided by coin-flip gates. That is the "10 h + 15 h test, same place" pattern the user complained about.

Grades: **[F]** = I checked it in files this pass. **[I]** = inference.

## A. Claims not supported, or overstated

1. **The two-attempt upside ("≥5 points, average 12.5, 0.7–0.9 chance of showing 0.25") is above what two attempts can deliver.**
   - For two independent attempts of the same agent, the expected best-of-2 gain equals the draw-to-draw variance of the task count.
   - The board draws give an SD of 1.07 (Budget-Fit's 7 identical draws), 1.43 or 1.78 tasks. So the perfect-picker ceiling is 1.1, 2.0 or 3.2 tasks, and the plan's own picker (keeps 55%) gives +0.6 to +1.7 [F, `strat/redteam/gates.py` §1].
   - vanductan's two 31B seeds: perfect picker 12 vs a mean of 11.5 of 40, i.e. +0.7 per 58.
   - The lab's +5.5-point oracle is inflated by fastapi/rich task flips.
   - **Fix:** delete the upside branch from the odds, or make it conditional on a measured ceiling (C1). The honest odds are the middle case or lower.

2. **"Oracle gain precise to about ±1 point" is wrong.**
   - In v31p the gain over A is the share of tasks only B solves. At a share of 0.035 on 120 tasks the SE is 1.7 points, so the 95% interval is about ±3.3. `power.py` gets 1.2 because it models two runs of the same bundle (symmetric), which v31p is not [F, gates.py §3].
   - G2b's "oracle ≥ A + 3 points" therefore passes a true 2-point gain about 30% of the time.
   - **Fix:** gate on the oracle with a lower confidence bound, or pool two v31p runs.

3. **v31t at a thinking budget of 2048 frees less than implied.**
   - Capping completion at 2048 removes 9.5% of v29's completion tokens; only 1.9% of steps are above the cap. A 1024 cap removes 21.8% (5,730 steps from lab15–18) [F]. That ~20 s/task is worth about +2.5 calls, i.e. +0.3 tasks at the 0.47 rate.
   - The 0.47 calls-to-solves rate itself comes from one comparison (25 vs 50 calls: 36 vs 50 of 129). Identical configs in the same post differed by 7 tasks (E30 vs E34: 55 vs 48, topic 746250) [F]. Its real range is about 0.2–0.75.
   - **Fix:** show every calls-to-gain conversion as a range, not a point.

4. **"Repos the model hasn't seen" is not what the eval-set filter delivers.**
   - The filter selects fixes made after the model's cutoff, mostly in repos that existed before it.
   - 231 of the 420 candidates (55%) are leaderboard rows. `emit_tasks.py --ps pr` keeps their issue text, median 1,391 characters, against 418 on the public tasks [F, `emit_tasks.py:9-11`, `candidates_v1.json`].
   - It also copies `hints_text`, which is empty in all 129 public tasks [F].
   - **Fix:**
     - Fetch the PR title and body from the GitHub API for the leaderboard rows (CPU, cheap).
     - Blank `hints_text`.
     - Report results split by repo creation date (before vs after 2025-01) to get a truly unseen subset.

5. **"14% wasted" depends on the scorer compacting at 14,336 tokens.**
   - The public getting-started notebook uses 14,336 (`nbhost2` cell 10) [F].
   - The host said on 10-15 that this notebook "uses the same configuration as the scorer" (`host_all.txt:422`) [F].
   - Topic 744692 shows an earlier 32,768 threshold [F].
   - The claim is probably true, but it is grade I, not F.
   - **Fix:** say so; the v31a smoke draw confirms it indirectly.

## B. Infeasible or hazardous steps in the harness

1. **Without compaction the context limit binds more often than the plan says.**
   - `arch_plan/uncomp.py` on 194 v29 lab traces: p50 19.1k tokens, p90 29.4k; 28 runs above 27.7k and 9 (4.6%) above 32k [F].
   - Near 30k the server clamps the reply (`trace_rich_3944` step 10: a 29,808-token prompt, with `max_output_tokens` 8192 in the bundle). So about 10% of runs have their last steps squeezed below their 4096 thinking budget.
   - With 32 calls the p90 reaches about 33.6k [I, linear scaling].
   - One unbounded `git grep` there grew the prompt from 13.4k to 29.8k in a single call.
   - **Fix:**
     - Drop v31a32. Keep v31a at 28 calls and bank the ~44 s as margin.
     - Add a prompt rule to pipe all output through `| head -c 4000`.
     - Optionally split the solver into two `agent_tool` phases (locate → fix, handing over a report) to reset the context.

2. **Inside `agent_tool` nothing stops a model that keeps calling tools after the limit.**
   - `max_turns` is enforced only by the outer `RunConfig(max_llm_calls)` (`agent_runner.py:789-801, 1026`). The inner Runner uses the default of 500 (`agent_tool.py:239-246`). Once over budget, tools refuse (`context.py:468-497`), but the model keeps being called [F].
   - In v29, 39/194 runs hit a "Tool call budget exhausted" refusal. 4 of them made about 50 more model calls and were stopped only by max_turns 80 [F].
   - In v31a and v31p these loops run to the 8-minute timeout.
   - **Fix:**
     - Add a G0a fake-model test: the solver keeps calling tools after BudgetExceeded.
     - Add a prompt rule: on BudgetExceeded, reply with the report at once.
     - Add an eval-set metric: share of tasks that hit 8 minutes.

3. **v31p can't always carry out its pick rule.**
   - All agents share one tool counter, and `submit_patch` and `get_status` are the only free tools [F, `execution.py:76,119`].
   - When the workers use up the shared 52 calls, the lead's `run_command` calls (save the diffs, `git apply` B's patch) are refused. Then A's working tree wins by default, or nothing.
   - **Fix:**
     - Make A's `/workspace` the default answer.
     - Have workers put a short diff summary in their `output_key` reports, so the decision itself needs no tool call.
     - Reserve calls by telling the workers a cap below the harness cap. How well they comply is something the eval set measures precisely.

4. **v31p at 24 calls per worker is over the time limit.**
   - It waits for the slower worker, and my model puts that at 326 s/task, 1.02× v29 (gates.py §2: useful decode 225 s × 1.11 two-stream slowdown, tool time serialized, slower-of-two penalty 0.56 × 77 s).
   - 22 calls gives 0.95×.
   - **Fix:** build at 22 calls (each attempt then gets 79% of v29's calls). The net gain becomes about +0.1 to +0.7 task.

5. **Worker B is handicapped by design.**
   - It can only use `run_command`: `read_file` and `edit_file` reject paths outside `/workspace` (`workspace.py:22-57`). Shell-based editing is our v22 family, which scored 6 on the leaderboard against 10 for native tools.
   - Putting the worktree inside `/workspace` instead would be picked up by `git add -N .` in the timeout fallback (`agent_runner.py:1050`).
   - **Fix:** if v31p survives C1, let A and B swap tool sets, or accept that B is weaker in the estimate.
   - Also add a mechanism check that B's tests import code from `/tmp/wt_b`.

6. **The eval-set build kernels are at the 12 h limit.**
   - Build takes about 7 h for 210 candidates. The gold/empty check runs sequentially: 4 checks × 4–49 s on about 160 built tasks ≈ 3.5–5 h. That totals about 10.5–12 h per kernel [I].
   - The pilot measured 71 MB per task, so about 15 GB before filtering [F, `evalset/data*`], against the 20 GB output limit.
   - **Fix:** use 4 build kernels, or put the gold checks in separate kernels. Delete failing tasks as the run goes.

## C. Statistical design repeats noise-level A/B testing

1. **The gates can't see the effects they judge** [gates.py §3]:

   | Gate | Pass if true gain = 0 | Pass if true gain = +1 task |
   |---|---|---|
   | G2b, picked ≥ v29 + 2 points (SE 3.9) | 0.30 | 0.47 |
   | G3, split B ≥ +2 points (48 tasks, SE 6.2) | 0.37 | 0.48 |
   | G3, pooled with 95% lower bound ≥ −1 | 0.04 | 0.10 (+2 tasks: 0.21) |

   G3 effectively always falls through to its leaderboard fallback.

   On the leaderboard, 6 draws each order a 0.5-task gap correctly only 73% of the time (3 draws: 67%). Thompson sampling at 3 draws is choosing by noise.

   **Fix:**
   - Use non-inferiority plus mechanism gates: candidate ≥ v29 − 5 points, paired time ratio ≤ 0.98 with a 90% upper bound, overflow, empty-patch rate, 8-minute hits. Adopt on prior plus mechanism.
   - Use leaderboard draws only to confirm scorer safety (no timeout, no crash), not to choose between candidates.

2. **G0b's absolute time threshold is noise.** "Real mean ≤ 303 s on 12 tasks" has an SE of about 22 s, and v29 itself moved 36 s between lab17a and lab17b.
   - **Fix:** compare paired against v29 in the same kernel, or use `timepred` ratios over the 120 eval-set tasks.

3. **G1 calibrates against v26t's single leaderboard draw (5 tasks).** With SE 3.9 points, the required "CI above 0" means an estimate of about 8 points, against a true gap of about 8.6 [I]. That is roughly 50% power.

## D. Strategy against the user's goal

- The plan concedes a true average of about 11 (0.19). It does no direction-finding: the eval set, our first instrument on unseen-style repos, is used only to check gates.
- The cheapest high-value lever goes untested: a check by the lead on an empty `git diff`. It targets the largest failure class (30–40% never edited; 18% empty patches in the lab, 40/218). In the lab the "non-empty first" pick alone recovers +1.5 of 73 [F, `selector.py`]. It costs time only on the roughly 20% of tasks that come back empty, paid from the ~44 s v31a frees.
- About 75–110 quota-hours goes almost entirely to measuring changes of +0.5 to +1 task. That conflicts with the user's rule of using GPU only when a significant gain is expected.

## What checks out [F]

- The repeat-draw means (V10 8.75 without the selected 13; Budget-Fit 10.14; SD 1.43 / 1.78 pooled).
- `agent_tool` runs a fresh Runner with no compaction and copies session state (`agent_tool.py:235-262`).
- The timeout fallback submits the `/workspace` diff.
- The v31p time constants.
- The score grid.
- Dropping LoRA, 12B and graph tools.
- Harness nudges matter little in v29: 6 of 157 traces have one.

## The 3 changes that matter most

1. **Measure before building.**
   - Replace lab21 (v26t) with a second v29 run on the eval set.
   - From the pair, get three things on unseen-style repos: the best-of-2 ceiling for identical attempts, the replicate noise, and the failure breakdown.
   - Build v31p only if the ceiling is ≥4 points and failures look like run-to-run variance rather than never locating the code. Otherwise put the effort into localization. This kills or confirms the main bet for 7 quota-hours instead of about 25 plus 3–4 days.
2. **Make v31a safe and use its real advantage.**
   - Keep 28 calls and drop v31a32.
   - Truncate tool output in the prompts.
   - Add tests and a prompt rule for post-limit loops.
   - Reserve tool calls for the lead, and add the lead's empty-diff guard: one targeted retry when `git diff` is empty.
   - If v31p goes ahead, build it at 22 calls per worker.
3. **Change the decision rule.**
   - Use non-inferiority, mechanism and paired-time gates.
   - Fix the eval set's text format: PR text for leaderboard rows, blank `hints_text`.
   - Spend leaderboard slots on scorer safety plus repeat champion draws, not on choosing between candidates expected to differ by less than 1.5 tasks.

Files: (scratchpad)/strat/redteam/gates.py has the ceiling, timing, gate-odds and leaderboard-ordering numbers; the per-step token-cap and post-limit-loop figures came from one-off scripts over the lab15–18 v29 traces.