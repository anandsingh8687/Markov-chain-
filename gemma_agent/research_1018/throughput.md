# Throughput on the scorer hardware (4xL4, Gemma-4-31B w4a16, vLLM 0.19.1): measurements and what they allow

**Bottom line:** almost all of a task's time is token generation. On the scorer setup, v29 has essentially no spare time. Running more sequences at once raises total output but slows each one. Two parallel attempts fit in v29's time only if each attempt is about 13% leaner. Four or more attempts mean each one gets much less than v29's thinking budget. The cheapest time to win back is the waste we already have: about 44 s per task, about 1.5 h over 120 tasks.

Scripts and outputs are in `(scratchpad)/strat/throughput/`:
- `seq_traces.py` → `seq_out.txt`
- `compaction.py` → `compaction_out.txt`
- `vllm_conc.py` → `vllm_conc_out.txt`
- `kmodel.py` → `kmodel_out.txt`

## 1. Measured hardware constants (verified)

**Sequential runs** come from lab17a and lab17b: 48 task runs and 1,433 LLM steps. A step's latency is the time from the previous observation to the next model step.

**Concurrent runs** come from lab13a, 14a, 15a, 15b, 16a, 16b, 18a and 18b: 10-second vLLM log lines (`loggers.py`), using only windows where the number of running requests did not change.

| Quantity | Value | Evidence |
|---|---|---|
| Single-stream decode | **34.9 tok/s** (28.6 ms per token). Steps of 800+ tokens: 34.8 tok/s. vLLM log at 1 running request: 34.5 | `compaction_out.txt`, `vllm_conc_out.txt` |
| Fixed cost per LLM call | **0.11–0.35 s** (fit intercept; repeated `submit_patch` loop steps take 0.6 s for 19 tokens) | `compaction.py` fit, rmse 1.57 s; `trace_fastapi_14372` steps 34–40 |
| Prefill of uncached tokens | 0.335 s per 1k tokens (about 3k tok/s). Busiest 10-second window: 2,057 tok/s | fit2 in `compaction_out.txt` |
| Prefix-cache hit rate | **89–92%** (vLLM, cumulative, all 8 labs). Traces imply 89.3%: 28.9k uncached out of 270k prompt tokens per task | `vllm_conc_out.txt`, trace sums |
| Prompt length | Essentially free: about +0.07 s per 1k prompt tokens | fit, `compaction_out.txt` |
| Compaction (above 14,336 prompt tokens) | 25.1 s extra per event, 1.21 events per v29 task, so **30 s/task**. Each summary call costs about 819 output tokens and about 4.3k prompt tokens (lab15a counters minus traces, 51 events) | `compaction_out.txt`; `lab15aout/lab/metrics.jsonl` |
| Aggregate decode at 1/2/3/4/5/6 running | 34.5 / 62 / 85–87 / 101–109 / 110–120 / 124–137 tok/s | `vllm_conc_out.txt` |
| Per-stream decode at 1/2/3/4/5/6 running | 34.5 / 31 / 28.5 / 25–27 / 22–24 / **21–23** tok/s | same |
| Memory headroom at 6 concurrent | KV cache at most 28% used, 0 preemptions, requests waiting in fewer than 1.4% of samples. vLLM reports 8.74x concurrency at 32k context | `metrics.jsonl`; `lab15aout/lab/vllm_server.log` |
| LoRA serving switched on | No decode penalty: 34.9 tok/s with it (lab17) vs 34.5 without (lab15) | |

## 2. Where v29's 318.6 s per task goes (lab means over 24 runs, verified)

