# Final specification: Gemma 4 Developer Agent, 31B main track and E4B (chief architect, 10-29)

## 0. Verdict

**No design beats v33t by a margin we could detect.** The parallel designs add risk and give no measurable gain.

What the data show (split A, 87 tasks, 318 runs):

- **The best-of-k ceiling is low.**
  - pass@1 is 35.5%.
  - A perfect picker at k=2 reaches 41.5%, which is +6.0 points or +5.2 tasks.
  - The only picker that works without hidden tests is "drop empty and timed-out patches". It recovers 49% of that gap (+2.9 points), and only when both branches run at full strength.
- **Most of the score is fixed by the task.**
  - 48 of 87 tasks were never solved in 2-5 runs, 23 were always solved, and only 16 were mixed.
  - About 82% of outcome variance lies between tasks.
- **The spare GPU capacity cannot be turned into solves.**
  - The decode slack is real: aggregate throughput rises from 37 to 57 tok/s at 2 streams.
  - But each stream slows by 1.18-1.30x. With waiting on the slowest branch and blocking tools, a parallel phase costs 1.31x (k=2) to 1.64x (k=4) of one branch.
  - At v33t's time, each branch therefore keeps only 0.65-0.76 of v33t's solves.
  - Best-of-2 breaks even only if each branch keeps 0.86 of a full run with a perfect picker, or 0.93 with a realistic one. The measured value is 0.77-0.85.
- **The designs' own estimates, after the judges' corrections:**

| Design | Expected gain, tasks/87 | Why it shrinks |
|---|---|---|
| A, race of 2 attempts | 0, range about -1.6 to +1.0 | +0.06 to +1.0 at the designed deadline; the k=2 "fastest valid" signal is -0.6 points versus a random valid pick; about 0.5-1 task of tax from the new branch protocol; -0.9 when forced to time parity at the measured 2-stream rate |
| B, fork at the commit point | +0.3 to +0.5 | About 85% of its value is "edit now at budget_warning". v30 already shipped that rule and lab20 showed no change (edits refused at the cap rose from 5 to 8, empties from 10 to 13) |
| C, v37c | +0.3 to +0.5 | It is v35 plus v36 plus levers the 36-agent study already refuted; its retry fires on 2/87 tasks and gains 0.00 |

- **No lab can tell these apart.** The SE of a paired 87-task difference is about 3.3 tasks. A lab can only check that a candidate does no harm and stays within time.
- **Sampling plus selection cannot reach 0.50 on the board.** Even a perfect pass@5 is 50% on our set, about 0.21 on the board.

**Recommendation (low risk):**

1. Build no new 31B architecture.
2. Keep **v33t** as the default upload.
3. Run **lab25 exactly as built** (v33t / v35 / v36 on all 87 split-A tasks). Promote v35 or v36 only through the non-inferiority and time gate in section 4.
4. Run **lab27** (E4B s3 / s4) for the small-model track.
5. Shelve the parallel race. Its hardened specification is kept in Appendix A, with explicit triggers for reopening it.
6. Parallel E4B: no (section 5).

## 1. Chosen architecture

A single LlmAgent in the v33t lineage. The candidates are already built, byte-identical to the lab25a/lab25b kernels, and compile with the official libraries:

| Bundle | Change against v33t | Expected Δ, tasks/87 (estimate) | Board per draw | Time vs v33t | Status |
|---|---|---|---|---|---|
| **v33t** (fallback) | none | 0 | 0.15 (draws 0.17, 0.13; third draw ref 57742428 pending) | 1.00 | uploaded, finishes inside 12 h |
| **v35** | the verbatim issue `{problem_description}` is pinned at the end of the instruction | +0.3 (range -1 to +1.4) | 0.15-0.16 | 1.00-1.01 | lab25 arm |
| **v36** | v35, minus read_file and the 3 graph tools (reads only through capped run_command slices) | 0 (range -1.5 to +1) | 0.15-0.16 | 0.98-1.01 | lab25 arm |

**Why this beats v33t.** It does not beat it by a detectable margin, and no design can. It is still the best option, for three reasons:

- **v35 targets a measured mechanism.**
  - 141 of 155 v33t runs compact, and the ADK summary drops the verbatim issue.
  - Runs whose first compaction came before the first edit solved 11/76; runs that edited first solved 32/53. This comparison is confounded by task difficulty.
  - The ceiling of a perfect fix for this is about +1.4 tasks.
  - Cost: the issue is median 359 characters (about 100 tokens) and at most 6,272 on our set.
- **v36 also removes get_code_subgraph.** That is the only tool with a list argument, which is the main way into the vLLM 0.19.1 parser hang. It also removes 61-67% of tool-output characters, which means fewer compactions.
- **Both are prompt and tool-list changes.** They keep compaction, one stream, and v33t's 28-call / 8-minute bounds, so the time risk is the same as v33t's.

**Why not the parallel shapes** (all estimates, from the inputs):

- **Wait-for-all at k=2:** -0.7 to +2.0 points. Each branch must stop at about 20 calls, but v33t's median last edit is at call 16, and 35% of solves edit after call 20.
- **k=3 or k=4:** worse.
- **Fork after localization:** fixers share the lead's diagnosis, and wrong patches are "sealed".
- **Race of 2 (the best parallel shape):** its gain at time parity depends on the disputed per-stream rate.
  - It needs at least 31.5 tok/s per stream at 2 running; measured is 28.6-29.6.
  - A valid evaluation needs a concurrency-1, real-clock lab: about 8.4 wall-h, or about 17 quota-h, per arm.

## 2. Bundle files (exact)

The files are on disk. Copy them from disk and check sha256; the text below is the same content.

- v33t: `/home/user/Markov-chain-/gemma_agent/bundle_v33t`
- v35: `/home/user/Markov-chain-/gemma_agent/bundle_v35`
- v36: `/home/user/Markov-chain-/gemma_agent/bundle_v36`

These are byte-identical to the `BUNDLES` dicts in `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/lab25a/lab.py` and `.../lab25b/lab.py` (checked 10-29).

sha256:
```
a243797d5a2a6f1b876199a586bb6b5b3158915c697595a5933659b707789907  eval_config.yaml        (v33t = v35 = v36)
630056889710d27dbf17c8fde62e033b7329616b7db435987cb4607b66a7c3f6  configs/sampling.yaml   (v33t = v35 = v36)
66ee50a4cb71c2893adc7731e68668a1b458a018a5f02cb95d76f4ba7f794fc3  bundle_v33t/agent.yaml
f39d03c7c02ca1376c3fc80f442489c1823a514343b9d2e99c9ca17485225f4e  bundle_v33t/prompts/system.md
a0a2a096d3e8a4f063f22ee6d06b0b726170fcbae9f6a771588a40447fc270ee  bundle_v35/agent.yaml
a008b38c35b2d01bd0dea2c795a88b2e17d0faeec08a53b382a991081dcbc782  bundle_v35/prompts/system.md
2b25b57fc23921443ad9e51ef90699c7b962bee886f6f92dbc654e2beec8345f  bundle_v36/agent.yaml
59624d71e814be039961765a5f7eebd4310176c7ab6eb238e62c61ae64c3fac5  bundle_v36/prompts/system.md
```

There are no sub-agent YAMLs and no skills.

### eval_config.yaml (all three)
```yaml
# Native tools, thinking on (0.2.12 enforces the budget). The call cap keeps the
# 8-minute cap inside the 12-hour run; timeout_seconds also bounds the grader's pytest.
evaluation:
  timeout_seconds: 240
  max_tool_calls: 28
  max_time_minutes: 8
  max_turns: 80
```

### configs/sampling.yaml (all three)
```yaml
temperature: 1.0
top_p: 0.95
top_k: 64
max_output_tokens: 8192
thinking_config:
  thinking_budget: 4096
  include_thoughts: true
```

### bundle_v35/agent.yaml
```yaml
name: fixer
model: gemma-4-31b-it-qat-w4a16-ct
description: v33t plus the issue text kept verbatim in the instruction, so history compaction cannot drop it.
instruction: !include prompts/system.md
tools:
  - run_command
  - read_file
  - edit_file
  - write_file
  - get_status
  - submit_patch
  - search_similar_code
  - get_code_neighbors
  - get_code_subgraph
generate_content_config: !include configs/sampling.yaml
```

