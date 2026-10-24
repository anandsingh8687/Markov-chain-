I found and reproduced the cause of the ParallelAgent crash, and the crash can be avoided from inside the bundle. Wrapping the ParallelAgent in an `agent_tool` runs two LLM workers at once inside one task without hitting the bug. Expect about 1.3–1.6x more model work in the same wall time, not 2x.

All my scripts and outputs are in `(scratchpad)/strat/parallel_arch/`. "Verified" below means read in the source (`SP` = `.../wh31/venv/lib/python3.12/site-packages`) or tested offline with a fake LLM. "Inference" means not tested.

## 1. Why ParallelAgent crashes (verified)

- **What breaks:** the host notebook turns on token-based history compaction (`EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5)`, `scratchpad/nbhost2/...ipynb`). Our lab copies it (`gemma_agent/lab/make_lab.py:129`).
- **When it fires:** before every LLM call, ADK compacts history once the most recent prompt in the whole session reaches 14,336 tokens. This check spans all branches, not just the current one (`SP/google/adk/flows/llm_flows/compaction.py:35-53`, `SP/google/adk/apps/compaction.py:425-470`).
- **What the summary hides:** the summary event has no branch, so every branch sees it. It hides every event whose timestamp falls between the first and last summarized event (`SP/google/adk/apps/llm_event_summarizer.py:121-138`, `contents.py:403-414`).
- **Why parallel branches trigger it:** an agent's tool-call event is stamped when its LLM request starts (`base_llm_flow.py:937-943`), but is only saved when the reply comes back. With two branches running, branch B's call can carry an older timestamp than events branch A saved in the meantime. Compaction then hides B's call and keeps B's tool response. The next request fails at `contents.py:210-220` with "No function call event found". Single agents are safe because their timestamps always go up.
- **Upstream confirms it:** google/adk-python issue #7324. The fix (commit 0c517e7, ADK v2.5.0) was never backported to 1.x and the error reproduces on 1.36.x. The issue's workaround (patching the session service) and raising `token_threshold` are both harness-side, so a bundle can't use them. Forum: degen and the host Ryan Holbrook on 10-11 ("too risky to attempt a migration to ADK v2"); the host also suggested ParallelAgent for concurrent LLM calls, noting tool calls still run one at a time.
- **Lab evidence:** v24 crashed on 7 of 48 tasks (`scratchpad/lab9aout/lab/v24/r0/worker_logs/fastapi_13207.log`, id `chatcmpl-tool-a69057bb05d2e705`, and 6 others).
- **Offline repro** (`repro_parallel.py`: real ADK 1.36.1 and harness plugins, fake LLM, blocking tools, harness-style nudges):

| Shape | Compaction | Some slow LLM calls | Crashes |
|---|---|---|---|
| v24 shape | on | yes | 11/15 |
| plain ParallelAgent | on | yes | 4/15 |
| v24 shape | off | no | 0/12 |
| v24 shape | on | no | 0/12 |
| AgentTool fan-out | on | yes | 0/15 |
| AgentTool wrapping a ParallelAgent | on | yes | 0/15 |

- **Why the wrapper avoids it:** AgentTool runs its agent in a private runner with no app and no compaction config (`SP/google/adk/tools/agent_tool.py:235-243`, `runners.py:1429-1430`), so the crash path never runs. The workers' `output_key` values do reach the lead: AgentTool copies state changes back (`agent_tool.py:258-262`), and I confirmed `{attempt_a_report?}` is filled in the lead's instruction (`check_state.py`).
- **A second risk with a workflow root (Sequential/Parallel/Loop) plus compaction:** if the first compaction happens at the end of an invocation, the summarizer has no model and raises "No LlmAgent model available for event compaction summarizer" (`compaction.py:226-236`). This reproduced 15/15 offline (`out_v24_comp_long_short.txt`) but was never seen in lab logs. An LlmAgent root removes it.

## 2. Harness facts that limit any architecture (verified)