| Component | s/task | Share |
|---|---|---|
| Decoding 8,370 completion tokens (thinking included: 28.6 ms/token matches vLLM's own decode rate) | 239 | 75% |
| Compaction summaries | 30 | 9.5% |
| Calls after `submit_patch`: the model keeps calling tools or `submit_patch` (lab17a: 7.3 calls per task, up to 44) | 13.8 (included in the rows above) | 4.3% |
| Uncached prefill plus per-call overhead | 13 | 4% |
| Tool execution (includes one 184 s hang) | 10 | 3% |
| Grading: median 3.5 s, mean 36 s, because rich_3772's hidden tests hit the 300 s timeout every run | 36 | 11% |

Because a call itself costs almost nothing, a tool call costs whatever it generates: about 276 tokens, or 8 s. v29c36 (8 more calls) measured +60.9 ± 26 s per task, paired on the same tasks, which agrees.

## 3. The 12 h budget

- Lab clock with 120 tasks plus about 500 s of startup (vLLM came up in 402–441 s): v29 = 10.76 h, v28 = 11.59 h.
- On the scorer, v29 finished twice and v28 failed. So either scorer time per task is ×1.036–1.117 of lab time, or there are 12–37 s/task of extra scorer overhead, or there are more than 120 tasks. This is inferred; the cause cannot be identified from our data.
- Raw per-task budget on the scorer clock: 388 / 368 / 356 / 328 s for N = 110 / 116 / 120 / 130 tasks.
- The pass/fail line is poorly pinned down:
  - On the same tasks in the same run (lab17a), v28 minus v29 is only +6.8 ± 35.6 s per task.
  - v29 itself differed by 36 s between lab17a and lab17b.
  - Within-task spread between replicate runs is 77 s. Summed over 120 tasks that is only about ±7 s/task of run-to-run noise.
- **Practical rule:** treat the lab-clock limit as about 320 s per task, i.e. v29 parity. Aim for 300 s or less for a safety margin.

## 4. K parallel attempts or sub-agents (model built from the constants above)

Assumptions:
- Each branch is a full v29 clone.
- Sync tools block the ADK event loop and so serialize across branches. This is verified: swegemma builds `RunConfig(max_llm_calls=...)` with no `tool_thread_pool_config` (`swegemma/harness/agent_runner.py:801`; ADK `functions.py:973`).
- The non-LLM time of 40 s is paid once per task.
- "Sync" means all branches stop at a shared deadline. "Slowest" means waiting for the last branch, which adds 77 s × E[max of K].
- Where two numbers appear, the first uses decode-dominated windows (optimistic) and the second all stable windows (pessimistic).

| K | Per-stream tok/s | Aggregate tok/s | Wall/task, sync / slowest | × v29 | 120-task hours (sync) | Completion tok/task | Per-branch share that fits v29 wall | Total tokens/task at v29 wall |
|---|---|---|---|---|---|---|---|---|
| 1 | 34.5 | 34.5 | 319 / 319 | 1.00 | 10.76 | 8.4k | 100% | 8.4k |
| 2 | 31 | 62 | 357–360 / 405–408 | 1.12 / 1.28 | 12.05–12.13 ✗ | 16.7k | **86–87% (7.2k)** | 14.4–14.5k (1.7x) |
| 3 | 28.4–28.9 | 85–87 | 390–396 / 468–476 | 1.23 / 1.48 | 13.2–13.4 ✗ | 25.1k | 76–77% (6.4k) | 19.1–19.4k (2.3x) |
| 4 | 25.3–27.4 | 101–109 | 419–446 / 519–554 | 1.31–1.40 / 1.7 | 14.1–15.0 ✗ | 33.5k | 65–70% (5.4–5.9k) | 21.7–23.5k (2.7x) |
| 6 | 20.7–22.8 | 124–137 | 505–547 / 653–709 | 1.6–1.7 / 2.1–2.2 | 17.0–18.4 ✗ | 50.2k | 48–53% (4.1–4.5k) | 24.3–26.8k (3.0x) |

Cross-check: in the 6-concurrent labs, each task took 442–549 s of real time against 318.6 s sequential, a 1.4–1.7× slowdown. That matches the per-stream slowdown at 6 running.

**What fits in 12 h:**
- **K=2** fits only with deadline-synchronized branches each using 86% of v29's tokens. Our measured waste (13.8 + 30 s, below) is 16% of v29's LLM time, so a lean branch can keep all of v29's useful work.
- **K≥3** fits only with sub-agents that each get 4–6k tokens, below v29's per-task budget.
- "Wait for the slowest branch" does not fit for any K≥2.

## 5. Time a leaner single agent frees (s/task, then minutes over 120 tasks)

| Lever | s/task | Minutes over 120 tasks | Status |
|---|---|---|---|
| Each 1k fewer completion tokens | 28.6 | 57 | |
| Stop after `submit_patch` | 13.8 | 28 | Measured waste |
| Never compact (stay under 14,336 prompt tokens) | 30.4 | 61 | Valid only if the scorer uses 14,336. The host notebook does; the README says 32,768 |
| Cap every step at 1,024 tokens | 31.6 | 63 | Removes 13.2% of tokens; can hurt reasoning |
| Cap every step at 512 tokens | 71.6 | 143 | Removes 29.9% of tokens; can hurt reasoning |
| One fewer tool call | 8.0 | 16 | |

Token concentration: the longest 4.4% of steps (over 1,024 tokens) carry 29.5% of all tokens. The median step is 109 tokens, the 99th percentile 2,222.

## Caveats and corrections

1. **Our virtual clock underestimates by 25–35%.** `lab/labworker.py:65-72` uses 0.164 s/call + 22.1 ms/token, while v29 now runs at 28.6 ms/token, and the clock ignores compaction. v29 reads 185–233 virtual seconds against about 288 s of real agent time. Its `PARALLEL_SLOWDOWN=1.15` is right at K=2 (measured 1.11) but low for K≥3 (1.2–1.67). Any parallel design scored on the virtual clock will look about 30% cheaper than it really is.
2. **The "~4 s per step" figure in the context file is wrong.** It is really about 0.1–0.35 s per call plus about 25 s per compaction. Short calls are cheap; generated tokens are what cost time.
3. **Unverified risks for parallel designs:**
   - All branches share one workspace and one 28-call / 8-minute budget (single ctx). This is inferred from swegemma tool code.
   - One hanging command freezes every branch, because tools are sync.
   - Earlier ParallelAgent runs crashed in ADK on 7 of 48 tasks.
   - Hosts reportedly said parallel is not supported.