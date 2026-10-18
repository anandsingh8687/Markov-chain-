I fetched fresh forum data with the cutoff moved to 2026-10-13 (53 topics, 24 of them new) and pulled 33 recent public notebooks. Every recent "jump" I can check turns out to be leaderboard noise: no public recipe has a measured mean above about 10 of 58 tasks (0.17), and that is where v29 already sits. The two levers that are actually allowed (LoRA and the smaller models) both have live problems on the scorer.

Two scoring facts to keep in mind:
- **Score grid.** The public score is solved/58, truncated to two decimals. So 0.15 = 9 tasks, 0.18 = 11, 0.22 = 13, 0.24 = 14, 0.25 = 15, 0.29 = 17, and 0.30 means 18 or more.
- **Leaderboard on 10-18 (3,132 teams).** 2 teams at 0.24, 27 at 0.22, 108 at 0.20, 341 at 0.18. Higher-scoring teams have submitted more often: median 11 submissions at 0.22, 8 at 0.18, 5 at 0.15. That fits "best of many noisy draws".

## 1. Host rules on training data, adapters and the smaller models

**Training data (host answers):**
- **Gemma's own trajectories** are allowed. This was confirmed earlier and is restated in topic 746046.
- **Other open-weight models** are allowed. Elan Markowitz (host), 746046, 10-05: trajectories from a different open model, and public SWE trajectory datasets on Hugging Face, "Both cases are permitted."
- **Claude/GPT (proprietary APIs).** Ashley Oldacre (admin), 742807, 09-29: allowed "as long as you are using those models in accordance with their model license terms" and the output doesn't conflict with the competition's own license rules. In practice this defers to the providers' terms, and the Anthropic and OpenAI terms quoted in 749585 restrict using outputs to build competing models.
  - 749585 (10-15) has no host reply; the only reply is a participant calling it distillation that breaks the providers' terms.
  - 746251 (sending task data to DeepSeek or OpenRouter, rule 2.4(b)) also has no host reply. The latest comment is 10-18.
- **Base weights for training:** use the unquantized variants on the Gemma 4 transformers page (748287, 10-11).

**Adapter limits (harness code plus host):**
- The whole bundle, adapters included, must be at most 3 GiB unpacked (`adk_submission/limits.py:184`).
- vLLM rounds the rank up to one of 1/8/16/32/64/128/256/320/512 (`server.py:59`).
- The host has "seen successful submissions with LoRA adapters up to rank 64", and the scorer sets `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1` (749191, 10-15).
- With that setting the KV cache drops to about 27.7k tokens, against about 45k without it (Nir Aberman, 749191).
- LoRA decoding was measured about 11% slower (749191).
- Michi Yamamoto's rank-16 bundle 57197626 ran past 12 h and got no score. The identical bundle without the adapter (57088086) scored 0.15.
- Adapters are applied correctly; the sample adapter only touches layer 0, which is why it changes almost nothing (749528).

**12B / E4B / E2B:**
- All four variants are allowed, but only one per submission: "Every agent and subagent ... must use the same variant (though they can attach different LoRA adapters)" (748287, 10-11; also 745805). So a small model cannot run alongside the 31B. Scoring conditions are identical for every variant.
- **No 12B submission has been reported scoring.** Four bundles that score on 31B threw "Notebook Threw Exception" when only the model was switched to 12B: 57106464, 57180129 (749259 and 748287), 57188236, and 57178131 (10-18). The host has not answered.
- 12B decodes about 67 tok/s single-stream, against about 35 for the 31B (Jarno Rantala, 748287).

## 2. Time budget

- **Nothing has changed.** Tasks run one after another, the 12 h limit covers everything including vLLM startup, and going over still errors the whole submission.
- Ryan Holbrook, 749597 (10-15): scoring unfinished tasks as 0 "could lead to inconsistent results" between public and private; "I will try to think of other ways." Nothing has been deployed since.
- `get_status` already reports remaining time.
- The harness budget warning counts only tool calls, never time (749198; 750490, 10-18).
- Time is the binding constraint. In Ayush Thakur's sweep on 129 tasks (746250), a 6 / 10 / 15 minute cap solved 37 / 46 / 54. His Kaggle calibration was 900.8 s per million tokens and about 5.5 min per task as the safe cap.

## 3. What teams at 0.22–0.24 disclose

