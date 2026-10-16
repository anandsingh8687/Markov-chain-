# Merged plan: public LB from 0.10 to 0.25 (written 2026-10-15)

**What reaching 0.25 means.** The public score is solved/58, truncated to two decimals. prvsiyan's notebook computes it this way (`int(k*10000//58)//100`, line 1629), and every reported score fits that grid. So 0.25 means **15 of 58 tasks**. 14 tasks shows as 0.24 and 16 tasks as 0.27, so a score of 0.26 cannot occur. The training plan's "≥0.26" target was wrong. On the same grid, our best (0.10) is 6 tasks, Budget-Fit (0.18) is 11, the 0.22 cluster is 13 and the leaders (0.24) are 14.

**Where the three plans disagreed, and how I resolved it from the files:**

| Disagreement | Resolution | Evidence |
|---|---|---|
| Submit v27 first (robustness plan) or v28 first | **v28 first.** v27's prompt is the "contract-first" type. The one verified score for that type is 0.18 (kashyap's byte copy of honghanhhh V3). The lab A/B covers v27. Submit v27 only as a fallback if v28 errors for an unexplained reason. | kashyapsinhgohil nb; Apex/jingshuifu say plainly they are "not a measured score" |
| Forced edit by call 8 or call 12 | **Call 12.** The "≤14 calls 52% vs 15–20 calls 5%" figure is confounded (easy tasks finish early). Forcing early edits mostly produces wrong edits in the right file. | 749198, 747980, leoprovorov tally |
| Graph tools declared or removed | **Keep them declared and forbid them in the prompt**, as both measured recipes do (0.18 and 0.22). Never call get_code_subgraph: it takes an array argument. | verracodeguacas, flexonafft, 745138/746336 |
| Check patch_size after submit_patch and resubmit | **Drop this.** Whether submitting ends the session is disputed (Gluzdov says the loop ends; samvalladares says the last submit wins; prvsiyan's traces show 13 submit calls). Do all checks first, then submit once. | dmitriigluzdov ideas nb; prvsiyan line 1481 |
| P(15 tasks) per draw at a mean of 13: 8% or 16–23% | **About 7% is more realistic.** If more than 20 teams' draws of one bundle all landed at 13 and none at 15 or above, the per-draw standard deviation is about 1 task. At sd 1.5 you would expect about 3 of 20 draws at 15 or more (P(none) ≈ 0.03). This is inference only; open question Q8 checks it. | 748051 (10/9/8/9), prvsiyan (5,4) |
| Our lab mirrors scorer compaction? | **It already does.** `lab/labworker.py:356-358` sets 15/2/14336/5 and the context cache 2048/1800/10. But the virtual clock was calibrated before 0.2.13, when thoughts were not carried between calls, so it needs recalibrating (Q2). | /home/user/Markov-chain-/gemma_agent/lab/labworker.py |

**Stale lines in context.md.** Correct these before anyone relies on them:
- The scorer runs wheelhouse v31 (adk_submission 0.2.13, swegemma 0.2.11 of 12 Oct, vLLM 0.19.1).
- `include_thoughts: false` no longer turns thinking off. Only `thinking_budget: 0` does. include_thoughts now decides whether earlier thoughts are carried from call to call (HOST, 747914).
- `timeout_seconds` does not bound the grader's pytest. The grader uses a fixed 300 s (HOST, 748428).
- Edits to test files are dropped from the patch since 8 Oct.
- The graph tools return results again (270/314 replayed calls), but no gain in solved tasks has been shown (748323).

---

## 1. What the 0.22 cluster and the 0.24 leaders are doing

Grades: **M** = measured LB or local data; **R** = reported by a third party, no screenshot or id; **S** = speculation or inference.

**The baseline everyone forks: 0.17–0.18 (M).**
- **Budget-Fit config:** T 0.2, top_p 0.95, max_output 8192, thinking 4096 with include_thoughts true, 240 s / 28 calls / 8 min / 80 turns, 9 tools.
- **Reproduced on the LB:** Gluzdov 0.18, prvsiyan E01 0.18 (57111761, 12 Oct), dddmd 0.18 (57049421).
- **Prompt-only variants of it:** Gluzdov D1 0.17, prvsiyan E03 0.17 (57183017, 15 Oct), an alternative prompt 0.13.
- **Conclusion:** the post-8-Oct harness build alone does not lift this family to 0.22 (M).

**The 0.22 cluster is almost certainly flexonafft/gemma-4-budget-aware-coding-agent-v2 (R, strong).**
- dmitriigluzdov/public-agent-ideas (line 227): "0.22 remains the original author's result". Its builder asserts that only prompts/system.md differs from Budget-Fit.
- nihilisticneuralnet pins the bundle's zip hash 6ff73d10… to "the attached 0.22 notebook".
- honghanhhh v3 names it as its "public 0.22" base.
- The cluster is dated 10-12..10-14, which matches the publication date (from context.md).
- **The YAML is byte-identical to Budget-Fit and to our v27. The prompt is the only difference (M, by diff).**
- It is a structured prompt of about 6.2 KB, derived from matterhorn3838 SuperAgent, with:
  - a call-phase plan: 1–8 locate, 9–12 edit (mandatory by 12), 13–20 verify, nothing new after 20;
  - a specification and edge-case list made before any tool call;
  - independent fixed-string git grep and git ls-files searches batched into one run_command;
  - up to 3 sed regions of about 40 lines per call;
  - reading one caller or test before editing;
  - for features, copying the closest sibling including its registration points;
  - an edit-failure ladder ending in a python heredoc that asserts exactly one match;
  - verification capped at 2 calls with `timeout 150 pytest -x -q -k`;
  - decision rules.
- **Evidence against a large effect:**
  - Gluzdov's paired screen on 31 tasks from repos outside the public set: 9/31 vs 9/31, p=1 (M, small sample).
  - Generic additions to Budget-Fit (an issue contract, a coverage checkpoint) gave 0.17–0.18 (M).
  - So the gain is probably real but only about 1–2 tasks, and comes from the specific structure: call budgeting, batching, the edit-recovery ladder (S).
- **Whether every 20+ team runs this exact zip is unknown (S).** The tightness of the cluster suggests per-draw sd near 1 (see above).

**The leaders at 0.24, Yurnero and Yike Xu: method unknown.**
- Yurnero already had 0.24 on 8 Oct, before the 0.22 recipe existed (M: prvsiyan line 140).
- His only hints (748500, 748044): "~$1000 of compute", "we are allowed to tune smaller models now", and strong local validation with few deliberate submissions (S that it means LoRA or 12B). He did not answer the LoRA question.
- No information on Yike Xu.
- **No public 0.24 recipe exists.** honghanhhh "LB 0.24" V3 shows 0.18 on its own page (R, kashyap). Apex and jingshuifu lb024 say "not a measured score". ozertuu gold states intent only. hitarthjain's title describes the leaderboard history, not his bundle.
- "The top is LoRA" is disputed and unsupported (748051: Sahil says yes, htn says no). No LoRA bundle in the corpus reports an LB number. Gluzdov's LoRA SFT was a NO-GO: 2/32 vs base 4/32 (M).

**What separated earlier tiers (M):**
- **Thinking on vs off:** Murugesan 0.05–0.08 → 0.10–0.15; Ayush 23 vs 48/129.
- **Native tools vs skill scripts:** yiyu 14–16/31 vs 7–8/31. Our v22/v26t at 0.08–0.10, and prvsiyan's patch kit at 0.05, fit this.
- **max_output 8192 vs 16384:** the starter config scored 0.08 (overflow at 32k).
- **Budget-Fit caps plus "edit by 12":** no-edit tasks fall from 38% to 11.6% (749198).

**Noise (M).**
- Identical archives: Sahil 10/9/8/9 tasks; prvsiyan 5→4 twice; Gluzdov 7/6/4 across harness builds.
- Locally, 15% of tasks flip between identical runs (747168).
- **Implication:** per-draw P(15) at a true mean of 13 is about 7% (sd 1) to 16% (sd 1.5); at a mean of 14, about 31–37%. **Matching the 0.22 recipe and resubmitting is roughly a 30% bet over 5 draws. We need a true +1 task over it.**

---

## 2. v28 bundle spec (submit first)

**Files:** gemma_agent/bundle_v28/
- I merged three rules from the config-prompt draft into it today; the pre-merge copy is (scratchpad)/oct15/plan/system_v28_before_merge.md.
- Lint ((scratchpad)/oct15/plan/lint_bundle.py) passes. The prompt is 7,183 bytes, with no braces and no backticks; content sha256 a69d473c9d9be486.
- Overlap with the flexonafft 0.22 prompt: the only 6-word run is "28 tool calls and 8 minutes"; there is no 7-word run.

**agent.yaml** (byte-identical to v27):
- `name: fixer`, `model: gemma-4-31b-it-qat-w4a16-ct`, `instruction: !include prompts/system.md`, `generate_content_config: !include configs/sampling.yaml`
- Tools: run_command, read_file, edit_file, write_file, get_status, submit_patch, search_similar_code, get_code_neighbors, get_code_subgraph. The last three are declared as a crash guard and forbidden in the prompt.

**configs/sampling.yaml** (unchanged): temperature 0.2, top_p 0.95, max_output_tokens 8192, thinking_config.thinking_budget 4096, thinking_config.include_thoughts true. No top_k and no seed.

**eval_config.yaml** (unchanged): timeout_seconds 240, max_tool_calls 28, max_time_minutes 8, max_turns 80. Fix the stale comment that says timeout_seconds bounds the grader's pytest.

**Zip:** exactly these 4 files, deterministic timestamps, no .pyc, uploaded under the name `submission.zip`.

**Prompt rules** (already written in our own words in the file):
1. **Grader framing.** Only the diff is graded. Hidden tests are written from the issue. An edit already on disk counts at timeout or when the call cap is hit; an untouched tree scores zero.
2. **Hard limits.** 28 calls / 8 min. Never touch tests or test config. No whole test suites. Stay inside /workspace. No installs. Do not call the 3 graph tools.
3. **Call plan.** 1–8 find and read; 9–12 edit (a source change is mandatory by 12; if unsure, edit the best candidate); 13–20 check and correct; after 20, no new searching.
4. **Specification before any tool call.** Exact names, the exception class and message, return or output, triggering inputs, and edge cases (None, empty, zero or negative, unicode, duplicates, defaults). Every literal in the issue must appear verbatim in the code.
5. **Locate.**
   - No directory listing; the layout is already in the first message.
   - If the issue names a path, open it directly.
   - A title-only issue means inferring the behaviour from the title, the code and the tests.
   - Independent fixed-string git grep and git ls-files searches go in one run_command, about 20 lines each. Dependent searches wait for their input.
   - Read with sed, up to 3 ranges of about 40 lines per call, or read_file with a line range.
   - Read the implementation plus one caller or test.
   - For a bug, fix where the wrong value is produced. For a feature, copy the closest sibling including its registration points.
   - Run a reproducer once at most, with python -c.
6. **Edit.**
   - old_string is copied exactly, 1–5 unique lines, with no docstrings or triple-quoted text.
   - On a rejection (no match, several matches, or missing parameters), re-read and use a smaller anchor. Never resend the identical call.
   - After 2 failures, use one heredoc python replace that asserts exactly one match first.
   - write_file only for a new module the issue requires.
   - Fix the cause, not the example. Keep signatures and backward compatibility. Use the exact exception text.
   - Apply the change to every parallel implementation (sync and async, client variants, backends, overloads, re-exports).
   - FastAPI documentation tasks: edit docs_src.
7. **Check (at most 2 calls).** One test file with -x -q -k, inside timeout 150, keeping only the last 25 lines. Ignore unrelated fixture or import failures. Fix once and rerun once; otherwise use python -c or py_compile.
8. **Review, then submit once.**
   - One call: git status --short plus git diff, capped at about 100 lines.
   - Remove scratch files and git checkout any touched test file. Confirm the literals are present.
   - Then call submit_patch once.
   - Under 90 s left on get_status: submit immediately.
9. **Decision rules.** Take the most literal reading. After an empty search, try one more string, then edit. After a failed fix, make a different, smaller change. Keep every output short. Never conclude that no change is needed.

**Why it differs from v27, and only in the prompt.**
- The only measured difference between 0.18 and 0.22 is the prompt (section 1). v27's 2.3 KB contract-first prompt belongs to the family measured at 0.18.
- v28 adds the call-phase plan, batching, caller/test reading, sibling registration, parallel implementations, the edit-recovery ladder, the timeout-wrapped and capped check, and the review step.
- It also adds guards against measured failure modes:
  - 20% of edit calls rejected, with up to 14–27 identical resends (748323, 747168);
  - overflow loses the patch: 44/44 overflowed sessions empty (744692);
  - compaction drops tool history (747186).
- Expected outcome: 12–13 tasks (0.20–0.22).
- Deliberately excluded: patch_size-then-resubmit, a forced edit by call 8, removing the graph tools, and any change to the YAML.

**Pre-submit gate (all CPU work):**
- lint_bundle;
- compile_submission on wheelhouse v31 with a stub model, using the discovery-import fallback;
- check the compiled request body: enable_thinking true, thinking_token_budget 4096, max_tokens 8192, 9 tools;
- unzip -l shows exactly 4 entries.

---

## 3. Daily submission schedule, 10-15 to 10-21

Every submission needs the user's approval. Space them about 24 h apart: only one can be pending, and the queue takes 14–24 h.

**Rules that apply every day:**
- Change one lever per variant.
- Never resubmit a bundle unchanged after a runtime error.
- Drop a variant after one draw if it is at least 3 tasks below the base mean.
- Promote a challenger only if its 2-draw mean is at least the base mean + 1 task and its lab mechanism metrics are no worse.

| Day | Submission | Hypothesis | Lab work the same day (quota-h) | Decision rule |
|---|---|---|---|---|
| **1 (10-15)** | **S1 = v28**, after the CPU gate plus an 8-task smoke (concurrency 1, real clock), or once the CPU gate passes if the GPU queue is over about 6 h | The 0.22 structure in our own words gives 12–13 tasks | Smoke 2; CPU compile check of v28t (include_thoughts false) to confirm enable_thinking stays true | When it scores: ≥0.20 means on track. 0.17–0.18 is within noise of Budget-Fit, so take a 2nd draw before judging. ≤0.15 or an error: read the telemetry (exceptions, overflows, rejection loops) and fix before anything else. |
| **2 (10-16)** | **S2 = v28 unchanged** (2nd draw) once S1 has returned. If S1 errored, submit the fix, or v27 to separate pipeline from prompt. | Measures our own variance and gives a pooled mean | **A4 paired lab:** v27 vs v28 on about 40 sound fastapi+rich tasks (Gluzdov mask; requests/httpx dropped), concurrency 4, full telemetry (8–10) | v28 is the base if pooled LB ≥ 11.5 tasks and lab resolved ≥ v27 − 2 with mechanism metrics no worse (rejections, overflow, compactions, no-edit rate) |
| **3 (10-17)** | **S3 = v28t** (include_thoughts false, thinking 4096, otherwise identical) if its lab probe passed; otherwise a 3rd v28 draw | Not carrying old thoughts shrinks the context, giving fewer compactions/overflows and faster prefill; continuity may suffer | **A6 probe:** 10 tasks paired v28 vs v28t with per-request logging (4). **Runtime calibration:** 10 tasks at concurrency 1 (3) | v28t goes to the LB only if peak prompt tokens fall ≥20%, compactions fall ≥30%, s/task fall ≥10%, and resolved stays within 1 |
| **4 (10-18)** | **S4 = v28t draw 2** if S3 ≥ v28 pooled mean − 1; otherwise v28 repeat | Confirm or reject the lever with 2 draws | Analyse A4 traces: what kills tasks (no-edit, rejection loops, overflow, wrong edit) | Promote v28t only if its 2-draw mean ≥ v28 mean + 1 |
| **5 (10-19)** | **S5 = repeat of the best-mean bundle** | Harvest noise once the base is ≥13 | Build v28b: one change targeting the dominant failure from the day-4 traces (e.g. a one-line progress note per milestone if compaction amnesia dominates; stricter output caps if overflow dominates) | — |
| **6 (10-20)** | **S6 = v28b** if it passed a 16–24-task paired lab gate (6), otherwise repeat the best | The fix for the dominant failure gives +1 task | Runtime check of v28b (it must stay within base + 5% s/task) | Same promotion rule as above |
| **7 (10-21)** | **S7 = the best by pooled mean**; weekly review | — | LoRA G0/G1 decision (section 4); plan week 2 | If base pooled mean ≥13: spend at least half of the slots on repeats. If it is <12: rewrite the parts of the prompt where we departed from the recipe's structure. |

**Next levers, in order, each gated in the lab:**
1. max_tool_calls 30, only if the runtime p95 projection is ≤10.5 h. 36 calls breached 12 h (samvalladares); 32 calls at 8 min timed out (748168).
2. search_similar_code allowed once as a fallback after an empty grep. Lab only, since its value is for private repos (745998).
3. thinking_budget 2048, only as a runtime hedge (Ayush 50 vs 48 is within noise).

**Not on the critical path:** sub-agents, skills, temperature changes, 12B (it fails in the scorer, 749259).

**Final 2 picks (by 12-02):** rank bundles by pooled mean, never by best single draw. Pick 1 is the best-mean bundle. Pick 2 is the runner-up if it is within 1 task of the best, otherwise another draw of the best.

**Week 1 GPU quota:** about 20–23 of 30 quota-h.

---

## 4. LoRA / training track

**Current verdict: NO-GO for the main track. GO only for free data logging and a cheap plumbing canary.**

| Evidence | Grade | Direction |
|---|---|---|
| No LoRA submission in the corpus reports an LB number | M (absence) | against |
| Gluzdov SFT on own traces (rank 16, 412 turns, 23 tasks): NLL −25 to −41%, but resolved 2/32 vs base 4/32 | M | against |
| Stronger models in the same harness gain only +4–5 of 124 tasks; distilling DeepSeek gave about +5 | M local | caps the upside |
| HOST: adapters do apply; the sample adapter touched only layer 0; rank ≤64 bundles have scored | HOST | plumbing works |
| Startup OOM without `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1`; the KV cache falls to about 27.7k tokens with it; "Notebook Threw Exception" reports; about 11% slower decoding | M/R | risk |
| Yurnero's hints of compute and "tune smaller models" | S | weak for |

**Stages** (kill date 11-08; this mostly uses TPU hours, which nothing else needs):
- **L0, data logging (from day 2, no extra cost).** The lab logs the full reasoning text, tool calls, results and token counts for every A4/A6 run. Train on fastapi/requests/httpx only; hold out Rich.
- **G0, base gate (about 10-20).** v28's pooled LB ≥0.20. If not, stop: an adapter will not fix a weak base.
- **G1, plumbing canary (week 1–2; about 3 quota-h and 5 TPU h).** Export a random rank-8 adapter on all 60 layers from our own trainer, in the scorer's key layout. Serve it through the official VllmServer path with the env fix. Pass all of:
  - 240 "Successfully loaded LoRA weights" lines;
  - top-20 logprob shift ≥1.25 nats;
  - a zero-B copy shifts ≤0.13 nats;
  - a 24k-token prompt plus generation completes with no stall;
  - a request with a 20k prompt and max_tokens 8192 does not hang (this exceeds the 27.7k KV);
  - decoding ≤15% slower.
- **G2, data (about 10-27).** At least 80 filtered resolved trajectories from at least 35 tasks, with thoughts present on at least 90% of turns. Filter: resolved and sound, first edit by call 12, ≤28 calls, one tool call per step, no test edits, no identical resends. Add TPU rollouts of the unquantized twin if short (10–15 TPU h, no seed, thinking not capped).
- **G3, offline quality (about 11-01; about 12 quota-h).** Rich-44, 2 seeds, base vs L-A (full-turn loss) vs L-B (tool-call-only loss).
  - Pass all of: resolved ≥ base summed over both seeds; rejected edits down ≥30%; no-edit rate not higher; thought tokens per call within ±30%; s/task ≤1.12× base; 0 unknown-tool calls; 0 hangs.
  - Training config: rank 16, alpha 32, all q/k/v/o/gate/up/down modules on all layers, lr 1e-4 cosine, ≤2 epochs, on the unquantized QAT twin (HOST 748287), TPU v5e-8.
  - RunPod is a fallback only, with the user's approval.
- **G4, LB (11-03 to 11-07; 2 submissions).** Adopt only if the mean of 2 draws is ≥ the v28 mean + 1 task. If the time projection with the 11% slowdown exceeds 10.5 h, set max_time_minutes to 7.

**How to verify the adapter is applied:** run these on the exact zip we will submit, not a rebuilt copy.
1. The compiled request's model string is `openai/<adapter_name>` (`adapter:` on the root agent).
2. The vLLM DEBUG log shows the load-line count and no skipped modules.
3. Logprob A/B against the base model on fixed prompts, and the zero-B control within noise.
4. The safetensors keys follow `base_model.model.model.language_model.layers.N.<module>.lora_{A,B}.weight`, and `layers_to_transform` is absent.

**12B:** blocked until the HOST confirms a 12B submission has scored. If unblocked: Rich-44 A/B, about 6 quota-h; go only if resolved ≥ 31B − 2 tasks at ≤0.6× the time.

---

## 5. Risks that zero tasks or the whole run, and how v28 avoids them

| Risk | Scope | Evidence | How v28 avoids it |
|---|---|---|---|
| 12 h overrun | Whole submission errors | HOST (747519/745805); 36 calls broke 12 h; Murugesan's 8 min timeouts | Keep the exact 240/28/8/80 that completed for 20+ teams; runtime calibration on day 3; any variant must stay within base + 5% s/task |
| Context overflow | Patch lost even after edits (44/44) | 744692, 745977, 747791 | 8192 output; head/tail caps; line-range reads; capped diff; tail 25 on tests; v28t probe |
| Compaction amnesia (summary drops tool calls) | Wasted calls, no edit | 747186 | Keep outputs small so the context stays under about 14k; progress note is a candidate for v28b |
| Unknown tool name or array-arg parser hang | Exception, or a frozen server for all later tasks | 745805, 745138, 746336 | No skills or custom tools; graph tools declared but forbidden; no array-typed tool is ever called |
| Braces in the instruction (ADK state templating) | Exception on every task | honghanhhh/samvalladares asserts; JudgeGuard hazard | Lint fails on `{`, `}` and backticks |
| .pyc in the zip, or wrong upload name | "Notebook Threw Exception" / HTTP 400 | 749200; prvsiyan | Deterministic 4-file zip, `unzip -l` check, file named submission.zip |
| Edit-rejection loops | No-edit task | 105/524 rejected; streaks of 14–27 | Never resend; 1–5 line anchors; no docstrings; heredoc fallback after 2 failures |
| Empty patch from never editing | Task = 0 | 38% with the default prompt | Mandatory edit by call 12; never conclude "no change needed" |
| Scratch or test files in the diff | Patch fails to apply | 747857, 747923 | /tmp scratch; git status --short; git checkout of tests (test edits are also dropped since 8 Oct) |
| Literal command examples cause malformed tool names | Wasted calls | 31% vs 5% (745143) | Commands described in prose, no code fences |
| Lab image Python 3.13 / torch 2.11 breaks the wheelhouse | Lab unusable, not scoring | 749505 | Pin the lab notebook environment; does not affect the scorer |
| LoRA startup OOM or KV shrink | Whole submission | 749191, 745364 | No adapter in v28; LoRA only after G1 |

---

## 6. Open questions to verify in our Kaggle lab before submitting

| # | Question | How to check | Cost |
|---|---|---|---|
| Q1 | Does v28 compile on wheelhouse v31, and does the request carry enable_thinking true, thinking_token_budget 4096, max_tokens 8192 and 9 tools? (Apex claims the budget is not forwarded.) | compile_submission with a stub model; dump the request body | 0 GPU, about 0.5 CPU-h |
| Q2 | Is our virtual clock still right now that 0.2.13 carries thoughts (prompts grow, so prefill time is not in the per_call/per_token model)? What is the real mean and p95 s/task for v28? | 10 tasks at concurrency 1, real clock; project 15 min + 120 × (mean + 30 s) ≤ 10.5 h | about 3 quota-h |
| Q3 | Does v28 cut rejected calls, overflows, compactions and no-edit rate against v27 without losing resolved? | A4 paired on about 40 sound tasks | 8–10 quota-h |
| Q4 | With include_thoughts false and budget 4096, is thinking still on, and does it shrink the context without losing solves? | CPU compile check, then a 10-task paired probe with request logging | 0.5 CPU-h + about 4 quota-h |
| Q5 | Does submit_patch end the session? | Inspect the event log of 1–2 smoke tasks for calls after submit | 0 extra (part of the smoke) |
| Q6 | Does the smoke show 0 exceptions, 8/8 non-empty patches, and no identical-rejection streak >2? | 8-task smoke | about 2 quota-h |
| Q7 | Which scorer compaction is live: interval 15 vs 5, threshold 14336 vs 32768? | Only the HOST can answer; ask in 744692/748584. Our lab uses 15/2/14336/5 like the official notebook | 0 |
| Q8 | How tight is the 0.22 cluster? Count teams at 0.20, 0.22 and 0.24 to estimate per-draw sd. This sets how many repeat draws are worth it. | Download the public LB CSV (Kaggle API; needs the user's network access) | 0 GPU |
| Q9 | Should we run the public 0.22 zip as a lab-only control (never submitted)? | **The user decides** under the no-copy rule. Without it, v27 is our control | about 4 quota-h if approved |
| Q10 | LoRA plumbing: do the KV size, a 20k prompt + 8192 max_tokens, and the load lines all work under the scorer's env fix? | G1 canary | about 3 quota-h + 5 TPU h |

**Total for Q1–Q6:** about 17–20 quota-h this week, within the 30 h quota. Nothing here needs RunPod; its remaining balance of about $0 should not be touched without the user's approval.

**Files:**
- Draft v28 bundle: gemma_agent/bundle_v28/ (YAML identical to v27; prompt updated today)
- Lint: (scratchpad)/oct15/plan/lint_bundle.py
- Overlap check: (scratchpad)/oct15/plan/overlap.py (arguments: scratchpad oct15 dir, n)
- v27, unchanged: /home/user/Markov-chain-/gemma_agent/bundle_v27/
- Lab harness: /home/user/Markov-chain-/gemma_agent/lab/labworker.py