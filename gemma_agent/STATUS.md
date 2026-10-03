# Gemma 4 Developer Agent: status report (2026-09-28)

## How the competition is scored

- We submit a declarative Google ADK agent bundle (`submission.zip`), not code. The host runs it on
  `gemma-4-31b-it-qat-w4a16-ct` (vLLM, 4x L4, 32k context) against hidden SWE-style tasks
  (real issues from Python repos such as fastapi, rich, requests).
- Per task: Phase 1 runs our agent in a sandbox (our `eval_config.yaml` caps it at 5 minutes);
  Phase 2 applies the resulting git diff, adds the maintainers' hidden tests and runs pytest.
  A task counts as resolved only if pytest exits 0.
- Score = resolved tasks / all tasks in the split (the resolution rate, 0.0 to 1.0).
- The public leaderboard uses part of the hidden tasks (about 58). The final ranking uses the
  private part, scored with the 2 submissions we select. We only ever see one number per
  submission; per-task logs of scored submissions are not available.
- Constraints: 1 submission per day; tasks run one after another and the whole run must finish
  in 12 hours (v1, v2d and v2e failed on this), so each task gets at most about 5 minutes.

## Leaderboard history

| Date | Bundle | Public score |
| --- | --- | --- |
| 09-24 to 09-26 | v1, v2d, v2e | error: exceeded the 12 h runtime |
| 09-27 | v3: single lean agent | 0.05 |
| 09-28 | v7: fixer + scout sub-agent + swe-tools skill | 0.08 |
| 09-29 (planned) | v11: single-argument tools only, backtick-free prompts | pending |

Leader: about 0.15. Top 10: about 0.13.

## How we test

| Test bed | What it is | Strength | Weakness |
| --- | --- | --- | --- |
| Leaderboard submission | host runs the bundle on the hidden tasks | the real score | 1 per day, one number only, no logs |
| RunPod GPU replica (`gpu/runpod_lab.py`) | one rented 48 GB GPU serving the exact Kaggle stack (vLLM 0.19.1, the Kaggle weights, gemma4 parsers); localeval with LLM_BACKEND=vllm | same serving stack as the scorer, no queue, about $1 per 32-task run of one bundle | 6 tasks at a time (KV cache ~131k tokens); local grader, not the hidden tasks |
| Kaggle GPU lab (`lab/make_lab.py`) | private notebook running the official harness and the exact model on 4x L4 | real harness, full traces, free | Kaggle GPU queue can take hours; one run of 2 bundles x 16 tasks takes about 2.5 h |
| OpenRouter replica (`localeval/`) | our copy of the harness; Gemma 4 31B served by OpenRouter hosts | fast (16 tasks in about 20 min), full traces | paid; different hosts and tool-call parser than the real vLLM |

Task sets: 16 "lab" tasks (8 fastapi, 6 rich, 2 requests) and 16 random held-out tasks from the
same public task file, so improvements are checked on tasks we did not tune on.

## Results so far (16 lab tasks unless noted)

| Bundle | Real harness (Kaggle lab) | OpenRouter replica (thinking off) |
| --- | --- | --- |
| v3 | 5/16 | - |
| v5 | 6/16 | - |
| v6 | 5/16 | 5/16 |
| v7 | queued (Lab 4) | 5/16; held-out 5/16 |
| v8 | - | 5/16 |
| v9 | - | 6/16 |
| v11 | queued (Lab 4) | - (OpenRouter credit used up) |

## RunPod GPU replica results (2026-09-28, 16 lab + 16 held-out tasks)

| Bundle | Lab 16 | Held-out 16 | Total |
| --- | --- | --- | --- |
| v7 | 5 | 7 | 12/32 |
| v11 | 6 | 5 | 11/32 |
| v12 | 6 | 4 | 10/32 |

14 of 32 tasks are solved by at least one bundle. No tool-call corruption appeared on the replica
for any bundle; v11/v12 lose tasks to context overflow (6 each) from reading many lines. The
replica still overestimates the public score (v7: 37% here vs 0.08 public), so the hidden tasks are
harder than ours. GPU spend: $3.20 of $10.


### v13 (2026-09-28 evening), clean GPU-replica runs

| Set | v13 | v7 | v11 | v12 |
| --- | --- | --- | --- | --- |
| 32 analysed tasks | 10 | 12 | 11 | 10 |
| 16 fresh tasks (never used for design) | 7 | 5 | - | - |
| total 48 | 17 | 17 | - | - |

