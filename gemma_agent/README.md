# Gemma 4 Developer Agent

Submission for [Google – The Gemma 4 Developer Agent Competition](https://www.kaggle.com/competitions/gemma-4-developer-agent):
a declarative Google ADK agent on `gemma-4-31b-it-qat-w4a16-ct` that fixes real
Python issues. Score = share of hidden tasks whose maintainer tests pass.

```
bundle_v2/                     current agent: SequentialAgent analyst -> coder -> verifier
bundle/                        v1: single coder with analyzer + reviewer agent_tools
build.py                       validates a bundle against the harness contract, writes dist/*.zip
localeval/                     our own replica of the swegemma harness (see below)
```

## What the harness actually punishes

Read from `HARNESS_README.md` and confirmed with local runs:

- **The 32k ceiling is prompt + `max_output_tokens`.** vLLM rejects the request
  with a 400 that is not retried, so the session ends there. With
  `max_output_tokens: 12288` a single agent dies once its history passes ~20k
  tokens; v1 lost 2 of 3 pilot tasks this way.
- **Repetition loops.** At low temperature Gemma repeats an identical failing
  call (50x `edit_file` with over-escaped quotes, 138x `read_file({})`).
- **`write_file` always writes inside /workspace**, even for `/tmp/x`, so
  scratch files leak into the patch.
- **The whole hidden run must finish in 12 hours, and tasks run sequentially**
  (host-confirmed, discussion 743063): ~120 tasks share 12 hours, about 6
  minutes each including sandbox setup and grading. Without an
  `eval_config.yaml` cap the run errors out (v1, v2d); v2e's 18-minute cap
  assumed parallel scoring. `build.py` now refuses a missing file or more than
  5 minutes per task. `timeout_seconds` is also the Phase 2 pytest timeout, so
  it must stay generous (>= 180).
- **`include_thoughts: false` disables thinking entirely** (adk_submission
  sends `enable_thinking: false`); `thinking_budget` is not forwarded to vLLM.
- **A text-only reply ends an ADK agent's turn**, so anything that makes the
  model "narrate" without a tool call stops that stage.

## v2 design

A `SequentialAgent` of three `LlmAgent` stages, each with
`include_contents: none`, so every stage starts from a fresh context and only
sees the previous stage's report (and state via `output_key` templating):

1. **analyst** (read-only): requirements, locations, plan, test files.
2. **coder** (`edit_file`, no `write_file`): implements, checks with /tmp/repro.py.
3. **verifier**: cleans the tree, runs the touched test files, separates
   regressions from pre-existing failures with `git stash`, fixes, and is the
   only stage that calls `submit_patch()`.

Sampling follows Gemma's recommendation (T=1.0, top_k=64, top_p=0.95) with a
4096-token output cap (thinking 2048), leaving each stage ~28k tokens of prompt.

## Local evaluation (`localeval/`)

A replica of the two-phase harness, built from `HARNESS_README.md`: offline
sandboxes (own network namespace, loopback only), the nine tools with the same
JSON shapes and truncation, AgentTool and SequentialAgent semantics, ADK
content assembly (`include_contents`, "For context" for other agents), nudges,
the 32k rule, and Phase 2 verification with the 4-pass apply and test reset.

```
python -m gemma_agent.localeval.goldcheck tasks.jsonl --out goldcheck.jsonl   # 123/129 tasks valid
OPENROUTER_API_KEY=... python -m gemma_agent.localeval.run tasks.jsonl \
    --bundle gemma_agent/bundle_v2 --results runs/x --gold goldcheck.jsonl --ids ...
python -m gemma_agent.localeval.inspect_trace runs/x <instance_id>
```

The model is `google/gemma-4-31b-it` on OpenRouter: the free variant first,
then fp4 hosts (closest to the W4A16 weights) under `LLM_SPEND_CAP` and a
per-task `LLM_TASK_SPEND_CAP`.

## Official compile check

The organizers published their libraries as the
`metric/gemma-4-developer-agent-wheelhouse` dataset. `official_check.py`
compiles a bundle with them exactly as the scorer does:

```
uv venv -p 3.12 wh && uv pip install -p wh/bin/python swegemma-*.whl adk_submission-*.whl adk_eval_core-*.whl google_adk-*.whl
wh/bin/python gemma_agent/official_check.py gemma_agent/bundle_v3
```

## Build

```
python gemma_agent/build.py --bundle gemma_agent/bundle_v2 --out gemma_agent/dist/v2.zip
kaggle competitions submit gemma-4-developer-agent -f gemma_agent/dist/v2.zip -m "<what changed>"
```

One submission per day, and only the 2 selected ones count, so every
submission should change one thing and be recorded in the log below.

## Submission log

| Date | Change | Local pilot | Public LB |
| --- | --- | --- | --- |
| 2026-09-24 | v1: coder + analyzer + reviewer | 1/3 | **error: exceeded 12h runtime** (no eval_config, 60 min/task default) |
| 2026-09-25 | v2d: analyst -> coder -> verifier, fresh contexts, T=1.0, 4k output | 3/6 (v2b), rich_3006 pass | **error: exceeded 12h runtime** (same cause) |
| 2026-09-26 | v2e: v2d + eval_config.yaml, 18 min/task (ref 56563641) | - | **error: exceeded 12h runtime** (tasks run sequentially; 18 min too long) |
| 2026-09-27 | v3: single lean agent, thinking off, 4 min/task, timeout_seconds 300 (ref 56592163) | - | **0.05** (first score; ~3/58) |
| 2026-09-28 | v7: fixer + fresh-context `scout` AgentTool, swe-tools skill (locate.py / check.py), no read_file (bounded `sed -n`), 5 min | thinking-off replica 5/16 (v6 5/16, but v6 overflowed 32k on 5 tasks, v7 on none) | **0.08** (ref 56623288) |

| 2026-09-29 | v13: single-argument tools (edit.py/show.py/run.py via run_command), guarded edits, loop breakers, repro memory, same-code sweep, evidence-based scout, 5 min | GPU replica (exact Kaggle stack): 17/48 = v7 17/48 (32 analysed 10 vs 12; 16 fresh 7 vs 5) | **0.10** (ref 56656319) |
| 2026-09-30 | v17: v13 + loop breaker (3rd identical view refused, shows diff + repro), edit.py EDIT APPLIED + repro rerun, run.py heredoc, where.py, locate fallbacks, sibling-sweep fix, empty-patch verdict, repro/env-value protocol; no maps, no planner | GPU replica 42 tasks (28 v13-failed + 14 v13-solved): v17 19/42 vs v13 17/42; v18 (context budget + edit range repair) 18/42; v15/v16 tied v13 | pending |
Note: before 2026-09-28 the replica sent a hidden 4096-token reasoning budget while
the scorer sends `enable_thinking=false`; only runs after commit 83769f5 match the scorer.
Lab 3 (real harness, v6): at the 5-minute cutoff the harness keeps working-tree edits even
without submit_patch, but 6 of the first 11 tasks ended with no edits at all after 35-140 calls.

### 2026-09-28 findings (Lab 3 on the real harness + trace analysis)

- Lab 3, official harness, regraded with the corrected grader: v5 6/16, v6 5/16. 7 of 16 v6 tasks
  ended with no patch.
- Cause on the real harness: vLLM's Gemma 4 tool-call parser corrupts calls with several string
  arguments when the model closes a string with a backtick instead of its string delimiter,
  e.g. run_skill_script got file_path="scripts/install.py`,skill_name:" and failed 105 times;
  edit_file lost old_string 65 times; read_file got a mangled start_line key. The model then
  copies its own malformed call. OpenRouter hosts do not show this, so only the Kaggle lab can.
- v11 therefore uses single-argument tools only (run_command + .swetools edit.py/show.py, scout
  AgentTool, submit_patch, get_status), has no backticks in any prompt, and tells the model to
  rewrite a malformed call from scratch instead of repeating it.
- OpenRouter replica (before credits ran out): v7 5/16 lab and 5/16 held-out; v8 5/16; v9 6/16.
