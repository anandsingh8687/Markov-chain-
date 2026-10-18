**LoRA fine-tuning: no-go before 12-02**

Fine-tuning won't take us from v29's ~0.15–0.18 to 0.25–0.30. That jump needs about 6–9 more tasks out of 58. The best LoRA evidence anyone has published is a loss, and the plausible upside is 0–2 tasks. It would also push v29 past the 12 h limit unless we cut its budget. And it would use up the TPU hours, about half a week of GPU quota and 2–3 submission slots.

**1. How adapters work in the scorer (verified in the v31 library code)**
All paths below are under `(scratchpad)/wh31/venv/lib/python3.12/site-packages/`.
- **Where adapters go:** they are found only under `adapters/`. A PEFT folder (`adapter_config.json` plus `adapter_model.safetensors`) counts as one adapter (`adk_submission/discovery.py:384-480`). Only `.safetensors` is allowed (`swegemma/config.py:31`). The whole zip is capped at 3 GiB (`swegemma/config.py:19`).
- **Rank:** read from `adapter_config.json` or the tensor shapes (`discovery.py:288-348`). It is rounded up to vLLM's sizes 1, 8, 16, 32, 64, 128, 256, 320, 512 (`adk_submission/server.py:59-67`).
- **How the agent uses it:** `adapter: <name>` in agent.yaml (`adk_submission/schema.py:279`, `adk_submission/resolvers/models.py:46-76`). swegemma turns this into a request for model `openai/<name>` (`swegemma/harness/agent_runner.py:64-92` and `:624-627`; `swegemma/cli.py:76-90`).
- **Server side:** vLLM gets `--enable-lora --max-loras N --max-lora-rank R --lora-modules name=path` only when an adapter exists (`server.py:757-797`).
- **"Adapter not applied" risk:** if `adapter:` is missing from agent.yaml, the adapter still loads and still costs speed and memory, but no request uses it.

**2. Where trainable weights come from (forum and notebook claims, not checked by me)**
- The host says to train against the unquantized variants on the Gemma 4 page (topic 748287).
- For 31B that is `gemma-4-31b-it-qat-q4_0-unquantized`, about 62 GB in bf16 (sauravbellam T1/T2 notebooks). The Kaggle model listing shows instances of 62,578,656,846 bytes, which is consistent. I couldn't resolve the instance names through the CLI.
- vLLM applies the LoRA on top of the 4-bit serving model. The host confirms adapters change the logits once they cover more than layer 0 (749528).

**3. Hardware and training stack (my estimates, not measured)**

| Option | Throughput | One epoch of our data (~4.7M tokens) | Problem |
|---|---|---|---|
| TPU v5e-8 | ~3,000 tok/s at 30% utilisation | ~0.5 h, +1–2 days building our own trainer | No public TPU trainer shows results: the sauravbellam notebooks have no outputs, and the gemma4-swe-kit trainer is code we may not copy |
| 4×L4 | ~200–250 tok/s, 4-bit base | ~6 h wall = ~12 GPU quota-h | Uses up the evaluation quota |
| RunPod H100 | ~1,000+ tok/s | ~1–1.5 h, fits the $10 budget | Needs your approval |

A 4-bit 31B LoRA fits on modest GPUs: denpugovkin trained a rank-8 LoRA on 2×T4 and scored 0.03/0.05 (with a 3-minute cap, so the score says nothing about LoRA).

**4. Training data**
- **Our own lab runs (counted; script at `.../scratchpad/strat/lora/count_traj.py`):**
  - The lab1* outputs hold 845 runs over 90 tasks; 328 are resolved and 310 of those have traces.
  - These cover only 42 distinct tasks (fastapi 20, rich 21, requests 1), with up to 14 copies of the same task.
  - Median trace is 27 steps; the raw text is about 5.9M tokens.
  - None of the traces contain the model's thinking. We serve with thinking on (budget 4096), so training on these teaches the format without thinking. Turning thinking off measured 23 vs 48 tasks (746250).
  - If we hold out rich for testing, about 20 training tasks remain. That is the same scale as Gluzdov's failed run (23 tasks).
