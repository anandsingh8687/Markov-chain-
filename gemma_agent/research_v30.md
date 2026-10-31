# v30 design: 28 to 32 tool calls, thinking budget 2048, max_turns 50, revised 4.2 KB prompt

Nothing was run in the lab and nothing was submitted; all numbers below are projections. The new files are in the scratchpad. The rest of the bundle (`agent.yaml`, tool list, temperature, timeouts) is the same as v29.

- **Prompt:** `(scratchpad)/oct15/v30_system.md`. It is 4,199 bytes (v29 is 3,495), plain prose, with no braces or backticks.
- **Eval config:** `(scratchpad)/oct15/v30_eval_config.yaml`. `max_tool_calls` goes from 28 to 32 and `max_turns` from 80 to 50.
- **Sampling config:** `(scratchpad)/oct15/v30_sampling.yaml`. `thinking_budget` goes from 4096 to 2048. This is the extra call cost that the 32-call cap depends on.

## Config changes
| Change | Evidence | Effect |
|---|---|---|
| `thinking_budget` 2048 | Only 7 of 40 solved v29 tasks have a call over 2,048 thought tokens, against 26 of 56 unsolved. A public test scored 50 vs 48 of 129 (2048 vs 4096). | About −6.5% completion tokens. This saving does not depend on the model following the prompt. |
| `max_turns` 50 | In 144 runs, no first submit and no successful edit came after LLM call 45. The submit loops are 10% of LLM calls and 14.8% of prompt tokens. | About −5% LLM calls and −3.5% prompt tokens. It cuts the long tail in wall time on the scorer. |
| `max_tool_calls` 32 | v29c36 (36 calls) solved about +3 of 73 lab tasks. rich_4079 and fastapi_14873 only flip when there are calls after call 28. The budget_warning rule below needs calls left after the forced edit to revise it. | About +1 to +1.5 lab tasks. On its own it adds about +0.6k tokens per task (8.0k to about 8.6k). |

## Prompt changes
1. **Limits sentence names budget_warning, and step 4 makes the next call an edit when the warning appears with no edit made.** This replaces the hard "by call 12" rule with "aim for call 12".
   - Evidence (14873, 4079): in 19 of 22 v29 empty-patch runs, no edit was on disk before the cap, and 13 first tried to edit at call 29 or 30.
   - The model ignores call counts it has to track, but it does see the warning string.
2. **Submit once, then reply with one line of plain text. This also applies after any BudgetExceeded.**
   - Evidence (11194, 14873): 6 tasks made 307 repeat submits.
   - I did not use the token analysis's wording "it works even after the limit". STATUS records those post-budget submits as refused.
3. **Keep thoughts short: no code copied into thoughts, cite lines, run code instead of tracing it.**
   - Evidence: code copied from earlier tool output is 13% of completion tokens (95 of 96 tasks), and hand tracing is 2.1%.
   - Expected saving is about −6.5% at 50% compliance.
4. **Rewrite the reproducer at most once, then only rerun it.** This replaces "at most two calls".
   - Evidence: third or later reproducer writes are 9% of completion tokens.
5. **New reproducer content:**
   - Call the public API and judge output only by what the issue, a docstring or a test promises (14419, 3521).
   - When the issue gives no failing input, loop over long mixed inputs and every index (3506, 3521).
   - If nothing fails, the inputs missed the case: skip version checks and read the function that converts or validates each value at run time, not setup or schema code (11194).
   - This changes what is in the reproducer, not how many calls it takes.
6. **Step 2: grep the variable or attribute name, not only the class, and read the lines that assign, extend or pass it on. Fix there, not with a second path** (5624, 14419). Expected cost is about one grep, which replaces wasted class-name greps.
7. **Step 2: put several strings in one `-F` search.** Only 2 of 758 v29 searches used more than one string. Even if it saves no calls, it costs nothing.
8. **Step 2: for a feature, copy the closest sibling and its registration (imports, `__all__`, tables).** The reason is private repos: the model cannot know their local conventions. It costs 0 to 1 call.
9. **Step 6: find the test file with `git ls-files` and grep first, and never run the whole suite.**
   - Evidence: 24% of v29 runs ran pytest on a path that does not exist.
10. **Step 7: one extra `git grep -F` for the original line you replaced, run in the same call as the final status and diff. If a copied twin method has it, make the same change there and nothing else.**
    - Evidence: rich_3480.
    - It costs no extra call and about 40 to 80 tokens. It keeps v29's protection against over-editing.
11. **Mechanics:**
    - After a cut-off or failed call, continue from what is already above and never re-read (14873; 61% of re-reads come after compaction).
    - On "not found", re-read the lines and use a shorter anchor.
    - All other v29 mechanics are kept: the 80-line and 5000-character read limit, `| head -30`, the quoted heredoc to `/tmp/r.py`, no backslash-n, and the switch to a python heredoc on the first missing-parameter error.

## Expected effect
- **Tokens per task:**
  - At 32 calls the base is about 8.6k. The thinking budget alone brings that to about 8.0k.
  - If the prompt rules are followed (thought rule at 50% about −6.5%, reproducer cap about −4.9%, submit rule about −2.8%, new rules about +0.3k), projected mean is about 7.0k to 7.6k.
  - **Worst case**, with the prompt rules not followed at all: about 8.0k to 8.2k. That slightly breaks the constraint for a 32-call bundle.
- **Time:** about 185 to 200 s per task in the lab, against v29's 198 s, which completed on the scorer.
- **Solves:** about +2 to +3 tasks over the 73 lab tasks: about +1 to +1.5 from the extra calls and about +0.5 each from the warning, trace, sweep and twin rules. On the public set that is about +1 to +3 tasks, so 0.20 to 0.22. **Reaching 0.25 (15 of 58, +4 over v29) is unlikely from this alone.**
- **Lab gate before submitting:** run v29 against v30 paired on the 48, plus the 25 holdout. Accept only if:
  - mean completion tokens are at most 8.0k (including about 800 per compaction);
  - mean time is at most 198 s per task;
  - solves are at least v29's minus 1.
- **Fallback if tokens come in over 8.0k:** set `max_tool_calls` back to 28 and change "32" in the prompt's first paragraph to "28". The other changes stay.

