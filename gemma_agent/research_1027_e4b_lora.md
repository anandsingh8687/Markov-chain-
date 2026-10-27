# E4B LoRA distillation: decision memo

## 1. Decision

**Go with a smoke test, scoped down.** The full distillation program is a **no-go** for now. Two gated steps are allowed:

- **Step 0, go now.** Run a serving canary of about 0.3-0.5 quota-h, riding on the lab27 kernel (E4B s3/s4 on 87 split-A tasks, already queued for the 10-31 reset).
- **Step 1, conditional go.** Run one pilot of 5 quota-h or less (Section 3), with stop criteria written down before it runs. It may run only if all three hold:
  - the canary passes;
  - lab27 has finished;
  - at least 5 quota-h are free in a week after the main-track gates (lab25a/b, lab26) have their quota.
- **Step 2, no-go unless Step 1 passes.** This is the full program: all segments, regenerated summaries, and the sealed split-B gate.

**Probability of success**

| Event | Estimate |
|---|---|
| E4B adapter takes effect on the scorer, including the KV-shared layers 24-41, and starts reliably | 0.6-0.7 |
| Pilot passes its screen, given serving works | ~0.15 |
| Full program passes the B gate, given the pilot passed | ~0.3 |
| LoRA bundle scores above 0.10 publicly (at least 7/58) | **~3% (range 1-6%)** |
| Small Model Prize won because of LoRA | **~1%** |
| Gain over resubmitting base E4B | 1-2 points at most |

**Reasons**

1. **The effect size needed is out of reach.** Beating 0.10 needs at least 7/58 hidden, about 21/87 locally at the 31B local-to-board ratio of 0.42. Our E4B starts from 1 solve in 57 runs, and the teacher solves 34/87. So E4B would have to recover about 60% of the teacher.
   - Published SWE-SFT results recover roughly 25-35% of the teacher at 7B, with full fine-tuning on bases whose failures were scaffold failures.
   - E4B's failures are different: wrong site or logic, plus mechanics (edit_file errors 39% vs 9% for 31B; median 10 calls vs 28).
2. **The record in this competition is 0 paired wins in about 12 LoRA/SFT attempts** (4 on E4B, 1 on 12B, 7+ on 31B). The best results were ties. Drops in NLL did not change solve counts.
   - TTX's E4B null (170 trajectories, 62 issues) is the same scale as our usable data: 195 trajectories on 74 tasks, 46% of them fastapi or rich.
3. **E4B LoRA serving is unproven.** No public E4B, E2B or 12B adapter has scored (topic 752239 has no answer).
   - Our local vLLM is the unpatched upstream build.
   - The adapter-reset fix was confirmed only on 31B, which has no KV-shared (cross_decoder) layers. If E4B's late-layer weights are silently zeroed, the submission scores like base with no error.
4. **What helps:**
   - The data is same-harness and complete: thoughts, arguments and observations are faithful.
   - Compute is cheap: about 2 GPU-h per epoch.
   - The packaging was verified offline.
   - On the lab side, I checked `adk_submission/server.py:759-799`: the LoRA flags are recomputed from the adapters found (`--max-loras` = number of adapters, `--max-lora-rank` from `r`). So lab27's `max_loras=8, max_lora_rank=128` does not change the flags. They match the scorer.
   - E4B has `attn_v` in all 24 KV-owning layers, so the `k_eq_v` v_proj drop does not apply.
   - The canary's answer is useful to the paper and the forum whatever the outcome.

## 2. Plan if the gates pass

### 2.1 Data conversion

The new script is `build_sft.py` under `lora/trainingdata/`. It reuses `convert.py`, `dump_tools.py` and `split_proposal.json`. It must never open lab24 or any split-B trajectory.

**Source runs.** Resolved 31B, single-agent (excluding v31a), from these labs:
- dev: 17a, 17b, 18a, 18b, 19
- A: 20a, 20b, 21, 22a, 22b

**Pilot split.** Defined in `lora/decision/half_split.json`. The rule holds out an A task if `int(md5(repo),16) % 2 == 0`.
- Held out: 40 A tasks (39 non-interface) from 32 repos. 31B solved 14 of them.
- Train: 146 trajectories on 60 tasks (all 80 dev trajectories plus 66 from A). Capped at 2 per task: 107 trajectories.
- Full program: train on dev plus all of A (195 trajectories). The gate is then B only.

**Rendering, two passes, both inside the kernel.** No Gemma tokenizer or chat template exists on disk.