- **Several tool calls in one model turn run concurrently:** ADK starts one task per call and waits for all of them (`functions.py:388-405`).
- **But tool calls block each other:** swegemma tools are plain functions that call `docker.exec`, which runs `subprocess` synchronously (`swegemma/tools/execution.py:47`). FunctionTool runs them directly on the event loop (`function_tool.py:~233`). The thread-pool option exists only in live mode (`functions.py:972-979`) and the harness doesn't set it.
  - So tool time is serialized across branches. LLM requests still overlap, because vLLM keeps decoding a sent request while the client is blocked.
  - The v24 traces show this: B's call is stamped exactly when A's tool ends (rich_3953 steps 26–27, fastapi_14371 steps 57–58).
- **Gemma does emit more than one tool call per turn, but rarely:** 2 of about 6,800 lab turns had two calls in one response (v23 fastapi_14463 step 8, fastapi_13713 step 3); v24 had 0 of 1,497. I couldn't check the vLLM parser source because vLLM isn't in the local venv.
- **How the budgets count:**
  - **Time:** one `asyncio.timeout(max_time_minutes)` wraps everything, including AgentTool's inner runners (`agent_runner.py:718-783`).
  - **Tool calls:** one shared counter, `SwegemmaContext.tool_calls_used`, used by every agent including AgentTool workers (`context.py:468-551`). `submit_patch` and `get_status` don't count.
  - **Turns:** `RunConfig(max_llm_calls)` only limits the top-level run; AgentTool's inner runner gets the default of 500. Inner model calls still reach the harness through plugins (on by default), so they count toward `max_turns`; tools refuse once it's reached and the harness stops between runs.
  - **Nudges:** up to 3 in a row. Each re-runs the root: an LlmAgent root continues its conversation, while a SequentialAgent root restarts at stage 1 (`sequential_agent.py:62-63`; the App has no resumability).
  - **Timeout fallback:** on timeout the harness submits the `git diff` of `/workspace` (`agent_runner.py:1054-1078`).
- **What a bundle can configure** (`adk_submission/schema.py`):
  - **Allowed:** `sub_agents`, `agent_tool` (any agent class, including a ParallelAgent), `skills`, `adapter`, `output_key`, `include_contents` (`default` or `none`), `generate_content_config`.
  - **n>1 sampling is blocked:** `generate_content_config` accepts only the 10 fields at `schema.py:202-213`. There is no `candidate_count`, and extra keys are rejected.
  - **Callbacks are silently ignored:** the harness compiles without a callback registry (`agent_runner.py:616-628`, `callbacks.py:356`).
  - **No `exit_loop` tool:** the only tools are the 9 from `create_tools` plus skill tools, so a LoopAgent can't stop itself.
- **Workers in a separate directory need care:** `read_file`, `edit_file` and `write_file` only accept paths inside `/workspace` (`swegemma/tools/workspace.py:22-57`). `run_command` always sets `PYTHONPATH=/workspace` (`sandbox/subprocess.py:485-489`), so a worker testing in `/tmp/wt_b` must set `PYTHONPATH=/tmp/wt_b` itself.
- **Inner AgentTool histories are never compacted,** so each worker's prompt plus `max_output_tokens` must stay under 32k.
- **Throughput (fit from lab traces, `latency_fit.py`):** at 6–12 concurrent streams each stream decodes at about 64–72 ms per token, against about 29 ms single-stream. That is 2.6–5x total throughput. For 2 streams the per-stream slowdown is probably 10–25% (inference).

## 3. Architectures, ranked

**1. LlmAgent lead + `agent_tool` wrapping a ParallelAgent of 2 attempts — works.**
- Verified: compiles (`compile_check.py bundle_atpar`) and 0/15 crashes offline.
- **Clock:** lead time + the slower worker + all tool time (serialized).
- **Budget:** one shared tool-call budget. Raise `max_tool_calls` (about 45–50) but keep `max_time_minutes` at 8, because the clock is the real constraint (mean must stay at or under about 330 s per task).
- **Set it up asymmetrically:** worker A edits `/workspace` with the native tools, so a timeout still yields its patch. Worker B uses `git worktree add /tmp/wt_b` and only `run_command`.
- **Main risk:** the ParallelAgent waits for both workers, so a runaway worker burns the clock. Each worker needs a call cap in its prompt (about 12–14 calls).
- **Expected gain:** about 1.3–1.6x more model work in the same wall time. The v24 replay showed best-of-2 at 0.536 vs single 0.458 (`STATUS.md:306`), but that was with full-size attempts.
- **Skeleton:** `bundle_atpar/` (placeholder prompts).