## Rejected
- **`max_tool_calls` 36:** 9.2k tokens per task, even with the savings about 8.5k or more including compaction summaries. That is too risky after v28's no-score.
- **`include_thoughts: false`:** v28t used more completion tokens than v28.
- **Run a snippet once instead of keeping a reproducer file:** in the lab, runs with a reproducer resolved 48% vs 21%. I kept the cap only.
- **No new searching after call 20:** 6 of 51 v29 solves needed late searching, and the model did not follow this rule in v28.
- **Reading up to 3 regions per command:** that goes over the silent 5000-character cut.
- **Verification settings from the 0.22 prompt:**
  - pytest -x: hides regressions behind a stale-test failure.
  - timeout 150: is 31% of the task budget.
  - fixing from the traceback: made v28 revert a correct fix on 3043.
- **Checking patch_size and resubmitting:** no v29 zero-size submit happened with calls left.
- **"Read one caller or test" as a rule:** 46% vs 51% resolved, with the first edit 3.8 calls later.
- **Fastapi `docs_src` rule:** specific to one public repo.
- **Full edge-case rule:** over-editing broke 3180 and 3470.
- **Debug-print removal, opening issue-named paths directly, and v29's "Every issue needs a source change" and "rerunning is expected" sentences:** dropped for size, as low-value items.
- **Optional extras from the near-miss pairs:** sibling-plus-nested reproducer inputs, and skipping the reproducer when the issue names the cause. Single-task evidence only.
- **Removing the graph tools from `agent.yaml`:** untested, so the prompt still tells the model not to call them.
- **Making a post-budget submit end the run in the harness:** that needs a harness change. The prompt rule plus `max_turns` 50 covers it.
# Reviews
**Verdict: ship with edits.** Don't submit on these projections; submit only after the tightened paired lab gate below. Time is the lens here. The config changes save time by themselves. The risk is in the prompt.

**What the traces show** (121 v29 runs, 73 v29c36, 48 v28; virtual clock = 0.164 s per LLM call + 0.0221 s per completion token + tool seconds)

- **v29, completed on the scorer:** 8.0k completion tokens per task, 29.7 LLM calls, 190 s pooled (draws 185, 185, 198).
- **v28, over 12 h:** 9.8k tokens, 233 s. The overrun came from longer thoughts per call (358 tokens per call vs 268), not from more calls (27.4 vs 29.8). Structured, judgment-heavy prompt text is what made v28 slow, and v30 adds some of that kind of text.
- **Config alone, measured on the same v29c36 traces:**
  - 28 → 32 calls: 8,540 → 8,984 tokens (+5.2%), 204 → 214 s.
  - Thinking budget 2048: −721 tokens (−8.0%).
  - max_turns 50: only −31 tokens and −1.4 LLM calls, about 1 s per task. The design's "cuts the long tail" is overstated, but the setting is harmless.
  - Net: v30's config is about 0.964 × v29, roughly 7.7k tokens and 183 s.
- **That leaves a buffer of only about 290 tokens per task over v29**, about one exploration call (301 tokens per call). There is no measured margin above v29: the limit sits somewhere between 198 s (passed) and 233 s (failed). With 120 tasks, a single draw also varies by about ±5% (1 sd).
- **Thinking-cap side effects:**
  - The cap cuts 2.4× more steps than the 4096 cap (93 vs 38). Most cut steps come right before a reproducer write (25) or an edit (20).
  - Twice the model kept reasoning in visible text up to max_output after its thinking was cut off (v28 rich_3521, v29c36 rich_3180: 4,094 visible tokens each). With a 2048 cap that text can reach 6,144 tokens. Worst case is about +150 tokens per task.
- **Prompt size and prefill are not a material risk.** The prompt adds 196 tokens per call, all prefix-cached. Peak prompt stays flat (14.8k vs 14.7k) because compaction holds it.
- **Compaction summaries are not counted by the virtual clock.** Compactions go from 1.04 to 1.12 per task, about +65 hidden tokens.
- **Prompt additions, estimated +0.4k to +1.2k tokens per task:**
  - The git ls-files step adds a call in about 68% of runs (82 of 121 run pytest): about +140.
  - Variable/attribute grep and read: +80 to +160.
  - Reproducer loops: +150 to +300, plus tool seconds.
  - Twin check: +50 to +100.
  - **Biggest risk:** softening "by call 12 must" to "aim for call 12". In v29, runs with the first edit at or before call 12 averaged 6.3k tokens, against 11.4k for calls 13 to 18. If the first edit moves 1 to 2 calls later, that costs +300 to +660. Every bundle that has scored (v27, v28, v29, the 0.22 bundle) kept a hard call-12 rule.
- **Savings depend on the model following the prompt:**
  - Stopping after BudgetExceeded is worth up to about 0.6k per task. The post-cap tail is 1,218 tokens per capped run, and 55% of runs hit the cap.
  - The reproducer cap will probably be ignored: v29 already broke "at most two calls" in 49 of 121 runs (3 or more writes).
- **Outside evidence:** a public Budget-Fit-style config with 32 calls, 8 min and thinking 4096 ran past 12 h (forum topic 748168).
- **Realistic range for v30:** about 7.0k to 9.3k tokens. The upper end lands in the zone between v29 and v28.

**Required edits (old → new)**

E1, step 4:
"Once you can name the line to change, edit it; aim for call 12."
→ "Once you can name the line to change, edit it. By call 12 a source file must be changed; if unsure, edit the best candidate."

E2, step 2:
"Use git grep -n -F with several strings in one call (-e 'A' -e 'B'), limited to the package directory, piped into head -30."
→ "Use git grep -n -F with several strings in one call (-e 'A' -e 'B'), limited to the package directory, piped into head -30; in the same run_command also run git ls-files piped into grep for the module name and test, piped into head -5, to learn the test file path."

E3, step 6:
"Check: find the test file with git ls-files piped into grep, then run timeout 60 python3 -m pytest on it -q, piped into tail -15, at most twice; never the whole suite."
→ "Check: run timeout 60 python3 -m pytest -q on a test file path shown by git ls-files, piped into tail -15, at most twice; never the whole suite or an unseen path."

E4, step 2:
"Trace a wrong value to where it is made: grep the variable or attribute name that holds it, not only the class, and read the lines that assign, extend or pass it on; fix there, not with a second path."
→ "Trace a wrong value to where it is made: put the variable or attribute name that holds it in the same grep as the class, and read the lines that assign, extend or pass it on; fix there, not with a second path."