- **(a) Faithfulness pass.** Render with the teacher's own system prompt, tools and stored task_prompt.
  - Use vLLM 0.19.1 `chat_utils` (`parse_chat_messages` + `apply_hf_chat_template`) with the tokenizer and template of the served -ct checkpoint.
  - Keep earlier thoughts in history as `reasoning`. Tool messages use `role: tool` with `json.dumps(obs, ensure_ascii=False)`. Arguments are dicts. Use real tool-call ids where the logs have them, otherwise synthetic ones.
  - Compare token counts with the logged `prompt_tokens` on pre-compaction calls. Require at least 95% within ±2 tokens, otherwise stop and debug.
- **(b) Deploy pass.**
  - System message: the deploy prompt, then `\n\n`, then the identity line `You are an agent. Your internal name is "fixer". The description about you is "<deploy description>".`
  - Tools: the 5-tool schema from `req_s3.json`.
  - User message: the stored task_prompt, edited as follows. Replace the budget lines with 5 min / 32 calls / 60 turns / 180 s. Delete the Code Intelligence section. Assert that each replacement matched exactly once.
  - Drop the 3 traces that use write_file or other tools outside the 5-tool set.

**Segments.**
- Pilot: the first compaction segment only, so no summaries are needed. This is 1.55M tokens per epoch for the 107 capped trajectories.
- Full program: all segments. Regenerate the 188 summaries with base E4B from `compactions[].summarizer_prompt`.

**Labels.** Loss only on assistant spans. For each assistant message i, the label is the tokens of `render(msgs[:i+1])` that come after `render(msgs[:i], add_generation_prompt=True)`. Check the prefix property at the token level, and drop any segment that fails it.

**Masked turns:**
- the 74 malformed calls;
- turns whose tool response is `{"error":...}` (they stay in context, so the recovery that follows is still learned);
- no-action turns;
- the 2 calls in rich_3278 that hit 8192 tokens.

Final-text turns are kept.

**Validation set.** First segments of the 31B solved trajectories on the held-out A tasks, for held-out NLL only.

**Upload.** The rendered chat JSON plus the peft and liger wheels go into one *private* Kaggle dataset. This contains competition and task content, so it must never be public.

### 2.2 Training kernel

**Machine.** 4xL4, pinned image `sha256:37c64f7d...`, internet off.

**Sources:**
- `metric/gemma-4-developer-agent-wheelhouse`: transformers 5.13.1, compressed-tensors 0.15.0.1, vLLM 0.19.1 (patched)
- model `google/gemma-4/Other/gemma-4-e4b-it-qat-w4a16-ct/2`
- model `google/gemma-4/Transformers/gemma-4-e4b-it/1`
- the private dataset: peft 0.21.2, liger-kernel 0.8.5, the data

**Libraries.** Torch and accelerate come from the image; check torch 2.10.x and accelerate ≥ 0.21 in the preflight. Do not use TRL or datasets.

**Base model.** Prefer the dequantized -ct checkpoint (`run_compressed=False`), because those are the exact served weights. Accept it only if its logits on 3 prompts match vLLM's served logprobs (mean |Δ| < 0.1 nats). Otherwise fall back to bf16 gemma-4-e4b-it.

**Model setup.**
- Text decoder only. The PLE table stays on CPU and `per_layer_inputs` is passed in.
- lm_head is separate in -ct (1.25 GiB), so add that to the memory estimate.
- Gradient checkpointing with `use_reentrant=False`, SDPA attention, Liger fused linear cross-entropy and RMSNorm.

**LoRA.**
- r16 for the pilot, r32 for the full program. `lora_alpha` = r (scale 1.0; never 2). Dropout 0.
- Targets: `q,k,v,o,gate,up,down` in language-model layers 0-41. k and v exist only in layers 0-23. If the canary shows a late-layer wipe, use `layers_to_transform` 0-23.
- No PLE gate/projection, no embeddings, no vision or audio modules.

**Optimiser.** AdamW, LR 1.5e-4 cosine, 5 warmup steps, weight decay 0, clip 1.0, bf16. DDP over 4 GPUs, micro-batch 1. Gradient accumulation 2 gives an effective batch of 8 segments.
- Pilot: 3 epochs, about 40 steps. Save after each epoch.
- Before the run, fix the choice: evaluate the epoch-2 checkpoint, or epoch 1 if held-out NLL rises from epoch 1 to 2.

**Sequence length.**
- Probe 2 steps each at 8k, 12k and 16k, logging `max_memory_allocated` and seconds per step.
- Use the largest length that leaves 1.5 GB headroom. Cut longer segments at an assistant-turn boundary.
- If no attention backend runs forward and backward at head_dim 512 at 8k or more, stop. Do not build custom kernels for a long shot.