```yaml
# agent.yaml
name: lead
model: gemma-4-31b-it-qat-w4a16-ct
instruction: !include prompts/lead.md      # uses {attempt_a_report?} {attempt_b_report?}
tools:
  - agent_tool: {config_path: sub_agents/attempts.yaml}
  - run_command
  - read_file
  - get_status
  - submit_patch
generate_content_config: !include configs/sampling.yaml
# sub_agents/attempts.yaml
name: attempts
agent_class: ParallelAgent
description: Runs attempt A (/workspace) and B (/tmp/wt_b) concurrently.
sub_agents: [{config_path: attempt_a.yaml}, {config_path: attempt_b.yaml}]
# sub_agents/attempt_b.yaml   (attempt_a.yaml: same, plus edit_file/write_file, works in /workspace)
name: attempt_b
model: gemma-4-31b-it-qat-w4a16-ct
instruction: !include ../prompts/attempt_b.md   # must contain {problem_description}; workers never see the user message
output_key: attempt_b_report
tools: [run_command, read_file]
generate_content_config: !include ../configs/sampling_worker.yaml   # e.g. max_output_tokens 6144, thinking_budget 2048
# eval_config.yaml
evaluation: {timeout_seconds: 240, max_tool_calls: 48, max_time_minutes: 8, max_turns: 120}
```

**2. Single LlmAgent (v29) — works.** Baseline: about 30 calls, 319 s per task. All budgets apply directly. Same shape as `bundle_v29/agent.yaml`.

**3. Several AgentTools in one lead turn (lead lists `agent_tool: worker_a.yaml` and `agent_tool: worker_b.yaml`) — works, but only parallel if the model emits both calls in one turn.** Verified 0/12 crashes offline, and the calls do run concurrently. The model emitted multiple calls in about 0.03% of lab turns, so it would need explicit prompting, and it falls back to running the workers one after another (2x the time). Use option 1 for a guaranteed fan-out.

**4. Sequential stages through AgentTool (lead calls `scout`, then works itself) — works.** No parallelism. Nudges continue the lead. The scout's history must stay under 32k because it isn't compacted.

**5. SequentialAgent root — works, with caveats.** Nudges restart stage 1, and there is the end-of-invocation summarizer risk above. Shape: `agent_class: SequentialAgent`, `sub_agents: [{config_path: ...}, ...]`.

**6. ParallelAgent in the main session (root or under SequentialAgent) — blocked in practice.** It is only safe if no prompt in the session ever reaches 14,336 tokens while branches overlap, and a v29-sized solver exceeds that.

**7. LoopAgent best-of-N — works, but it's sequential and has no early exit.** It always runs `max_iterations` times; the only way out early is the harness break after a patch is submitted and the agent replies with text. Each pass continues the same history unless `include_contents: none`. Costs N times the clock. Shape: `agent_class: LoopAgent`, `max_iterations: 2`, `sub_agents: [{config_path: solver.yaml}]`.

**8. Sampling n>1 / `candidate_count` — blocked** by the schema, as noted in section 2.

**9. A skill script or `run_command` calling vLLM directly — unknown and not recommended.**
- What is verified: the subprocess sandbox has no network isolation in its code, only a cleaned environment (`adk_eval_core/sandbox/subprocess_sandbox.py:24-54`). The Docker sandbox sets `network_mode='none'` (`docker.py:86`).
- Why not to use it: those calls would bypass ADK's budget counting and contradict the "environment is offline" rule. It needs the hosts' explicit approval.

**Next step:** a paired lab run of option 1 against v29 on about 40 tasks, at concurrency 1 and real clock, to measure actual seconds per task and solves before any submission.