E5, step 3:
"With no failing input given, loop over many inputs, including long ones mixing the kinds the code treats differently, and every index, printing only the first failure."
→ "With no failing input given, loop over a few dozen inputs, including long ones mixing the kinds the code treats differently, and every index, printing only the first failure; keep the script under 30 lines."

E6, step 3:
"If nothing fails, your inputs missed the case; the bug exists, so skip version checks and read the function that converts or validates each value at run time (not setup or schema code)."
→ "If nothing fails, your inputs missed the case; the bug exists, so skip version checks, read once the function that converts or validates each value at run time (not setup or schema code), and edit it."

E7, step 7. The grep output is uncapped and a common line can return up to 5,000 characters right at peak context:
"In one run_command run git status --short, git diff and git grep -n -F on the original line you replaced; if a copied twin (sibling method, sync or async) has it, make the same change there and nothing else."
→ "In one run_command run git status --short, git diff, and git grep -n -F on the original line you replaced, limited to the package directory and piped into head -10; if a copied twin (sibling method, sync or async) has it, make the same change there with one edit_file and nothing else, then submit."

E8, Rules. The current sentence contradicts step 5's "On not found, re-read the lines":
"After a cut-off or failed call, continue from what is above; never re-read what you have."
→ "After a cut-off or failed call, continue from what is above; re-read only the exact lines a failed edit needs."