**Export.**
- Rename keys to `base_model.model.model.language_model.layers.N.<self_attn|mlp>.<proj>.lora_{A,B}.weight`.
- Write `adapter_config.json`: `peft_type LORA`, `r`, `lora_alpha` = r, `target_modules` = the 7 projection names, `bias none`, `modules_to_save null`, `use_dora false`, no `rank_pattern` or `alpha_pattern`.

**Cost.** Training costs about 0.43 GPU-h per million tokens (SDPA), with a range of roughly 0.75x to 1.5x.

| Run | Tokens | GPU-h | Wall-h | Quota-h |
|---|---|---|---|---|
| Pilot (1.55M × 3 epochs) | 4.65M | ~2.0 (1.5-3.0) | 0.4-0.75 | 0.8-1.5 |
| Full (4.73M × 2 epochs) | 9.5M | ~4.1 (3-6) | 1.0-1.6 incl. setup | 2.5-3.5 |

### 2.3 Bundle layout

Checked against `adk_submission` `schema.py` (field `adapter: str | None`), discovery and `server.py`.

```
bundle_s5L/
  agent.yaml
  prompts/system.md          # v33t prompt with graph-tool and write_file text removed (the training system prompt)
  configs/sampling.yaml      # s3: temperature 1.0, top_p 0.95, top_k 64, max_output_tokens 4096, thinking_budget 2048, include_thoughts: true
  eval_config.yaml           # s3: timeout_seconds 180, max_tool_calls 32, max_time_minutes 5, max_turns 60
  adapters/e4bsft/adapter_config.json
  adapters/e4bsft/adapter_model.safetensors
```

```yaml
name: fixer
model: gemma-4-e4b-it-qat-w4a16-ct
adapter: e4bsft
description: <exactly the string used in the training identity line>
instruction: !include prompts/system.md
tools:
  - run_command
  - read_file
  - edit_file
  - get_status
  - submit_patch
generate_content_config: !include configs/sampling.yaml
```

**Naming rules.**
- The adapter name must match `^[a-zA-Z0-9_.-]+$`.
- It must not equal the base alias; a collision silently serves the base model.
- It must not contain `gemma4`, which switches the tool role to `tool_responses`.

**Files.** Only `.safetensors` and `.json`; a `.bin` file fails validation. The r16 adapter is about 70 MB, well under the 3 GiB cap.

**Pre-upload check.** Run `lora/serve/offline_pack_check.py` on the bundle. It must show:
- `--enable-lora --max-loras 1 --max-lora-rank 16 --lora-modules e4bsft=...`
- compiled model `openai/e4bsft`

### 2.4 Lab smoke test (must pass before any eval)

Run `lora/serve/e4b_lora_smoke.py` (190 lines, not yet run) on the installed wheelhouse, with `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1`. It must show all of the following:

1. `supports_lora(Gemma4ForConditionalGeneration)` is True. Record whether the Self and Cross decoder classes still register `decoder_layers` as submodules.
2. Record `num_kv_shared_layers`, `attention_k_eq_v`, `head_dim`/`global_head_dim` and `num_key_value_heads`.
3. The server starts with LoRA: no "does not support LoRA yet" and no warm-up OOM. Startup under 15 min. Record KV-cache tokens against the base 298,464.
4. `/v1/models` lists the adapter.
5. At temperature 0:
   - a zero-B adapter equals base (max |Δlogprob| < 0.05);
   - a random adapter on layers 0-3 **and** one on layers 24-41 each change the top-5 logprobs. **If layers 24-41 equal base, the cross-decoder wipe is confirmed.**
   - 0 "No LoRA weights found for module ...decoder" lines in the log.
6. The trained adapter loads with 0 unsupported-module warnings. Its teacher-forced logprobs on 5 training turns match HF+PEFT (mean |Δ| < 0.1).
7. Decode tok/s, base vs adapter. A 20k-token prompt completes.
8. A tool call parses through the adapter id. One full harness task resolves to `openai/e4bsft`.

**Paired-lab pitfall.** make_lab mounts adapters from the **first** bundle only (`discover_adapters(first)`), so the LoRA bundle must be listed first. Keep the parser guard on, and require 0 LABGUARD events, since each one would be a hang on the scorer.

### 2.5 Evaluation gate (full program)

**Set.** Sealed split B, the 68 non-interface tasks, one sample per arm.

**Arms:**
- s3 (best base E4B bundle)
- s5L without the adapter (separates the prompt effect from the adapter effect)
- s5L

That is 204 runs, about 2-3.5 wall-h or 4-7 quota-h.