v13 = fixes for every failure cause found in 96 traced runs (edit guards, run.py loop breaker, repro
memory, same-code sweep, public-API repro, evidence-based scout). It solves tasks no earlier version
solved (rich_3480, fastapi_14873, fastapi_14349) but loses others; the net is a tie. Single runs of 32-48
tasks cannot resolve differences of 2-3 tasks, so bigger evaluations (all 125 valid tasks) are needed to
measure real progress. RunPod spend so far: $6.86 of $10 (including ~$2 lost to proxy/host problems).


### v14 (2026-09-29): public-baseline settings, GPU replica

v14 = the settings shared by the public 0.10-0.12 notebooks (temperature 0.2 / top_k 40, native
read_file/edit_file/write_file, short low-temperature scout, 50 tool calls) plus our checks.
Result: 8/48 (v7 17/48, v13 17/48). Two causes:
- Measurement: read_file contexts tripled prompt tokens per task (394k vs 135k), so with 6 tasks
  sharing one GPU each call took 9.4 s and 11 tasks hit the 15-minute wall clock after only 20-40
  calls (on Kaggle one task runs alone at ~2.5 s/call). The replica's wall-clock cap is unfair to
  context-heavy bundles; future runs should cap LLM turns and tool calls instead.
- Real: at temperature 0.2 the model repeats itself exactly when stuck: 32 identical failing
  edit_file calls (requests_7505), 48 identical git grep calls in the scout (rich_3067), the same
  pattern that made us leave T=0.2 in v4b. The public 0.10-0.12 vs our 0.08 is 2-3 public tasks,
  within noise; no public design explains 0.13-0.15.
Not submitted.

## What we learned

1. **Runtime**: without a per-task time cap the hidden run exceeds 12 hours (3 failed submissions).
2. **Tool-call corruption on the real harness (biggest finding)**: vLLM's Gemma 4 parser breaks
   tool calls with several text arguments when the model closes a string with a backtick. Example
   from Lab 3: `run_skill_script` received `file_path="scripts/install.py`,skill_name:"` and failed
   105 times in one task; `edit_file` lost `old_string` 65 times in another. The model copies its
   own broken call, so 7 of 16 v6 tasks ended with no patch at all. OpenRouter hosts do not show
   this, which is why replica and leaderboard numbers disagree.
3. **Edit failures in the replica**: 61 of 92 `edit_file` calls in v7 failed on escaping
   (`\n`, quotes, backslashes). Line-number editing (`edit.py`) cut this to 1 failure in 42.
4. **Unverified fixes**: the agent often "verified" by calling internals or an API it invented;
   the maintainers' tests use the public API, so these patches failed.
5. **Loops**: identical commands repeated 20-65 times (degenerate repetition, thinking off).
6. **Replica bugs we fixed**: a hidden 4096-token thinking budget (the scorer runs with thinking
   off) and a pytest import mode that made correct patches fail.
7. **Out of reach**: about 2 of 16 lab tasks need names the issue never mentions or a 250-line
   refactor.

## The v11 design

- Root agent `fixer`, tools: `run_command`, `get_status`, `submit_patch`, the `scout` sub-agent
  (fresh context, read-only, returns requirements / locations / repro), and the `swe-tools` skill.
- Only single-argument tools are used for real work. Reading and editing go through
  `run_command` plus our skill scripts:
  - `show.py FILE A B`: numbered lines
  - `edit.py FILE A B <<'EOF' ... EOF`: replace a line range, with no text matching;
    rejects broken heredocs, fixes off-by-a-few indentation, checks syntax
  - `check.py --repro /tmp/repro.py`: runs the repro without and with the change, then the
    related tests, and prints a VERDICT
  - `locate.py`: ranks the code relevant to the issue
- The prompts contain no backticks, reproduce first through the public API, and tell the model to
  rewrite a malformed call instead of repeating it.

## Expectations

- v11 targets the failure that caused most no-patch tasks on the real harness. If it removes
  most of them, we expect roughly 0.10-0.14 public. Crossing 0.15 is possible but not yet
  supported by data: v11 has not run on the real harness yet.
- 0.50 is far above what anyone reaches in this competition (the leader is at about 0.15 with
  the same model). A realistic goal is the top 10 (about 0.13+).

## Next steps

1. Lab 4 (v11 vs v7, real harness) once Kaggle starts it; if it stays queued, the v11 submission
   itself is the real-harness test.
