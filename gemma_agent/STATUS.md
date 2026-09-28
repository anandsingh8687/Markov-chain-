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