### bundle_v35/prompts/system.md
```
You are fixing one issue in the Python repository at /workspace. A grader applies your git diff to a clean copy and runs hidden tests. Only the diff counts: an empty diff fails, and a correct diff passes even if you never ran a test. Limits: 28 tool calls and 8 minutes. When a limit is reached, the files on disk are graded as they stand.

1. Read the issue. Note every exact name, parameter, exception type, message and return value it states, and use them character for character. If no message is given, build it from the issue's own words in the format of nearby messages.

2. Find the code. Search with git grep -n for the most specific identifiers or messages from the issue, limited to the package directory shown in the layout, and always pipe the search into head -30. Empty output simply means no match; try one different string, never the same search twice. Read code with run_command, cat -n on the file piped into sed -n with a line range of at most 80 lines, because command output is cut at 5000 characters without notice. Read the whole suspect function before deciding. Do not call search_similar_code, get_code_neighbors or get_code_subgraph.

3. If the issue describes a bug but shows no error output, write one reproducer in a single run_command: cat into /tmp/r.py with a quoted heredoc, the closing EOF alone on its line, then timeout 30 python3 /tmp/r.py on the next line. Use the public API with a few inputs, each wrapped in try and except, printing repr of the result or the exception. write_file cannot write outside /workspace, so scratch files go through run_command. If the reproducer cannot run for setup reasons, drop it. Spend at most two calls on it before the first edit.

4. Edit early. As soon as you can name the line to change, the next call is the edit, and by call 12 a source file must be changed; if you are unsure, edit the best candidate. Make the smallest change that fixes the cause, in the direction the issue asks. After the first edit, rerun the reproducer; if its output is now right, make no further edits. A change to comments or docstrings alone never fixes an issue.

5. Edit with edit_file. old_string is two or three code lines that occur once in the file, copied without the cat -n line numbers and never from a docstring. Write line breaks as real line breaks, never as backslash-n, and never put a backslash before a quote. If the new code itself needs a backslash, or edit_file reports a missing parameter, do not resend it: in one run_command run python3 with a quoted heredoc script that reads the file, asserts the old text occurs once, replaces it using raw strings, writes the file, then runs python3 -m py_compile on it.

6. Check once: run timeout 60 python3 -m pytest on the test file for the module with -q, piped into tail -15, at most twice in total. A test that expects the old behaviour the issue changes will fail; keep your fix. A failure whose traceback does not pass through code you changed existed before; ignore it. Any other new failure means your edit broke something: narrow that edit.

7. Run git status --short and git diff, delete stray files you created in /workspace, call submit_patch and stop with a one-line summary.

Rules: never create, edit or delete test files. Do not install packages. Never repeat a search or a failed call unchanged; rerunning the reproducer or the test after an edit is expected. Every issue needs a source change. If get_status shows under 90 seconds left, call submit_patch.

The issue, verbatim. Older messages are summarized when the context grows, but this copy always stays here: before every edit, check names, messages and behaviour against it.

{problem_description}
```

### bundle_v36/agent.yaml
```yaml
name: fixer
model: gemma-4-31b-it-qat-w4a16-ct
description: v35 without read_file and graph tools, so every read is a bounded run_command slice and history compacts less often.
instruction: !include prompts/system.md
tools:
  - run_command
  - edit_file
  - write_file
  - get_status
  - submit_patch
generate_content_config: !include configs/sampling.yaml
```

### bundle_v36/prompts/system.md
This file is identical to v35's prompt except for the last sentence of step 2, which reads:
```
... Read the whole suspect function before deciding, one slice of at most 80 lines per call.
```
It replaces `... Read the whole suspect function before deciding. Do not call search_similar_code, get_code_neighbors or get_code_subgraph.` (`diff` confirms this is the only differing line).

### Fallback (v33t)
v33t is v35 with the `description` line `Single fixer on native tools; edits early, checks once, submits.` and without the final paragraph and the `{problem_description}` line.

