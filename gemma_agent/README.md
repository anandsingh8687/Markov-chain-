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
| 2026-09-27 | v3: single lean agent, thinking off, 4 min/task, timeout_seconds 300 | - | scheduled |