**Lab gate (replaces the design's gate)**

The absolute "≤8.0k tokens / ≤198 s" bar is within noise. A paired v29-vs-v29 run on the 48 differed by +628 tokens (standard error 453), and v29's own draws were 7.7k, 8.0k and 8.3k. Run v29 and v30 in the same lab run on all 73 tasks, including the holdout. Accept on time only if all of these hold:

- v30 mean tokens ≤ v29's mean in the same run, and ≤ 8.0k.
- v30 mean virtual seconds ≤ v29's in the same run.
- v30 p90 virtual seconds ≤ v29's p90 + 5%.
- At most 1 step per 50 tasks with more than 500 visible (non-thought, non-call) tokens.
- Compactions per task ≤ v29's + 0.1.

If it fails, try `max_tool_calls` 28 with "28" in the prompt, as the design already proposes. If no lab run is possible, ship 28 calls / thinking 2048 / max_turns 50. That projects to 7.4k tokens and 176 s before prompt effects (−7.5% vs v29), enough buffer for the prompt changes.

Analysis scripts are in (scratchpad)/rv30/ (a1.py to a8.py; a6.py is the config simulation). They read (scratchpad)/tokan/recs.json. The harness code behind the budget_warning and max_turns facts is in (scratchpad)/wh31/venv/lib/python3.12/site-packages/swegemma/tools/base.py and .../swegemma/harness/agent_runner.py.
**Verdict: ship with edits.** Send v30 to the paired lab gate only after the edits below, not straight to the leaderboard. Nothing here was run in the lab.

The config changes (thinking 2048, max_turns 50, 32 calls) and the harness mechanics do not depend on the repo. I checked the budget_warning claim in `swegemma/tools/base.py`: it fires on every counted call once `remaining <= 10`, so it appears from call 22 at a cap of 32.

The prompt has three generalisation problems:
- **Fitted rules.** All of the new reproducer and trace content comes from the 8 near-miss tasks. Those are all fastapi or rich: 14873, 4079, 11194, 14419, 3521, 3506, 5624 and 3480. Two of those rules point the wrong way on unfamiliar repos.
- **Undisclosed drops.** The design says "all other v29 mechanics are kept", but 7 v29 clauses were dropped without being listed (see the last section).
- **src layout.** The lab has one src-layout task, requests_6644. In all three runs the reproducer imported the installed copy instead of the workspace:
  - v29 lab15a log, lines 61–87: "Wait, it still failed!", then `requests.__file__` printed `/usr/local/lib/python3.12/dist-packages`, then a rerun with `PYTHONPATH=/workspace/src`.
  - v29c36 lab16a, lines 151–156: the same.
  - Recovering cost about 3 calls each time. v29 used all 28 calls; v29c36 used all 36.
  - v30's "the bug exists, so skip version checks" would discourage exactly the `__file__` check that rescued these runs.

## Required edits (old → new)

Prompt file: `(scratchpad)/oct15/v30_system.md`

1. **Fitted to rich's split_cells.** 3506 and 3521 are the same function; "every index" and "parts add up" come from its gold patch. Gemma copies examples literally, and fuzz loops cost completion tokens, which is the gate's limiting metric. This edit also restores v29's try/except, which v30 dropped without listing it.
   - Old: "Judge output only by what the issue, a docstring or a test promises (parts add up, round trip, a count), never by a guess. With no failing input given, loop over many inputs, including long ones mixing the kinds the code treats differently, and every index, printing only the first failure."
   - New: "Judge output only by what the issue, a docstring or a test promises, never by a guess. With no failing input given, try several varied inputs, including edge cases the code treats differently, each in try and except, printing only the first failure."

2. **Fitted to fastapi_11194, and pointing the wrong way.** Constructors, registration and config are common bug sites; 14873 is an `__init__`-order bug in setup code. "Skip version checks" also blocks the stale-import diagnosis.
   - Old: "If nothing fails, your inputs missed the case; the bug exists, so skip version checks and read the function that converts or validates each value at run time (not setup or schema code)."
   - New: "If nothing fails, your inputs missed the case, not the bug: do not check versions; read the code path the issue names."

3. **src-layout guard.** Insert before "Call the public API as a user would":
   - New: "Its first line prints the package's __file__; if that is outside /workspace, prefix python3 and pytest with PYTHONPATH set to the folder holding the package (src layout: /workspace/src)."
   - Why: the lab evidence above. On the scorer, the editable install is `pip install --no-build-isolation ... || true`, so it fails silently when the build backend isn't installed. The `workspace_paths.pth` entries are appended after site-packages, so an installed copy can still win.

4. **Scope change the design does not list.** v30 now writes a reproducer for feature requests too, which costs a call for an AttributeError.
   - Old: "If the issue shows no error output, before editing write one reproducer"
   - New: "If the issue describes a bug but shows no error output, before editing write one reproducer"

5. **Restore the edit deadline that has scores on private repos.** "By call 12" is the rule behind v29's 0.18, the 0.22 bundle and the 0.24 notebook. Softening it is backed by lab data only. The budget_warning backstop stays.
   - Old: "Once you can name the line to change, edit it; aim for call 12."
   - New: "Once you can name the line to change, edit it; by call 12 a source file must be changed, so if unsure, edit the best candidate."

6. **Contradiction.** The first reproducer run usually exits non-zero, which makes it a failed call. The Rules line then forbids the rerun that step 4 orders. This clause was a v29 review fix, and v30 dropped it.
   - Old: "Never repeat a search or failed call unchanged."
   - New: "Never repeat a search or failed call unchanged; rerunning the reproducer or a test after an edit is expected."

7. **Cut-offs and compaction.** Compaction keeps only the last 5 events, so earlier reads are gone. On fastapi and rich Gemma partly knows the code from pretraining; on private repos it cannot write old_string from memory. Files with long lines are also cut off more often than in rich.
   - Old: "After a cut-off or failed call, continue from what is above; never re-read what you have."
   - New: "If a read is cut off, read on from the last line number shown. Never re-read lines still shown above; if they are gone, re-read only the lines you will edit."

8. **Conflicts with the 2–3 line anchor rule.** One-line anchors are often not unique in large files.
   - Old: "On not found, re-read the lines and use a shorter anchor."
   - New: "On not found, re-read those lines and copy old_string from that output."

9. **head -30 with several strings.** Hits for a common string fill all 30 lines, and the model can't tell the rarer string was cut. This matters more in repos larger than rich.
   - Old: "Use git grep -n -F with several strings in one call (-e 'A' -e 'B'), limited to the package directory, piped into head -30. Empty output means no match."
   - New: "Use git grep -n -F with several distinctive strings in one call (-e 'A' -e 'B'), limited to the package directory shown in the layout, piped into head -30. Empty output means no match; 30 lines means the list is cut, so search again with fewer strings."

10. **Twin check (step 7).** Three problems with the current sentence:
    - A large feature diff pushes the trailing grep past the silent 5000-character cut.
    - A quote in the original Python line breaks the shell quoting, so the whole command fails, including status and diff.
    - After an insert-only edit, the model's own edit site matches the grep.
    - Old: "In one run_command run git status --short, git diff and git grep -n -F on the original line you replaced; if a copied twin (sibling method, sync or async) has it, make the same change there and nothing else."
    - New: "In one run_command run git grep -n -F on a quote-free part of the original line you replaced, piped into head -10, then git status --short and git diff; if a copied twin elsewhere (sibling method, sync or async) still has it, make the same change there and nothing else."

11. **Step 6, unfamiliar test setups.** Private snapshots may have no matching test, or tests that need settings or plugins to start.
    - Old: "at most twice; never the whole suite." New: "at most twice; never the whole suite. If no test file matches, skip this step."
    - Old: "A failure whose traceback misses your code is old." New: "A failure whose traceback misses your code, or pytest failing to start, existed before; ignore it." (This restores v29's "ignore it", which v30 lost.)

With all eleven edits the prompt is 4,758 bytes (v30 is 4,199; the 0.22 prompt is about 6 KB). It still has no braces, backticks or backslashes. Completion tokens should not go up: edit 1 removes the fuzz loops and edit 4 removes reproducers for features.

## Recommended, not blocking
- Restore v29's "write_file cannot write outside /workspace, so scratch files go through run_command." v27 hit this in 29 of 48 tasks.
- Change "Delete stray files in /workspace." to "Delete stray files you created in /workspace." The harness writes pytest.ini and conftest.py on the scorer.
- Change "copy the closest sibling and its registration" to "follow the closest sibling, including its registration", so the model doesn't paste a whole long sibling in a big private file.
- Change "Run code instead of tracing it by hand." to add "when it runs without setup." Application repos often can't run a snippet.
- For features, spend the call that edit 4 saves on reading one existing test of the closest sibling. This comes from the 0.22 bundle, the only one here with private-repo scores. It was rejected on a lab correlation (46% vs 51%), which is within noise.

## Gate changes
- **Evidence tasks are in-sample.** The design expects about +0.5 per new rule, but all of that comes from the 8 tasks the rules were written from. Count those 8 separately, and require solves on the other 65 to be at least v29's.
- **src layout:** include requests_6644. Record where the reproducer imports from in every run.
- **Thinking cap:** report the share of LLM calls that hit the 2048 cap, and the solved tasks with at least one such call (v29 had 7 of 40). Unfamiliar code will hit the cap more often than the lab shows.
- The lab still has no out-of-sample repo. Keep the forecast of 0.20 to 0.22; 0.25 is not supported.

## Design text that is inaccurate
"All other v29 mechanics are kept" is false. These v29 clauses were dropped without being listed:
- "describes a bug but"
- "each wrapped in try and except, printing repr"
- "write_file cannot write outside /workspace"
- "rerunning the reproducer or the test after an edit is expected"
- "shown in the layout"
- "ignore it"
- "you created"

Evidence files:
- `(scratchpad)/lab15aout/lab/v29/r0/logs/requests_6644.log`
- `(scratchpad)/lab16aout/lab/v29c36/r0/logs/requests_6644.log`
- `(scratchpad)/data/sandbox/setup.py` (lines 290–318)
- `(scratchpad)/wh31/venv/lib/python3.12/site-packages/swegemma/harness/container_setup.py` (line 516)
- `(scratchpad)/wh31/venv/lib/python3.12/site-packages/swegemma/tools/base.py` (lines 47–68)
- `(scratchpad)/oct15/near/*/gold.patch`
**Verdict: ship with edits.** That means it can go to the lab gate once these edits are in. It should not go to the scorer before the gate. None of the problems below is fatal. Three of them reverse v29 mechanics that had measured effects, and the design does not account for that.

Data used: lab15/16 v29 and v29c36 traces (194 runs), taken from `tokan/recs.json`. Harness checked: swegemma 0.2.11 in the scratchpad `wh31` venv. The analysis scripts are in `(scratchpad)/rv30/m1.py` to `m16.py`.

**Facts that hold**
- The budget_warning sentence matches the code (`tools/base.py:47-69`). The warning is added when 10 or fewer calls remain and the cap is at least 20, so at a cap of 32 it starts on call 22.
- run_command is safe with backslash-n inside the command: 254 such calls worked and 1 was corrupted. So the new reproducer content is not a parser risk.
- The thinking cap is enforced: completion tokens per call reach about 4.1k at p99. Cutting thoughts to 2048 would remove at most 7.1% of v29's completion tokens, which is consistent with −6.5%.
- max_turns 50 is supported. The latest successful edit in any run was at LLM call 42, and the 32nd counted tool call lands at LLM call 32 or 33.

**Required prompt edits (old -> new)**

1. Rules. This contradicts step 5 ("re-read the lines") and blocks re-reads after compaction. About 54 of the roughly 317 re-reads after compaction were followed within 3 calls by a successful edit.
   - Old: "After a cut-off or failed call, continue from what is above; never re-read what you have."
   - New: "After a cut-off or failed call, continue from what is above. Re-read only lines no longer shown above, or the lines around an old_string that was not found."

2. Step 3. The design says all v29 mechanics are kept, but the write_file sentence was dropped. v27, without it, made 95 write_file calls to /tmp and all of them failed; v29 made 2.
   - Old: "If setup blocks it, drop it."
   - New: "write_file cannot write outside /workspace, so scratch files go through run_command. If setup blocks it, drop it."

3. Step 3. This broadening was not in the design. It forces a reproducer before editing on feature tasks, and "the bug exists" makes no sense there.
   - Old: "3. If the issue shows no error output, before editing write one reproducer in one run_command:"
   - New: "3. If the issue describes a bug but shows no error output, before editing write one reproducer in one run_command:"

4. Step 4. As written it contradicts the step 5 ladder ("do not resend") and the step 3 rule to write the reproducer first. 5 of the 31 empty-patch runs already had a failed edit before the cap; rich_3063 had 60 missing-parameter resends.
   - Old: "If you see budget_warning with no edit made, your next call is edit_file with your best fix from code already shown."
   - New: "If you see budget_warning with no edit made, your next call is the edit, even without a reproducer: edit_file with your best fix from code already shown, or the step 5 python script if an edit_file call already failed."

5. Step 4. Softening "by call 12" has no evidence behind it. Every scored config in this family has the hard rule (Budget-Fit, the 0.22 bundle, v29), and 749198 measured it.
   - Old: "Once you can name the line to change, edit it; aim for call 12."
   - New: "Once you can name the line to change, edit it; by call 12 a source file must be changed, and if unsure, edit the best candidate."

6. Step 4. This contradicts the step 7 twin edit.
   - Old: "Rerun the reproducer; if it now shows what the issue promises, stop editing."
   - New: "Rerun the reproducer; if it now shows what the issue promises, make no further edits except a step 7 twin."

7. Step 7. Two problems:
   - The grep comes last, so the silent 5000-character cut removes it first: 4 of 84 diffs already reached 5000 characters, and p90 is 2.9k.
   - Grepping a whole code line breaks shell quoting: 49% of edited lines contain `"`. In a repo that uses single quotes, the `-e '...'` form fails, and a quoting error stops the status and diff from running too.
   - Old: "7. In one run_command run git status --short, git diff and git grep -n -F on the original line you replaced; if a copied twin (sibling method, sync or async) has it, make the same change there and nothing else."
   - New: "7. In one run_command run git grep -n -F -e with a short fragment of the original line you replaced (no quotes or backslashes) in the package directory piped into head -10, then git status --short, then git diff. If a copied twin (sibling method, sync or async) has that line, make the same change there and nothing else."

8. Step 2. Several `-e` patterns under one `head -30` mix their matches together, so a common string hides the rare ones. 55 of 449 single-string v29 greps already hit 30 lines. The design's claim that this "costs nothing" is wrong.
   - Old: "Use git grep -n -F with several strings in one call (-e 'A' -e 'B'), limited to the package directory, piped into head -30."
   - New: "Batch independent searches in one run_command: one git grep -n -F per string, limited to the package directory, each piped into head -10."

9. Rules. Dropping v29's exception for reruns creates a contradiction: a reproducer that shows the bug exits 1 and is reported as CommandError, so rerunning it counts as repeating a failed call (14 such reruns in the data).
   - Old: "Never repeat a search or failed call unchanged."
   - New: "Never repeat a search or failed call unchanged, except rerunning the reproducer or test after an edit."

10. Step 6. Make the file lookup conditional so it does not cost a call on every run, and cap its output.
    - Old: "6. Check: find the test file with git ls-files piped into grep, then run timeout 60 python3 -m pytest on it -q, piped into tail -15, at most twice; never the whole suite."
    - New: "6. Check: if you have not seen the test file path, find it with git ls-files piped into grep and head -20; then run timeout 60 python3 -m pytest on that file -q, piped into tail -15, at most twice; never the whole suite."

**Required corrections to the design and bundle text**
- **Submit loops.** "STATUS records those post-budget submits as refused" is false:
  - submit_patch and get_status use `budget_gated(count_tool_call=False)` (`swegemma/tools/execution.py:76,119`), so neither the tool-call budget nor the turn budget can refuse them.
  - Every repeat submit in the traces returned `{"status": "ok", "patch_size": N}`.
  - Most loops start with calls left: fastapi_14492 made 50 submits at 19 tool calls, and rich_3506 made 63 at 13.
  - The prompt rule is still valid, because the fallback diff is identical to what a submit would capture. Fix the STATUS line that says "harmless, refused calls".
- **max_turns evidence.** "No first submit after LLM call 45" is off by one: lab16 v29 rich_3882 first submitted at LLM call 46 and was resolved. That run lost 31 calls to corrupted edit_file calls. Calls that fail with a missing parameter are rejected before the budget wrapper runs, so they use up turns, are never counted as tool calls, and never trigger budget_warning.
- **Edit corruption cause.** The main corruption is not backslash-n. 183 of the corrupted edit_file calls end new_string with "`,old_string:", meaning the closing delimiter came out as a backtick; only 32 contain backslash-n. The first edit_file call in a run is corrupted 14% of the time, and resends are corrupted much more often.
- **Missing counter-evidence.** Add 748168 to the evidence: Murugesan's 240 s / 32 calls / 8 min / 80 turns config with thinking 4096 timed out with no score. It is confounded, since his 28-call version also timed out (748618), but it is the only public data point on 32 calls.
- **Mislabelled evidence.** The "public test 50 vs 48 of 129" is a third-party local run (Ayush, 746250), not a leaderboard score.
- **Lint gate.** `lint_bundle.py` on the assembled bundle returns FAIL with "max_tool_calls > 28 at 8 min". Change the rule on purpose rather than bypassing it.
- **Stale config comment.** `v30_eval_config.yaml` still says timeout_seconds bounds the grader's pytest. The grader uses a fixed 300 s.

**Add to the lab gate**
- write_file calls to /tmp.
- Streaks of missing-parameter edit_file calls.
- Runs that end at the 50-turn cap with fewer than 32 tool calls.
- Repeat submits.
- Twin edits and how those tasks turned out. The twin rule rests on one task (rich_3480), the same standard the design used to reject other ideas.
# Token analysis
Completion tokens: v29 averages 8,009 per task over 96 runs (labs 15a and 16a, 40 solved). The thought text in `message` is the whole of the model's reasoning, so there is no hidden reasoning left over. Four changes together would cut completion tokens by an estimated 18% (22% on the 25 holdout tasks). Only the two config changes are certain to save tokens (about 7%); the rest depends on Gemma following new prompt rules about how it thinks, and needs a paired lab run to confirm.

## Where completion tokens go

**Split by text type** (the Gemma 4 tokenizer was run over every step):

| Part | Share | Notes |
|---|---|---|
| Thought text (`message`) | 74.4% | This is the reasoning channel. Capped thoughts end at exactly 4,094 tokens, which is the 4,096 thinking budget. |
| Tool-call arguments | 23.4% | |
| Remainder | 2.3% | About 6 formatting tokens per call (median 6, 5th–95th percentile 5–6). |

The remainder is not hidden reasoning, so it is not something to cut.

**Thoughts are very uneven in length.** The median is 36 tokens per call, the 90th percentile 499 and the maximum 4,094. The longest 10% of calls hold 65% of all thought tokens. Calls with a thought over 1,000 tokens are 4.8% of calls but carry 38% of completion tokens.
- 63 of those 138 long thoughts come right after reading code.
- 52 of them end in yet another search or read rather than an edit.
- Of their text, 28% is code blocks and 30% is paragraphs opening with "Wait", "Actually" or "Hmm". There are 31 "Wait"s per task.

**By tool** (tokens per task and share):

| Tool | Tokens/task | Share | Calls/task |
|---|---|---|---|
| Reproducer runs | 2,036 | 25.4% | 3.2 |
| Searches | 1,860 | 23.2% | 7.9 |
| `edit_file` | 1,338 | 16.7% | |
| `read_file` | 1,317 | 16.4% | |
| `submit_patch` | 373 | 4.7% | 4.2 |
| `cat`/`sed` reads | 291 | 3.6% | |
| pytest | 211 | 2.6% | |
| Text-only turns | 177 | 2.2% | |
| git | 119 | 1.5% | |
| `rm` of /tmp files | 92 | 1.2% | |

**By phase:**

| Phase | Share | Calls/task |
|---|---|---|
| Before first edit | 58.2% | 15.6 |
| Edit calls | 18.6% | |
| Checking | 15.3% | |
| The submit call | 3.7% | |
| After first submit | 4.2% | 4.6 |

**Solved vs unsolved:** solved tasks use 6,197 tokens, unsolved 9,304.
- Most of the gap is before the first edit: 3,135 tokens over 10.5 calls when solved, 5,757 over 19.2 calls when unsolved.
- Unsolved tasks have far more long thoughts: calls over 1,000 tokens carry 42% of their tokens, against 29% in solved tasks.
- Of the 48 tasks run in both labs, the 17 solved both times average 5,618 tokens, and the 25 never solved average 9,055.

## Waste patterns

| Pattern | Count | Share of completion tokens |
|---|---|---|
| Code copied from earlier tool output into thoughts | in 95 of 96 tasks | 13.0% (12.7–14.6% in v27 and v28 too) |
| Code drafted in thoughts and never used | | 4.0% |
| Code drafted in thoughts, then retyped in the call | | 1.8% |
| Tracing code by hand ("Let's trace…") | | 2.1% |
| Reproducer written a 3rd time or more | 101 calls in 40 tasks | 9.0% (6.1% before the first edit, which the prompt forbids) |
| Same thought lines repeated from earlier calls | 2,851 lines | 7.0% |
| Re-reading lines already read (call cost) | 195 calls | 8.5%, plus 1,110 prompt tokens/task; 61% of these happen after a context compaction |
| Exact repeat of an earlier call | 190 calls | 6.3% (67 are failed `edit_file` calls resent unchanged) |
| Search right after another search | 2.7/task | 5.7% (only 2 of 758 searches used more than one pattern; only 34% piped into `head`) |
| Search with empty output | 157 | 5.5% |
| Failed `edit_file` | 114 | 5.8% (48 are missing `old_string`, i.e. parser corruption; 7 tasks had 5 or more failures in a row) |
| Thought hitting the 4,096 cap | 15 calls | 8.6% |
| `submit_patch` loops after the budget | 6 tasks, 307 repeat submits | 1.0% of tokens, but 10% of LLM calls and 14.8% of prompt tokens |

Five of the capped thoughts are pure loops at the end of the budget ("Wait, I'll try to call `submit_patch`. Actually…").

The submit loops happen because `submit_patch` does not end the run: the harness only stops on a text-only reply after submitting, or when it reaches `max_turns: 80`.

Several suspected patterns turned out to be small:
- Restating the issue: the first thought is 1.7% and lines copied from the issue 1.1%.
- Large `new_string` blocks: 1.2%.
- pytest calls: 2.6% of completion tokens, plus 354 prompt tokens per task of output.
- Text-only turns before submitting: about 0%.

## Prompt growth and the hidden cost of compaction

- **Starting size and growth:** the first call's prompt is about 3,732 tokens (system prompt 827, issue 1,658). Earlier thoughts are resent each call, so the prompt grows by roughly the last thought plus its arguments and output: 595 tokens per call on average (median 342, 90th percentile 1,484).
- **Compaction:** above 14,336 tokens the history is summarised, and the prompt drops from about 15.1k to 5.7k. Mean prompt is 8.7k per call; total is 260k per task.
- **Uncached prefill:** about 36.6k tokens per task, which is 14% of all prompt tokens and fits vLLM's logged 89–92% cache hit rate. 68% of that uncached prefill comes from compactions.
- **Compaction counts per task:** v29 1.20, v29c36 1.29, v27 1.08, v28 1.40, v28t 0.50.
- **Not counted by our clock:** each compaction is an extra LLM call missing from both the traces and the virtual clock. vLLM's request count exceeds the trace count by exactly the number of compactions (lab15a: 52 extra requests against 53 compactions).
- **Size of that blind spot:** each compaction generates about 780–800 tokens. That is about 11% more decode than the virtual clock counts, about 960 tokens per task for v29.
- **v28 against the clock:** this blind spot may explain why v28 went over the 12 h limit even though the lab clock looked fine.

Completion tokens already make up 92.5% of v29's virtual time (177 of 191 s), so cutting them is the main lever on runtime.

## Proposed changes

Savings below are mechanical upper bounds: they assume the model keeps the rest of its behaviour.

| Change | Lab 15a+16a | v29c36 | Holdout 25 |
|---|---|---|---|
| A. `thinking_budget` 4096 → 2048 | −6.5% | −7.9% | −9.3% |
| B. No code copied into thoughts, at 50% compliance (100%) | −6.5% (−13.0%) | −6.9% (−13.8%) | −6.8% (−13.5%) |
| C. Reproducer written at most twice | −4.9% | | |
| D. `submit_patch` rule | −2.8% | | −6.1% |
| E. `max_turns` 80 → 50 | −0.4% tokens, −5% calls, −3.5% prompt | | |
| **A + B(50%) + C + D + E** | **−18.0%** | **−18.4%** | **−22.4%** |
| Same but `thinking_budget` 1536 | −20.8% | | |
| Prompt and E only, budget unchanged | −14.1% | | −17.9% |

Notes on each change:
- **A** shortens 44 calls. Only 7 of the 40 solved tasks contain a call over 2,048 tokens, against 26 of 56 unsolved. A public test of 2048 against 4096 scored 50 vs 48 out of 129.
- **E** carries no risk in this data: across 144 runs, no first submit or successful edit came after LLM call 45.
- **Including the compaction summaries**, the full package's total generated tokens fall about the same amount, −17.4%, with compactions dropping from 1.29 to 1.14 per task.
- **Not recommended: `include_thoughts: false`.** v28t used *more* completion tokens than v28 (10,427 vs 9,812), so the fewer compactions only break even.

Concrete edits:
- `configs/sampling.yaml`: `thinking_budget: 2048`.
- `eval_config.yaml`: `max_turns: 50`.
- `prompts/system.md`:
  1. New paragraph after the limits sentence: "Keep each thought to a few short lines: what the last output showed and which call comes next. Never copy code, file contents or issue text into a thought; cite file and line. Do not trace code by hand; run it. Write new code only inside the edit_file or reproducer call."
  2. Step 3: replace "Spend at most two calls on it before the first edit." with "Write it once; rewrite it at most once, and only if it failed to run; after that only rerun it with timeout 30 python3 /tmp/r.py. Leave /tmp files alone."
  3. Step 2: add "Put several strings in one search: git grep -n -F -e 'A' -e 'B' -- <pkg> | head -30."
  4. Step 7: replace "call submit_patch and stop with a one-line summary" with "call submit_patch once; it works at any time, even after the call limit. When it returns, reply with one line of plain text and no tool call."

**Steps to reach 0.25:**
1. **Package on v29c36:** projected 9,182 → about 7,489 completion tokens, or about 8.5k including compaction summaries. That is below v29's measured 8,009, or about 9.0k with summaries, which fit the time limit. So the +2 to +3 solves from 36 calls might become affordable.
2. **Lab check:** a paired run of v29 against v29+package (and v29c36+package) on the 48 tasks plus the 25 holdout. Accept if completion tokens per task fall at least 15% and solves stay within one of v29 (lab noise is about ±3).
3. **Compliance to measure:** copied-code tokens (now 1,044 per task), 3rd-or-later reproducer writes (101), submits per task (4.18) and "Wait" count (31 per task).
4. **Clock fix:** add about 800 tokens per compaction to the virtual clock.

The scripts are in (scratchpad)/tokan:
- extract.py
- analyze.py
- waste.py
- sim.py
- common.py
- recs.json (all labs, every step tokenised)

The tokenizer is in (scratchpad)/tok/g4/tokenizer.json. Run the scripts with (scratchpad)/tok/venv/bin/python -I.
# 0.22 idea gap
**0.22 prompt vs v29: behavioural ideas v29 lacks or contradicts, ranked by expected value under the 12 h budget**

**Budget:** v29 runs at about 8.0k completion tokens per task and about 270 tokens per call, and 55% of runs use all 28 calls. The scorer ceiling sits between v27-like (8.6k) and v28 (9.8k), so the headroom over v29 is about 0.6k tokens per task, roughly 2 calls. No single idea below is a confident +1 task; with per-draw sd of about 1 task, each is worth a fraction of one. The top items count because they cost no tokens or save them.

**Evidence base:** I measured these from lab traces: v27 121 runs, v28 48, v29 121, v29c36 73 (labs 12–16).

**Caveat on the "0.22" label:** the notebook text itself says "This candidate has not been scored". The 0.22 attribution rests on the third-party evidence in research_oct15.md.

**Ranked**

1. **Find the test file by search before running pytest, then focus it with -k** (v29 lacks this; it says "the test file for the module").
   - Private repos: test layouts are unknown, so guessing from the module name fails more often than in our lab.
   - Cost: none if the test path goes into the first locate search (git ls-files filtered by keyword). It saves about 0.25 calls per task.
   - Lab: **for**. 29 of 121 v29 runs (24%) ran pytest on a path that does not exist ("file or directory not found", "no tests ran"). That is 29 of 151 pytest calls, and 27 of them were followed by a find/ls call. Each one also used up one of the two allowed pytest runs. v27 had this once.

2. **Run a snippet once instead of keeping a reproducer file** (contradicts v29 step 3). Don't adopt it as written; take a cap from it.
   - Cost: this is the biggest token lever in the gap. The v29 reproducer is 24.8% of completion tokens (about 1.9k per task): 3.5 reproducer calls per task, 2.1 full script rewrites per task, about 565 tokens per call.
   - Lab: **against** adopting it fully. Runs that used a reproducer before the first edit resolved 48% vs 21% for runs that didn't (confounded). v27 to v29 credits part of its gain to the reproducer.
   - Recommendation: write the script once and rerun the same file after edits. That is about −0.5k tokens per task, which pays for everything below.

3. **For features, copy the closest sibling, including its registration points** (`__all__`, option and dispatch tables, imports). v29 lacks this.
   - Private repos: the model cannot recall local registration conventions, so a sibling is the only source. Hidden tests import the new names.
   - Cost: 0–1 call; the sibling is often in the file already read.
   - Lab: **neutral**, no task tests it. Only 1 of 73 gold patches touches `__init__`/`__all__`. Registration-style tables appear in rich_3676, 3942, 3675 and 3777, which no bundle solved, and those failed for other reasons. Reviewer 1 recommended restoring the rule.

4. **Zero-call meaning rules** (v29 has these only partly):
   - fix where the wrong value is produced, not where it shows;
   - never special-case the issue's example;
   - keep existing signatures, defaults and backward compatibility;
   - follow local idioms (the repo's own exception classes and naming).
   - Private repos: this is the main way to match conventions the model has never seen.
   - Cost: about 0 calls, a few dozen thinking tokens.
   - Lab: **weak for**. The v29 failure analysis has 3 wrong-location tasks and 1 that broke existing behaviour (3180).

5. **Hard limits v29 lacks**: never run a whole suite, don't explore site-packages, write_file only for a new module.
   - Private repos: one whole-suite run can hit the 240 s command timeout, half of the 8-minute task budget. This is runtime insurance.
   - Cost: 0.
   - Lab: **weak for**. Whole-suite runs: v29 1 of 121, v29c36 2 of 73. Site-packages/inspect commands: 26 in v29 (0.2 per task). Failed write_file calls on existing files are mostly parameter corruption (one task), not misuse.

6. **List only the edge cases the issue mentions** (empty, None, defaults and so on) before the first call. Drop the rule to handle every implied edge case.
   - Private repos: the issue is the only specification.
   - Cost: about 30 tokens on the first turn (v28 220 vs v29 188).
   - Lab: **mixed**. Wrong semantics is failure cause #2 (7 tasks), but over-editing broke 3180 and 3470. v28 had the full rule and lost.

7. **Check the issue's literals and remove debug prints in the final diff** (v29 lacks this).
   - Cost: 0 calls; it happens in the git diff call v29 already makes.
   - Lab: **weak for**. One contract-mismatch task (15588).

8. **Edit-failure ladder.** Adopt only one part: on "not found" or "multiple matches", re-read the lines with cat -n and use a smaller unique anchor.
   - Keep v29's switch to a heredoc on the *first* missing-parameter error. The 0.22 prompt waits for 2 failures, but the lab shows that once literal backslash-n appears, 55 of 67 calls are corrupted.
   - Cost: saves about 0.1 call per task.
   - Lab: **mildly for**. v29 had 17 not-found/multiple failures in 121 runs. After a failed edit, the next call was a re-read 15 times, a heredoc 14 times, a successful retry 9 times, and submit_patch at budget end 15 times.

9. **Open file paths named in the issue directly.** 11% of issues name a .py path; it saves about 1 search there. Lab: neutral. Free.

10. **Read one caller or test before editing.**
    - Lab: **against as a rule**. v29 already reads a file other than the one it patches before the first edit in 94 of 98 patched runs. Runs that read a test first resolved 46% vs 51% and made the first edit 3.8 calls later. v28 was told to do this and complied in only 12.5% of runs.
    - Cost: about 1 call. Use it only when the reproducer can't be built from the issue.

11. **Call phases: check and correct in calls 13–20, no new searching after call 20.**
    - Runtime: positive in principle. Exploring after call 20 is 9.7% of v29 tokens.
    - Lab: **against**. 6 of 51 v29 solves needed searching after call 20 (3 made their first edit after 20). v29c36 gained its lab tasks from late calls. v28 had this rule and searched more after call 20 than v27 (10.3% vs 7.4% of tokens), so the model doesn't obey it.

12. **Batch independent searches in one run_command.**
    - Lab: **neutral to against**. v28 batched twice as often (0.73 per task) but did not cut searches before the first edit (6.8 vs 6.0) or bring the edit earlier. A batched call costs about 2× the tokens of a single one (458 vs 244), so it saves no time. Truncation is rare (3 of 44).

13. **Verification settings: -x, timeout 150, fix once from the traceback.**
    - Lab: **against**. -x hides regressions behind a stale-test failure. Fixing from the traceback is what made v28 revert a correct fix on 3043. 150 s is 31% of the task budget, while lab pytest averages 3.6 s and never hit the 60 s timeout. -k alone is covered in item 1.

14. **Read up to 3 regions of about 40 lines per command.**
    - Contradicts v29's 80-line limit. Three regions is about 120 lines, which often goes over the silent 5000-character cut (100-line windows exceed it 7–14% of the time, 150-line windows 70–96%).
    - Lab: **against**. v28's 40-line reads missed the bug in 5624 and 9753.

15. **Check patch_size after submit_patch and resubmit.**
    - Lab: **against**. None of v29's 174 zero-size submits happened with calls left (all at or after call 26). It would only make the submit loops longer.

16. **FastAPI docs_src rule.** Specific to one public repo; irrelevant for private repos.

**Package and token accounting:** items 1–9 together come to about −0.4k tokens per task net: −0.5k from the reproducer cap (item 2), −0.07k from item 1, and about +0.15k for the zero-call rules. That keeps the mean below v29's 8.0k and well under the about 8.6k ceiling. If the cap holds in the lab, the spare budget could also pay for a modest call-cap increase. v29c36's extra calls gained +3 tasks over 73 for +1.2k tokens per task.

Gate this in the lab only as a no-regression check plus tokens per task. The rules are fitted to fastapi and rich, and the +1 tasks would not show above the lab's ±3 noise.

Analysis scripts and data are in `(scratchpad)/gap22/`: `feat.py`, `summ.py`, `detail.py`, `detail2.py` and `rows.json`.