### Time contingency (do not apply unless a gate says so)
If a passing arm's predicted time is above 1.02x v33t, set `configs/sampling.yaml` `thinking_budget: 4096` to `2048`. That saves about 6-8% of tokens, with solves unchanged within noise (lab18, v30). Then gate again on time only.

## 3. Offline test plan (CPU, before any GPU)

### Already run on 10-29, all pass

1. **Official compile** of v33t, v35 and v36:
   `.../scratchpad/wh31/venv/bin/python -I /home/user/Markov-chain-/gemma_agent/official_check.py <bundle>`
   - Result: OK for all three.
   - Request extras: `enable_thinking: True`, `thinking_token_budget: 4096`, T 1.0, top_k 64, max_output 8192.
2. **Real-harness fake-LLM suite.** It uses the real compile_submission and run_agent_sandbox, the subprocess sandbox, the toy flat and src layouts, and the run_official helpers through `impl/partest/drive.py`.
   - Fake: `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/bic/chief/fake_v35.py`, a copy of designC's fake_c.py with two added scenarios.
   - Runner: `.../bic/chief/run_v35.sh <bundle_dir> <scenario> <task> <port>`
   - Summary: `/usr/bin/python3 -I .../bic/chief/summarize.py`
   - 15 of 15 runs behaved as specified:

| Scenario | Bundles × layouts | Result |
|---|---|---|
| solo_pass | 3 bundles × flat/src | resolved, 7 counted calls, only the one source file in the patch, 0 gitlinks |
| solo_compact (every step reports 15k prompt tokens) | 3 × 2 | 5 summarizer calls, no crash, resolved; the pinned issue is in the system prompt of every fixer request for v35/v36 (false for v33t, as expected); no template placeholders left over; 9 tools offered (v35) / 5 (v36) |
| cap_empty | 3 × flat | 28 calls, the 29th call (an edit) refused, empty patch, no crash; this documents the cap path |

3. **Lab kernel identity.** The lab25a, lab25b and lab26 `BUNDLES` match the bundle directories on disk byte for byte. lab25a/b task ids are 43+44 = all 87 split-A eval tasks (0 from split B). lab26 uses 68 split-B tasks.

### Re-run immediately before launch (gate to press "run")

- Repeat items 1-3. All must pass unchanged.
  - Any sha256 mismatch between a lab kernel and the disk bundle blocks the launch.
  - Any `templ_left` other than `[]` blocks the launch.
- `lab/selftest.py --skip-e2e` with the wheelhouse venv (unit checks plus kernel parse).
- **Templating spot check.** Use an issue string that contains `{x}`, `${HOME}`, `{a.b}` and a literal `{problem_description}`. It must be inserted verbatim without a KeyError. This was verified before (STATUS 10-26); repeat it after any adk_submission or wheel change.
- **Do not edit any prompt** for these arms; edits would invalidate lab25.
  - Process rule: no prompt text may quote split-A issue text or hidden-test forms.

## 4. GPU lab plan for the 10-31 quota reset (30 quota-h)

Measured rates:

- 31B at concurrency 6 on the virtual clock: 1.82-2.0 wall-min per arm-run (lab22a 86 runs in 2.87 h, lab24 136 runs in 4.13 h after vLLM start).
- vLLM start: 5-7 min.
- Billing: about 2.0 quota-h per wall-h (the 10-24 week used about 14.6 wall-h for 28.6 quota-h).
- At most 2 GPU sessions run at once.

| Priority | Kernel (prepared in the scratchpad) | Arms | Tasks | Runs | Wall-h | Quota-h | Launch |
|---|---|---|---|---|---|---|---|
| P1 | lab25a | v33t, v35, v36 | 43 split A | 129 | about 4.0 | about 8.1 | 10-31 00:15 UTC |
| P1 | lab25b | v33t, v35, v36 | 44 split A | 132 | about 4.1 | about 8.3 | at the same time as lab25a |
| P2 | lab27 (E4B, LABGUARD on, E4B clock preset) | s3, s4 | 87 split A | 174 | about 2.5-3.5 | about 5-7 | when the first lab25 kernel finishes |
| P3, conditional | lab26, **regenerated** as ONE arm: the lab25 winner if it is not v33t, paired with lab24's v33t split-B arm (it replaces v29 vs v35) | 1 | 68 split B | 68 | about 2.2 | about 4.5 | only if a candidate passes the gate on split A |
| Reserve | rerun of a failed or hung kernel | | | | | about 3-5 | |