**Pass, fixed before the run:**
- s5L beats both s3 and s5L-without-adapter by at least 8/68 (about the 12-point MDE);
- 0 LABGUARD events;
- malformed-call and edit_file-error rates no worse than base;
- token-time at most 1.25x (to cover the LoRA decode overhead).

**After a pass:** one leaderboard check in a daily slot. If two submissions in a row fail at startup, stop.

**Team decision needed.** The user rule (at least 2/12 on smoke and at least 10/87 on A) cannot be applied cleanly, because training uses A tasks. Using the B gate instead needs the user's explicit approval. So does spending a final pick on E4B (that gives up a 31B hedge).

**Full-program total after the pilot:** about 7-11 quota-h plus one leaderboard slot. Including canary and pilot: about 11-16 quota-h.

## 3. Cheapest first experiment (5 quota-h or less)

**Experiment 0, the canary: 0.3-0.5 quota-h, in lab27.** Before lab27's own eval, start a separate vLLM with LoRA, run smoke items 1-5 and 7 with zero, early-random and late-random adapters, then kill it. lab27 then runs without LoRA, so its numbers are untouched. This settles the serving factor (0.6-0.7). lab27 also gives the fair base-E4B reference on the E4B clock.

**Experiment 1, the pilot: about 3-4.3 quota-h, one kernel, a hard 2.4 wall-h deadline.** It answers the dominant unknown, the closed-loop effect size, at the lowest cost that gives any statistical signal.

| Phase | Wall-h |
|---|---|
| Install and preflight (versions, SDPA forward+backward at head_dim 512 and 256, text-only load, dequant check) | 0.25 |
| Render and tokenize (faithfulness pass, then deploy pass for 107 capped trajectories, first segments) | 0.05 |
| Train r16, 3 epochs, DDP (subprocess `torchrun`, which exits before vLLM starts) | 0.4-0.75 |
| vLLM with the trained adapter, smoke items 5-8 | 0.2 |
| Paired eval: 39 held-out A tasks × {s5L, s5L without adapter}, 78 runs, concurrency 12 | 0.6-0.9 |

- Stop launching runs at 2.2 wall-h. If time remains, add a second s5L sample.
- s3 and s4 for the same 39 tasks come from lab27.
- **Metrics** (the gold files come from the `tasks.jsonl` patch field):
  - the submitted diff touches a gold non-test file (file hit);
  - a hunk within 20 lines of a gold hunk;
  - solves;
  - edit_file error rate, malformed-call rate, LABGUARD count, token-time.
- **Continue only if all hold:**
  - file hits for s5L are at least those of the no-adapter arm plus 4/39;
  - s5L solves are at least the no-adapter arm's and at least s3's;
  - edit-error and malformed-call rates are not worse;
  - 0 LABGUARD events;
  - token-time at most 1.25x.

  This screen is lenient on purpose: it is built to stop the program cheaply when there is no signal.

## 4. Stop rules

1. **Canary failures:**
   - "does not support LoRA", a zero-B adapter that differs from base, startup over 15 min, or a warm-up OOM: stop all LoRA work.
   - Layers 24-41 equal base: re-test with layers 0-23 only. If that also shows no effect, stop.
2. **Preflight:** no attention backend runs forward and backward at head_dim 512 at 8k or more within memory, or the faithfulness pass is off by more than ±2 tokens on more than 5% of calls after one fix.
3. **Training:** HF-vs-vLLM teacher-forced mismatch above 0.1 nats per token, or adapter warnings for unsupported modules, after one fix.
4. **Pilot:** any continue criterion in Section 3 is missed. That ends the program. Write it up as a negative result for the paper; do not iterate on rank or alpha. The public record has already explored that space without a win.
5. **B gate:** below s3 + 8/68, or any LABGUARD event: no upload.
6. **Schedule:** the pilot has not run by the 11-14 reset (there is not enough time for training, the B gate, a leaderboard check and a final-pick decision by 12-02), or the team gives the E4B final pick to a non-LoRA bundle.
7. **Quota:** the pilot is not funded at the expense of main-track gates. If lab27 or later work shows that base-E4B fixes (edit_file mechanics, early quitting, the E4B clock) are moving the base rate, that work takes the quota first.

**Files:**
- Pilot split (repo-level hold-out of A): `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/lora/decision/half_split.json`
- Script that builds it: `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/lora/decision/half_split.py`
- Smoke test: `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/lora/serve/e4b_lora_smoke.py`
- Packaging check: `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/lora/serve/offline_pack_check.py`
- Converter: `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/lora/trainingdata/convert.py`
- Queued lab: `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/lab27/lab.py`