- **Other models' trajectories:**
  - The host allows trajectories from other open-weight models and public datasets (746046).
  - Using Claude or GPT output is unanswered (749585), and their terms restrict it.
  - Public dataset: 1,427 curated Qwen3-Coder trajectories, CC BY 4.0 (745143). They have no Gemma thinking either.

**5. Expected gain: the evidence is negative or missing**
- **Gluzdov (own traces):** rank 16, 412 turns from 23 tasks. Loss fell 25–41%, but the adapter resolved 2/32 vs 4/32 for the base model, so his verdict was no-go (`oct15/nbtxt/dmitriigluzdov__gemma-4-task-soundness-serving-and-evaluation.txt:272-292`).
- **Stronger models as an upper bound:** DeepSeek V4 Pro and Qwen3.6-27B in the same harness beat Gemma by only 4–5 of 124 tasks, and 48 tasks were solved by nobody (747168). A DeepSeek V4.1 Flash teacher solved about 5 more (745274). Distilling them can't add more than roughly 2 of 58.
- **Leaderboard:** no public score shows a LoRA bundle beating its own version without LoRA. The 0.22 cluster is prompt-only. The 0.24 leaders haven't disclosed a method, and "the top uses LoRA" is disputed (748051).
- **My estimate:** about 15–20% chance of +1–2 tasks, so the expected value is about +0.3 tasks (~+0.005 on the LB).

**6. Risks, each measured by someone**
- **12 h overrun:**
  - Michi's rank-16, all-layer adapter on a 28-call / 8-minute bundle hit "exceeded the allowed runtime". The same bundle without the adapter scored 0.15 (57197626 vs 57088086, topic 749191).
  - LoRA decodes about 11% slower (DECEM, 749191).
  - For us: v29 averages 8,296 completion tokens per task × 29 ms ≈ 241 s of its ~319 s. Adding 11% to that gives ~345 s/task, above the ~330–340 s limit.
  - So we would have to cut the budget by about 8%.
- **Smaller memory for context:** with the scorer's setting the cache holds 27,712 tokens instead of 36–46k, below the 32k context limit. Only 1 of 194 v29 traces went above 27.7k (99th percentile is 21.0k; script `.../strat/lora/ctx.py`), so this risk is small.
- **Startup failures:** "Notebook Threw Exception" or out-of-memory with LoRA bundles is reported by several teams (749501, 745364, 749191). The host says adapters up to rank 64 have scored.
- **No way to check offline:** our lab results don't predict the LB, and a held-out set of about 21 rich tasks can't detect a difference under 3 tasks.

**7. Cost if we did it anyway**
- About 25–35 TPU h (1.5 weeks of TPU quota) plus 1–2 days of trainer work.
- About 15–20 GPU quota-h (around 60% of a week) for the startup check and held-out evaluation.
- 2–3 submissions.
- The first LB result would land around 11-08 to 11-10.

**8. Recommendation**
- **Don't start LoRA now.**
- **Reopen it only if** a scored LoRA bundle is shown beating its own non-LoRA version, or 12B becomes scorable. 12B decodes ~67 vs ~35 tok/s and is much cheaper to train, but three teams' 12B submissions currently fail (749259).
- **Cheaper fixes for the same behaviour problems:** the problems a LoRA would target show up in our v29 traces (`.../strat/lora/errs.py`, `submits.py`, `loop_time.py`):
  - 12 of 194 tasks loop on `submit_patch` 20–63 times, with a median of 80 model calls vs 29 normally and 532 vs 415 s.
  - 3.0% of tool calls fail with "mandatory input parameters are not present".

  Prompt or config changes can attack these at no training cost and with no slowdown.