- **Yurnero and Yike Xu (0.24): nothing technical.** Yurnero (748500, 10-12): top-5/10 likely needs "~$1000 or access to a permanent cluster ... We are allowed to tune smaller models now."
- htn (rank 12), 748051: "none of the top submissions have managed to get any improvements through finetuning." In 745274 (rank 12), distilling from DeepSeek gave only +5 tasks locally.
- 750496 (10-18) asks the 0.22–0.24 teams directly; no replies yet.
- **The 0.22 public bundle is luck, measured.** Notebook dariushafshar/gemma-4-lb-58-tasks-bronze-is-a-124-team-tie, section 8 (10-17):
  - The flexonafft V10 files, submitted byte-identical, drew 7 and 9 tasks (0.12, 0.15), against 13 for its author. Mean 9.67.
  - The Budget-Fit files drew 8–11 over 7 draws, mean 10.14.
  - One draw varies by about 1.4–1.8 tasks (SD).
  - Other repeat draws of V10: 0.15 and 0.17 (kozykappa notebook). Another identical bundle drew 0.13 and 0.20 (dmitriigluzdov ideas notebook, updated 10-18).
- Same notebook, single draws by temperature: 0.15 at T 0, 0.18 at T 0.2, 0.12 at T 0.4. That is within the noise.
- 750521 (rank 52, 10-18) also reports different scores from an identical zip at T 0.2.
- **Inference:** v29 (0.18 and 0.15, mean about 10) is statistically the same as every public 0.22 recipe.

## 4. Does multi-attempt or parallel sampling work here?

Nothing shows a gain:
- **ParallelAgent with tools is broken** in ADK 1.36. The host declined to move to ADK v2 (748287; upstream issue adk-python #7324). The only workaround mentioned is tool-free sub-agents. Tool calls run one after another regardless.
- **Two seeds of the 31B agree almost completely.** vanductan ran the official harness on 40 public tasks at 5 min / 40 calls, T 1.0, thinking 4096. I re-tallied the outputs with `(scratchpad)/strat/forum_analysis/models.py`:

| Model | Run 1 | Run 2 | Empty patches |
|---|---|---|---|
| 31B | 12/40 | 11/40 | 9 and 4 |
| 12B | 9/40 | – | 19 |
| E4B | 3/40 | 4/40 | about 4–5 |

  - The 31B's second seed solved nothing the first missed, so even a perfect picker over 2 attempts gives 12 against a mean of 11.5.
  - Pooling all five runs across models reaches 15/40, but one submission can't mix models and has no oracle to pick with.
  - Despite faster decoding, 12B was worse than 31B at the same time cap.
- Our own 2-attempt + picker bundle (v25) scored 0.08.
- 749198 (kimdonggyu): of 65 unsolved tasks, 51 had an edit applied, and 42 of those touched a file the reference patch changes. **Inference:** the bottleneck is a correct edit, not finding the file or getting more samples.

## 5. Newest public recipes (10-13 to 10-18)

| Recipe | What it is | Score |
|---|---|---|
| averywright/gemma-4-caveman-thinking-0-20 | Budget-Fit plus a "think short, like a caveman" block, no "Wait/Actually" | 0.20, one draw |
| flexonafft V10 | About 6 KB prompt | 0.22 for its author; repeats 0.12 / 0.15 / 0.15 / 0.17 |
| honghanhhh "LB 0.24" | Despite the title, its versions scored 0.13, 0.18 and 0.15 | 0.24 not shown |
| lynnsakurai bounded rescue | Budget-Fit variant | 0.18 / 0.15 |
| leoprovorov anytime patch | Single agent | 0.17 |
| dmitriigluzdov 12B swap of V10 | 12B model | unscored |
| LoRA: denpugovkin QLoRA | 31B QLoRA trained on T4 x2 (unsloth base) | 0.03 / 0.05 |
| LoRA: philgear | Ablation study plus QLoRA | at most 0.13 |
| noormamhidayat "distillation" | Claims distillation | claims 0.17 |
| kozykappa, jaelle, rainycloudss, lambdaderta (6 min / 48 calls, T 1.0) | Various | unscored or 0.03 |

No public LoRA, 12B or multi-attempt recipe has scored 0.18 or more.

**Inference:** getting to 0.25–0.30 means a real gain of about 5–7 tasks on the *mean*. No prompt or sampling change has shown that. The only untested paths are (a) a LoRA small enough to keep v29 inside 12 h, given about 11% slower decoding and a smaller KV cache, or (b) the 12B once the scorer serves it, which it doesn't today. Any comparison needs at least 2 draws per config.

Raw data is in `(scratchpad)/strat/forum/`:
- `data/all.txt`, `data/host_all.txt` (all 70 host comments), `data/toprank.txt`, `data/new1.txt`, `data/new2.txt`, `data/recent_other.txt`
- `data/lb/gemma-4-developer-agent-publicleaderboard-2026-10-18T19:26:13.csv`
- `data/kernels.csv`, notebook text in `nbtxt/`, vanductan run outputs in `nbout/`
- scripts in `tools/`