The total is about 21.5-24 quota-h, or about 26-28.5 with P3.

**Parallel race:** no 31B arm this week (see Appendix A for what a valid test would cost). CPU-only hardening work on it is optional and blocks nothing.

**Analysis rules (pre-registered):**

- Primary set: the 76 scoreable tasks. Exclude 11:
  - package or environment broken: PyBaMM-5061, pyqasm-155, pyqasm-168, pyvrp-803, pynwb-2052, pynwb-2060, cryptography-12673, pyinfra-1665, earthkit-data-671;
  - network-dependent tests: pdm-3759, mempalace-1004.
  - Report the 87-task numbers alongside.
- Baseline: pooled v33t, the mean of lab22's v33t and lab25's v33t arm. The pair also gives a measured A/A discordance.
- Use `stats.py` (McNemar, paired bootstrap).

**Upload gate.** v35 or v36 replaces v33t as the upload candidate only if ALL of the following hold:

1. solves on the 76 tasks ≥ pooled v33t − 1;
2. predicted scorer time ≤ 1.02x the lab25 v33t arm. In absolute terms: 120 × (mean agent s + 10) + 500 ≤ 40,700 s. v33t projects to about 39,900 s, or 11.09 h;
3. empties plus 8-minute timeouts ≤ the v33t arm + 3;
4. no new failure class: 0 harness errors other than the session timeout, at most 1 turn-limit loop, 0 LABGUARD events;
5. v36 only: read calls per run ≤ 1.2x v33t's, and 28-call cap hits ≤ v33t + 3. Otherwise drop v36 in favour of v35.

If both v35 and v36 pass:

- take the one with more solves on the 87 tasks;
- within 2 tasks, take v36 if its time ≤ v35's (fewer ways into a parser hang, fewer compactions), else v35.

Any lab difference under about 6 tasks is noise. Passing the gate means "no harm", not "better". The candidate must then **complete at least one board draw within 12 h** before it can be a final pick. The board is the only real test of the 12-h limit. If any condition fails, v33t stays.

**Leaderboard slots and final picks (deadline 12-02):**

- Until lab25 reports, the slots stay on v33t draws.
- After the gate, use the slots for draws of the passing candidate.
- Final pick 1: the gate winner with at least 1 completed draw, else v33t.
- Final pick 2: the E4B bundle only if the user's E4B gate passes (≥ 2/12 on the smoke set AND ≥ 10/87 on split A AND 0 LABGUARD events); otherwise a second main-family bundle.

### 4.1 Addendum, 10-31 09:40 UTC, written before any lab 26 data exist

The lab 25 gate failed both candidates, so P3 as written above does not run. With about 19 quota-h left
this week (lab25a 4.24 h, lab25b 4.45 h, lab27 2.42 h), lab 26 is regenerated for two questions. This
is a follow-up chosen after seeing split A, so it is declared here before split B is run.

**Kernels.** lab26a / lab26b: arms v29, v33t, v36 on the 68 scoreable split-B tasks
(`evalset/v1/evB_nointerface.txt`, shuffled with seed 26 into `ev26a.txt` / `ev26b.txt`, 34 each),
same harness as lab 25 (docker-like sandbox, concurrency 6, 31B clock preset, parser guard on, seed 26).
204 runs, about 6.5 quota-h.

**Q1, sampling (paper §4.1, no decision attached).** v29 -> v33t pooled over lab 22 (split A, 87 tasks,
same kernel) and lab 26 (split B, 68 tasks, same kernel): 155 paired tasks; report solves, discordant
counts, exact McNemar p and the paired bootstrap interval, whatever the result. v33t lab 24 vs lab 26 on
split B gives a second A/A measurement.

**Q2, v36 replication (upload gate).** On split A, v36 solved 34 against v33t's 29 in the same kernel
(+5, inside the A/A swing) and failed only criterion 5 (28-call cap hits 42 vs 32). v36 becomes an
upload candidate only if ALL hold:

1. pooled same-kernel pairs, lab 25 (87) + lab 26 (68): v36 solves >= v33t solves + 6 (that is, split B
   must not lose any of split A's +5);
2. predicted scorer time (timepred, 31B constants) <= 1.02x the lab 26 v33t arm;
3. on split B, empties plus 8-minute timeouts <= the v33t arm + 3;
4. 0 LABGUARD events, 0 harness errors other than the session timeout, at most 1 turn-limit loop per arm.

Cap hits and read calls are reported, not gated: on split A the extra cap hits did not cost solves and
time was equal, so criterion 5 is replaced by the direct time criterion (2). This change is made now,
before split B is seen.

If Q2 passes: v36 gets one leaderboard draw (a new bundle, so no identical re-upload); final pick 2 = v36
if that draw finishes inside 12 h, else v29. If Q2 fails: final picks v33t and v29.

## 5. E4B variant: not supported (why not)

Parallel E4B (k=4-6 with an agreement vote) does not plausibly reach the small-model leader's level.

- **Base rate is tiny.** Our E4B bundles solved 1 of 57 split-A runs. Good bundles run at about 0.34x 31B's rate, about 10/87 (90% CI 4.6-17).
- **Even the k=6 vote is short of the leader.** The estimate is 14-17.5/87 before hang losses. The leader-equivalent is about 20/87, which needs E4B at 0.40x of 31B or better (P about 0.30).
- **Hang exposure grows with k.** vLLM 0.19.1's parser hangs at about 1 per 1,700 E4B calls. At that rate a k=6 design keeps about 0.19 of its score, against 0.67 for a single agent.
- **Worktrees would need shell edits.** Isolating k-1 workers means editing through shell commands, and E4B made 0 such edits in 137 runs.
- **Selection has nothing to work with.** Among 57 split-A E4B runs, 46 are wrong non-empty patches.
- **Spend the quota on lab27 instead** (s3/s4, LABGUARD, all 87 tasks) to get a split-A base rate and hang count.
  - The only multi-attempt E4B worth a later build is k=3 *sequential* fresh attempts (AgentTool per attempt, exact-hash majority, max_time_minutes 5.5). It is estimated at +2-2.5/87, and only if s3 reaches ≥ 10/87 with 0 LABGUARD events over 3,000 or more calls.
  - Even then, it does not reach the leader.

## 6. Main risks and fallback

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Gate noise.** With SE 3.3, a non-inferiority gate passes a truly −2 candidate about 50% of the time and a −3 candidate about 38%. | Candidates differ from v33t by one paragraph or by the tool list. Gate on time and failure classes as well as solves. Require a completed board draw before a final pick. |
| 2 | **12-h limit.** v33t projects to 11.09 h. v32 finished at about 1.02x v29; v28 failed at 1.075x. | Time cap of ≤ 1.02x in the gate; thinking-2048 contingency. |
| 3 | **Long hidden issues (v35/v36).** The pinned issue appears twice before the first compaction and raises the token floor after it. Our sets top out at 6.3k chars; competition-format sets at 10.7k chars (about 3k tokens), with 1 task over 8k chars in each of the 165/221/51-task sets. | Below the 14,336 threshold even at the maximum; watch compactions per run in lab25. |
| 4 | **v36 habit change.** read_file was the model's main reader. | Read-cost guard (gate condition 5). |
| 5 | **Scorer-fatal parser hang.** 31B: 0 hangs in about 10k calls. | v36 removes the only list-argument tool. Any hang on the scorer makes v36 the default. |
| 6 | **Lab kernel hang or quota overrun.** lab20b ran on after the quota was spent, and the CLI cannot cancel a kernel. | KILL_AFTER in the kernel; the user stops it in the Kaggle UI; 3-5 quota-h reserve. |

**Fallback:** v33t, unchanged. It is already uploaded, has finished inside 12 h on the scorer (draws 0.17 and 0.13, a third pending), and is the solve leader on split A (34/87).

## Appendix A: race2h, the parallel spec of record (shelved)

**Canonical files:** `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/bic/designA/final/bundle_race2/`
- Shape: lead → AgentTool → ParallelAgent of a1/a2 in git worktrees; skill `race` (setup.py / final.py); counted command prefix `. /tmp/race/aN && `; atomic mkdir claim; deadline watchdog.
- Status: compiled, 18/18 fake runs pass. Suite: `.../designA/final/test/run.sh`.

**Required hardening before it can go anywhere near a GPU:**

1. **Hide /workspace without deleting it.** Mark every tracked file skip-worktree (`git ls-files -z | xargs -0 git update-index --skip-worktree`) before removing it, and undo that (`--no-skip-worktree`) before every `git reset --hard`. A premature submit or a timeout then grades an empty diff instead of one that deletes the repository.
2. **Claim without SIGTERM.** final.py does `mkdir R/won` first. If `won` exists without `won/done`, it polls for up to 30 s. handin and the watchdog write `won/done` after applying. final.py skips the reset and apply when the /workspace diff already equals `R/<winner>.diff`, and never resets with less than 30 s of agent time left (setup writes `R/t0`).
3. **In-band deadline.** The lib claims synchronously once `now − t0 ≥ DEADLINE`, then prints STOPPED. The detached watchdog stays as a backup, plus an unconditional restore at about 440 s of agent time.
4. **DEADLINE from the measured rate.** Set it from the per-stream rate measured at 2 running: 300 s below 30 tok/s, 330 s only at ≥ 31.5 tok/s.
5. **Lower LIMIT to 24.** edit_file is not counted by the lib.
6. **eval_config:** `max_tool_calls: 100`, `max_turns: 300`. Keep max_time_minutes 8 and timeout_seconds 240.
7. **Lead rule** in lead.md: "never call submit_patch before final.py printed `winner:`; after any nudge, run final.py first".
8. **Plan-B watchdog** gets the non-test filter.
9. **index.lock:** every git command in pick() retries 3 times, 1 s apart.

**Tests to add before any GPU run:**

- Run the suite in docker mode with an editable install and with a meson/scikit-build package.
- New fake cases:
  - the lead submits before final.py;
  - final.py at 470 s;
  - watchdog and final.py overlap;
  - both branches hand in in the same tick;
  - a new file created in a copy;
  - an ignored `_version.py` imported at runtime;
  - hints filled;
  - both branches end empty.
- Pass condition: every case resolves or ends empty, never with a diff that deletes the repository.

**Reopen only if** (a) the 2-stream per-sequence decode is measured at ≥ 31.5 tok/s on the scorer stack, or (b) a new base has a split-A oracle gap pass@2 − pass@1 of 10 points or more (currently 6.0).

**If reopened, the evaluation order is:**

1. 12-task real-clock smoke at concurrency 1 for "race1", the same branch stack with k=1 (about 2.6 quota-h). Abandon the design if its protocol tax exceeds 1 task/87 or 3% of time.
2. race2h, real clock, 87 tasks, concurrency 1 (about 8.4 wall-h, about 17 quota-h).
3. Ship gate: ≤ 1.00x v33t time and solves ≥ v33t − 2. This is non-inferiority only.

## Appendix B: evidence behind dropping B and C

**Forced commit at the warning, on v33t's 87 runs** (computed today from designC/ev.jsonl):

| Trigger, no source edit by call | Runs with no edit | Late solves exposed | Runs that never edited | Fresh-run rescue mass of those |
|---|---|---|---|---|
| 18 | 43 | 11 | 19 | 1.58 tasks |
| 22 | 29 | 4 | 19 (13 hit the 28-call cap, 6 hit the session timeout) | 1.58 tasks |

- Late-edited wrong runs at call 18 or later have rescue mass 0.00.
- Realistic capture is 20-40% of the rescue mass, about +0.3-0.6. The rule already shipped in v30 and v32 without changing behaviour.

**C's parts:**
- The pinned issue is v35 and the bounded reads are v36.
- The single-file pytest rule is refuted lever #8.
- The retry fires on 2/87 tasks, gains 0.00, and costs +2.7-4.8 s per task.

**Files written today:**
- `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/bic/chief/fake_v35.py`
- `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/bic/chief/run_v35.sh`
- `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/bic/chief/summarize.py`
- run outputs in `/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/bic/chief/out/`