2. From Lab 4 / v11 traces: remaining loop and wrong-fix patterns, then v12.
3. Keep 1 submission per day; select the best 2 for the final ranking.

## Repository map

```
gemma_agent/
  bundle_v3 ... bundle_v11/   agent bundles (v7 = last submitted, v11 = next)
  skill_src/                  swe-tools skill sources and generator (make_skill.py)
  localeval/                  replica harness: env, tools, runner, grader, OpenRouter client
  lab/make_lab.py             Kaggle GPU lab kernel builder
  build.py, official_check.py submission build and official compile check
  README.md                   design notes and submission log
```

## 09-29 late: v15/v16 paired result, v17 built

- Paired GPU replica (holdout + fresh):
  - v16 9/30 vs v13 9/30 on the same tasks (won fastapi_5077, lost rich_4077).
  - v15 8/28 vs v13 8/28.
  - Both are ties, so neither is submitted.
- The diagnosis of the v15/v16 traces found:
  - The planner mostly hurts: wrong fixes, and empty replies when its thinking hit the token cap.
  - The maps describe the newest commits, so they mislead on older checkouts.
  - Loops on repeated views persist.
  - The "EOF%" junk made bash exit 1 after an applied edit.
  - The slowness comes from LLM time, not tools.
- v17 = v13 plus general fixes only:
  - show.py refuses a third view of the same unchanged lines and shows the diff and repro result instead.
  - edit.py ends with EDIT APPLIED and reruns the remembered repro.
  - run.py writes and runs a heredoc script in one call and remembers repro*.py.
  - New where.py lists definition, set/pass and read sites.
  - locate.py adds case-insensitive and sub-token fallbacks.
  - check.py's sibling sweep ignores the patch's own added lines, always adds tests by changed names, and fails an empty patch.
  - Prompt:
    - seed the repro from the closest existing test;
    - check every value of settings and environment variables;
    - never submit an empty patch.
  - No maps, no planner.

## 09-30 early: v17 result (38 of 42 so far) and v18

- v17 on the GPU replica, counted by resolved_env:
  - 18/38 solved, where v13 solved 15 of the same 38.
  - Won 5 tasks v13 failed: rich_3676, fastapi_5077, rich_3777, rich_4075, rich_3718.
  - Lost fastapi_14616 and fastapi_14349.
- New failure class: 6 context overflows (32k tokens), where earlier versions had 1-2.
  - One is a loop: an edit whose range also covered a needed line, `) -> Dict[str, Any]:`, was refused about 50 times in a row.
  - The others are long explorations of 50-70 calls, most of them file views.
- v18 = v17 plus two fixes:
  - edit.py:
    - when a refused edit compiles with a one-line range change, it names that exact command;
    - if the same refused edit is sent again, it applies that correction and says so.
  - The tools count how much text has entered the model's context (about 2.7 characters per token), warn at about 45k characters and demand check-and-submit at about 58k.

## 09-30 00:50 UTC: v17 submitted

- Final replica results on 42 tasks (resolved_env; v13 counted as best of its two runs):
  - v17 19/42. Wins: rich_3676, fastapi_5077, rich_3777, rich_4075, rich_3718. Losses: rich_3130, fastapi_14616, fastapi_14349.
  - v18 18/42, with only 3 task flips against v17.
    - The context overflows fell from 6 to 2 and there were no time-budget endings; median time was 282 s against 396 s.
    - The context warning fired in 23 of 42 tasks, which may be too early.
- v17 was submitted under the pre-set rule: the higher total, and at least +2 over v13.
- Spend: RunPod about $2.3 for this pod.

## 09-30 02:40: v19 replica result

- v19 = v18 plus:
  - context warnings recalibrated (66k/80k characters, never "revert to empty");
  - show.py accepts A-B, A:B and A,B and prints the next range;
  - check.py flags a repro that imports private modules;
  - prompt: submit only after check.py; keep existing behaviour; honour "breaking / postponed";
  - install.py resets the guard state.
- Result: 18/42 (v13 17 on the same tasks).
  - Wins: rich_3676, requests_6592, rich_3718. Losses: rich_3480, fastapi_14349.
  - Confounded: this pod was an A40, much slower than the L40S used for v17/v18.
    - Median 741 s (v18: 282 s); 13 tasks ended on the time budget; 3 were lost to LLMError (14978, 14099, 14448).
- Status: v17 19, v18 18 and v19 18 on 42 tasks are within noise of each other, all 1-2 above v13.
  - The replica cannot separate them further. The v17 public score decides the direction.
  - Spend on this pod: $0.83.

## 09-30 midday: v17 public 0.08; where the gap comes from

- Public scores: v7 0.08, v13 0.10, v17 0.08. With about 58 public tasks, 1 task = 0.017, so all three are within 1 task. The leaderboard cannot separate them.
- Replica about 40% vs public about 10%:
  - Not the task mix. The harness's own difficulty tiers put our 42 tasks at 18 Easy, 19 Medium and 5 Hard, similar to the public 129. Our solve rates are Easy about 75%, Medium about 25%, Hard 0%.
  - Not agent speed. Kaggle's 4x L4 lab ran about 3.6 s per call, faster than our shared replica at about 12 s.
- Official harness vs replica (the official harness now runs locally: gemma_agent/official/run_official.py):
  1. Any model or ADK exception drops the patch: a context overflow 400, or an unknown tool name. The replica kept the diff.
  2. On Kaggle the prompt advertises search_similar_code, get_code_neighbors and get_code_subgraph (graph data exists for every task). Our bundles did not declare them, so a call to one kills the session. The v5 lab run died on 'grep_search'.
  3. Compaction: history is summarized by an extra LLM call above 14336 tokens (32768 in the README). The replica has none.
  4. The replica grader is lenient (failures that are a subset of the gold's failures still pass). The official grader needs pytest exit 0.
- Across 10 runs: 25 of 42 tasks were solved at least once and 17 never.
  - Runs that never ran check.py resolve 6% (5/85). Half never edited, and most ended with an empty patch. The real bottleneck is deciding the change on Medium tasks.
  - With the check it is 61-68%; an OK or FIX verdict barely predicts the result.
- A best-of-N ceiling estimated from per-task solve rates gives about 22/42 at N=3 with a perfect pick. Reaching 30/42 needs the never-solved Medium tasks, not only reliability.
- Running now:
  - official-harness v17 vs v20 (v20 = v19 + all advertised tools declared);
  - replica oracle diagnostics O1 (gold file and function given) and O2 (plus the hidden tests), to measure how much is lost at localization vs spec vs implementation.

## 09-30 afternoon: oracle diagnostics and official-harness runs

- Oracle diagnostics (replica, v17, 29 tasks: 17 never solved + 12 coin flips):
  - O1 (gold file and function given): 1/17 never-solved, 6/12 coin flips.
  - O2 (plus the hidden tests): 3/17, 9/12.
  - Knowing where and what does not unlock the hard tasks. In O2, 8 of the 17 never ran a test and 6 overflowed.
- Gold size vs solvability (42 tasks):
  - 0-10 lines: 18 tasks, 15 ever solved.
  - 11-30 lines: 14 tasks, 9 ever solved.
  - 31-80 lines: 3 tasks, 1 ever solved.
  - 81+ lines: 7 tasks, 0 ever solved.
  - The realistic ceiling is about 32 tasks, so 30/42 means solving the small-fix tasks almost every time.
- Official harness (gemma_agent/official/run_official.py, 15 min, pods A6000/A40, 6 jobs):
  - v17 12/40 and v20 13/42. Replica v17 was 19/42.
  - 17-20 timeouts: the pods are about 5x slower per call than Kaggle.
  - Requests tasks fail on local environment differences.
  - One v20 context overflow lost its patch.
- Compaction is real in the official harness: at 14336 tokens it fired in 24/42 tasks, and the prompt dropped from about 14.5k to about 5.5k tokens. Whether the Kaggle scorer uses 14336 (host notebook) or 32768 (README) is unanswered.
- Kaggle GPU lab 5 is running v17 vs v20 on 16 tasks with real 4x L4 timing, the official harness and compaction at 14336.
- New tool: status.py (patch, repro result, last verdict, files viewed) to re-orient after compaction.

## 09-30 evening: Kaggle lab 5, thinking test, v21

- Kaggle lab 5 (real 4x L4, official harness, 5 min, compaction 14336; patches regraded locally):
  - v17 11/16, including all 8 of the replica's always-solved tasks. The agent behaves on Kaggle as it does on the replica.
  - v20 9/16. Its native read_file (multi-argument) came back corrupted by the real parser (`start_line\"`). The scout looped on it until the context overflowed, and the patch was dropped.
  - Rule: never add multi-argument tools.
- Thinking test (O2 oracle with thinking on, 2048 budget): 1/17 never-solved and 2/12 coin flips, against 3/17 and 9/12 with thinking off.
  - 20/29 hit the time budget, with a median of 21 calls in 15 minutes.
  - Thinking is too slow for a 5-minute budget: keep it off.
- v21 = v17 + status.py, edit range repair, show.py range syntax, a private-import repro check, and the submit-after-check and keep-behaviour rules.
  - Context warnings are disabled: under compaction the cumulative count is wrong.
  - Kaggle lab 6 (v17 vs v21, 16 improvable tasks) is running.

## 09-30 night: labs 6-8 (Kaggle 4x L4, official harness, regraded locally)

| Bundle | Hard 16 (lab6 set) | Reliable 16 (lab5 set) | Total 32 |
| --- | --- | --- | --- |
| v17 | 3 | 11 | 14 |
| v21 | 4 (lab6) / 4 (lab7a) | 11 | 15 |
| v22 (no scout) | 3 | 13 (keeps all 11 of v17's) | 16 |
| v22, 8-min cap | 2 | not run | not run |

- The 8-minute cap does not help: 9/16 still time out and patches are empty more often. The hard tasks are capability-bound, not time-bound (consistent with the oracle tests). Keep 5 minutes.
- No submission on 10-01: v22 is +2 over v17, below the +3 bar and far from the target.
- Kaggle GPU used this week: about 12-15 of 30 h.

## 10-01 slot: skipped

- No bundle beat v17 by the required +3 on the 32 lab tasks: v22 16, v21 15, v17 14.
- Kaggle GPU quota is exhausted until 10-03 00:00 UTC (a 4x L4 kernel bills about 2 quota-h per wall hour).
- Built and committed: v23 solo-plus and the concurrent lab kernel (offline tests pass).
- In progress: v24 duo (two parallel attempts plus pick_patch).

## 10-01: v23 / v24 / concurrent lab kernel built and validated offline

- v23 solo-plus (single agent, 5 min):
  - check.py never stashes; it uses a base clone. This fixes 4 lost patches, 3 of which regrade as resolved.
  - Session clock anchored on _swegemma_baseline; time caps; src PYTHONPATH.
  - 15 s script timeouts with a hang hint; a state line first in every helper output, with output capped at 4500 chars.
  - Anti-churn (STOP rewriting / EDIT NOW); 1536 output tokens.
  - Offline suite 119/119 on fastapi, requests, rich and t17 replicas.
- v24 duo: SequentialAgent[ParallelAgent[attempt A in /workspace, attempt B in a git clone --shared], finisher].
  - pick_patch.py: hard filters, then pooled-repro pass count. Replay of 469 stored attempts: best-of-2 0.536 vs single 0.458 (87% of the oracle gain).
  - Race on the check.py GATE; deadline pick at T+225; crash-safe writes into /workspace; tripwire for B's plain commands.
  - Offline suite 164/164. Fake-LLM smoke through the real harness: 10 scenarios x 2 tasks pass.
  - Residual risk: a stray early submit_patch plus a text reply submits A's tree.
- Lab kernel: --concurrency N (one OS process per task-run), --replicates, and a branch-aware virtual clock that the helper tools also see.
  - Refit constants: 0.164 s per call + 0.0221 s per token + tool seconds (R² 0.82).
- Next: lab round K1/K2 (v22 vs v23 vs v24 on the broad48 set, concurrency 6, virtual clock) scheduled for 10-03 00:15 UTC, when the Kaggle quota resets.

## 10-01 05:33 UTC: v22 submitted (user request)

- Kaggle lab: 16/32, against v17 14/32.
- Score check is scheduled for about 12 h later.

## 10-01: v22 public result: ERROR

- Kaggle reported: "Your notebook hit an unhandled error while rerunning your code". No score.
- v17 to v22 diff analysed: every change is to sandbox-side helpers, the prompt, or removing the scout. The harness catches every per-task exception (evaluate.py / agent_runner.py); only ContainerSetupError (infrastructure) is re-raised.
- v22 ran 48 official-harness lab tasks with 0 crashes, and its time per task equals v17.
- Most likely a scorer or infrastructure failure. Resubmitting v22 is proposed to the user, pending their decision.

## 10-02 00:04 UTC: v22 resubmitted unchanged (user request)

## 10-02: v22 resubmission scored 0.10

- The identical bundle scored 0.10, so the 10-01 "unhandled error" was transient (scorer side).
- v22 ties v13 (0.10) and is above v17 (0.08). With about 58 public tasks, that is about 6 solved.

## 10-03: lab 9 (Kaggle 4x L4, official harness, 6 concurrent, virtual clock; broad48), regraded locally

| Bundle | Resolved /48 | Kaggle-env | Empty | Timeouts | Median virtual s |
|---|---|---|---|---|---|
| v22 | 20 | 15 | 4 | 10 | 136 |
| v23 | 20 | 15 | 6 | 4 | 128 |
| v24 duo | 21 | 14 | 8 | 0 | 115 |

- v23 vs v22: +5 / -5 (a tie). The tool fixes cut timeouts (10 to 4) but did not add net solves.
- v24: 7/48 tasks crashed with an empty patch: ExceptionGroup -> ValueError 'No function call event found for function responses ids' (google/adk/flows/llm_flows/contents.py _rearrange_events_for_latest_function_response) inside ParallelAgent.
  - This is an ADK bug when the history of parallel branches is rebuilt (likely together with session-wide compaction). It cannot be caught from the bundle.
  - 3 of v24's 4 losses are crash tasks. Without the crashes v24 could be around 23-24/48, but the crash rate (15%) makes it unsafe.
- Lab infrastructure: on 10-03 Kaggle's default image moved to Python 3.13 and the cp312 wheelhouse failed to install. Fixed by pinning the hosts' image; the hosts' wheelhouse is now adk_submission 0.2.12.
- Quota used: 6.7 of 30 h. No submission candidate (none beats v22 by +4).

## 10-03: v25 seq built (one agent, two sequential attempts; no ParallelAgent)

- Why: v24's ParallelAgent hits an ADK bug (7/48 crashes). v25 keeps v23's single-LlmAgent shape and runs the two attempts one after the other, orchestrated only by the helper tools (tools/_seq.py; make_skill.py --seq).
- Flow (clock = _swegemma_baseline commit time, as in v23):
  - Attempt 1 in /workspace. check.py GATE (source change, compiles/imports, repro FAILS before and passes after, no new test failure) -> FINAL at once. OK without a GATE -> "do not submit yet".
  - T+150, first helper call: attempt 1 saved (cleaned diff via a private GIT_INDEX_FILE, repro, meta) to <TMP>/.swe/<hash>/att/1; /workspace reset to the baseline through the journaled _duo.promote (never touches .swetools); first line "ATTEMPT 2: ...". The tool itself is not run, except check.py up to T+180, which checks attempt 1 first and switches afterwards unless it passes the GATE.
  - Attempt 2: its GATE -> FINAL at once; check.py OK -> pick now; T+265, first helper call -> pick. The pick reuses pick_patch's rank_key/_measure/_tests (pooled repros, one per attempt; hard filters) and writes the winner crash-safely; first line "FINAL PATCH IS IN /workspace: call submit_patch now". Empty attempt 2 -> attempt 1 restored.
  - Publisher from T+240: while attempt 2 has no compiling source change and attempt 1 had one, attempt 1 goes back into /workspace (the floor for a harness timeout).
  - Crash safety: seq.json "pending" (switch/pick) plus the promote journal; the next helper call finishes the reset or redoes the pick from the tagged snapshots.
- Build: seq hooks in _ws.py/check.py sit between "# <seq>" and "# </seq>" lines, which the solo and duo builds strip; bundle_v23 and bundle_v24 rebuild byte-identical. Prompt: v23 plus a 4-line "Two attempts" section and 4 adjusted lines (submit only after FINAL; edit by T+90).
- Offline: unit suite scratchpad/v25t/test_seq.py (fa, rq, ri, t17); fake-LLM smoke through the real harness (gate_first_try, switch_then_pick, timeout_in_attempt2) passes. Unit suite 160/160.

## 10-03 night: lab 10, v25 seq (one agent, two sequential attempts + pick_patch)

- v25: 24/48 resolved (Kaggle-env grading 18). Lab 9 on the same tasks and setup: v22 20 (15), v23 20 (15), v24 21 (14).
- vs v22: +8 / -4 (gains include 4 Medium tasks: fastapi_14349, rich_3676, rich_3772, rich_4075). vs v23: +6 / -2.
- Medium 11 vs 7 for v22.
- 48/48 runs ended normally: 0 crashes, 0 timeouts, 2 empty patches. Median virtual time 139 s.
- Meets the candidate bar (+4 over v22, no new crash class). Caveat: a single run; noise is about ±3 tasks.
- Quota used: 9.2 of 30 h.

## 10-03 23:36 UTC: v25 submitted (user approved)
