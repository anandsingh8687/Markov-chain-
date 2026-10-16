**Verdict: ship with edits.** Most of v29 is harness mechanics, and those carry over to private repos because the scorer runs the same harness. The rule set as a whole is still fitted to the lab sample: every rule and the promotion gate come from the same 48 lab tasks (28 fastapi, 20 rich). Four rules in particular would hurt on unseen repos (edits 1–4 below), and one rule from the 0.22 recipe, which was scored on private repos, has been dropped (edit 3).

## Required edits (exact text)

1. **Step 5, the backslash ban.**
   - Replace: "Never put triple quotes, backslashes or backticks in old_string or new_string, and do not write docstrings."
   - With: "Never put triple quotes or backticks in old_string or new_string, and do not write docstrings. Prefer old_string lines without backslashes. new_string may contain the backslash escapes the code needs; after such an edit, check that the diff in the result shows each one exactly as intended."
   - Why: 11 of the 33 gold patches add source lines with backslashes (14487, 15588, 3278, 3535, 4076, 3468, 3938, 3061, 14306, 15661, 3930). Newline and tab escapes, `\x1b` and regex escapes are ordinary in text-processing code, which is what private repos will contain.
   - The design says C2 "keeps 3278". v27's actual 3278 win was an edit_file call with backslashes in both old_string and new_string, applied with strategy "unescaped". The ban blocks the path that won it.

2. **Step 2, read size.**
   - Replace: "taking the whole suspect function in one call (up to 150 lines)."
   - With: "at most 80 lines per call. Command output is cut off silently after 5000 characters, so if a read stops early, read the next range."
   - Why:
     - swegemma 0.2.11 `budget.py` sets `max_stdout_chars=5000`, and `tools/execution.py` cuts stdout at 5000 characters with no truncation marker. read_file allows 10000.
     - I measured 150-line `cat -n` windows: they go over 5000 characters in 70% of rich windows and about 95% of windows across 22 other libraries. At 80 lines it is 0% and about 1%.
     - rich is the most compact case, so the lab understates this.

3. **Step 6, restore the "pre-existing failure" rule.** It was in both v27 and the 0.22 recipe.
   - Replace: "Any other new failure means an edit broke something: remove or narrow that edit."
   - With: "Errors whose traceback does not pass through a file you changed (missing modules, fixtures or files, pytest unable to start) existed before you; ignore them. Any other new failure means an edit broke something: remove or narrow that edit."
   - Why: as written, an environment error makes the agent revert a correct fix. Private tasks run with "different wheels", the public sandbox already lacks inline_snapshot and dirty_equals, and the harness can mask pytest (`disable_test_runners_in_sandbox` prints "pytest is disabled" and exits 1).

4. **Rules, contradiction with step 6.**
   - Replace: "Never repeat a call you already made."
   - With: "Never repeat a search or a failed call unchanged; rerunning the reproducer or a test after an edit is expected."

5. **Step 4, renames.**
   - Replace: "Comments, docstrings and renames never fix an issue."
   - With: "A change to comments or docstrings alone never fixes an issue."
   - Why: in rename, deprecation and typo tasks, the rename is the fix, and the hidden tests import the new name.

6. **Step 4, edit deadline.**
   - Replace "By call 10" with "By call 12". Keep "As soon as you can name the line to change, your next call is the edit."
   - Why: 12 is the number scored on private repos (0.18 and 0.22). The evidence for 10 is a correlation on repos Gemma partly knows from pretraining. v29 also adds a reproducer before the edit, so on unfamiliar code the deadline will force edits in the wrong place.

7. **Step 3, bound the reproducer.**
   - Change "If the issue shows no error output" to "If the issue describes a bug but shows no error output".
   - Append: "If it cannot run for setup reasons (imports, configuration, missing services or files), do not fix the environment; drop it and continue. Exit code 124 means the timeout killed it."
   - Why: rich and fastapi need almost no setup. Applications in private repos often do, and a failing reproducer can use up the calls before the edit.

8. **Step 1.**
   - Replace "and raise the way neighbouring checks do" with "and, if the issue names no exception type either, raise the way neighbouring checks do."
   - Why: this rule came from 14258, which is unsolvable. As worded, it can override an exception type the issue does state.

9. **Step 5.**
   - Replace "After a shell edit run python3 -m py_compile on the file." with "After a shell edit to a .py file, run python3 -m py_compile on it."
   - Why: running it on a template, toml or json file looks like a failure and invites a revert.

## Recommended, not blocking

- **Restore two rules from the 0.22 recipe that no lab loss justified dropping.** Add: "For a new feature, follow the closest sibling, including where it is exported or registered (package imports, __all__, option tables). Keep existing signatures and defaults." Hidden tests for private-repo features import new names from the package.
- **Step 6:** use the closest test file, adding `-k` when the file is large (the 0.22 recipe has this). "The module's test file" assumes rich's tests/test_<module>.py layout.
- **Step 2:** drop "for example splitlines or strip for lost newlines". It comes from the rich text tasks, and Gemma tends to copy examples literally.
- **Search output:** if `git grep | head -30` returns a full 30 lines, narrow the search (for example add `-- '*.py'`) rather than assuming it saw every hit.

## What the design missed

- **The gate measures fit, not gain.** The 33 analyses cover all 28 of v27's lab failures, and the gate re-runs those same 48 tasks. "v27 + 2" with ±3 noise and about 15% flips between identical runs is expected even with no real improvement. Use the lab only as a no-regression and process-metric gate: first-edit call, corrupted calls, seconds per task. Drop the "+1 over 0.22 on the board" forecast.
- **Lab and leaderboard disagree.** The lab ranked v27 over v28 (5–0). On the leaderboard, which is scored on private repos, the 0.22 prompt that v28 is modelled on beat Budget-Fit, the family v27 belongs to, 13 to 11. So removing 0.22-recipe rules because of lab losses (5624, 9753, 9425, 3043, all within noise) is the riskiest kind of change here. A rule that only lab evidence supports should not replace one from the 0.22 recipe.
- **No out-of-sample check.** A public notebook built 31 tasks from repos outside the public set (pyairtable, django-axes, polyfactory, bandit). The lab also has no src-layout repos.
- **Import-path fallback.** In the scorer, `/tmp/r.py` imports the workspace only through the editable install or the workspace_paths.pth file. The editable install is `pip install --no-deps -e /workspace || true`, so it can fail silently. A one-line fallback would cover this (rerun with PYTHONPATH=/workspace, or /workspace/src for a src layout, and never install). This is low risk, so I left it optional.

## Evidence files

- Harness: `(scratchpad)/wh31/venv/lib/python3.12/site-packages/swegemma/budget.py`, `(scratchpad)/wh31/venv/lib/python3.12/site-packages/swegemma/tools/execution.py`, `(scratchpad)/wh31/venv/lib/python3.12/site-packages/swegemma/harness/container_setup.py`
- v27's 3278 edit with backslashes (step 8): `(scratchpad)/oct15/fa/rich_3278/v27_trajectory.txt`
- Gold patches: `(scratchpad)/oct15/fa/*/gold.patch`
- 0.22 prompt: `(scratchpad)/oct15/nbtxt/flexonafft__gemma-4-budget-aware-coding-agent-v2.txt`
**Verdict: ship with edits.**

I found no templating or parser hazard. The prompt is 3,477 bytes of plain ASCII with no braces or backticks, `!include` passes it through as a raw string, and the lint passes. Moving work onto the single-argument `run_command` is safe: 0 of 836 `run_command` calls in the v27/v28 traces were corrupted, against 79 `edit_file` calls with a missing old_string or filepath. In both sandboxes `git grep | head` returns exit 0, because bash runs without pipefail. The scratch path `/tmp/r.py` is rewritten to the sandbox's own tmp directory, and `PYTHONPATH` points at the workspace, so a script in /tmp imports the edited source.

Several sentences do cause harness failures, though, or quietly make runs slower. The required edits follow, most important first.

**Required edits**

1. **The 150-line read is cut off without notice.** `run_command` truncates stdout at 5,000 characters with no flag (`swegemma/tools/execution.py`: `result.stdout[:max_chars]`). `read_file` allows 10,000 characters and sets `is_truncated`. I measured `cat -n` windows on the rich and fastapi mirrors: 150-line windows exceed 5,000 characters in 70% (rich) and 96% (fastapi) of positions, 100-line windows in 7% and 14%, and 80-line windows in 0%. The agent will believe it read lines it never saw, such as a loop branch below the cut, as in rich_4006.
   - Replace: "Read with run_command, cat -n file piped to sed -n with a line range, taking the whole suspect function in one call (up to 150 lines)."
   - With: "Read with run_command: cat -n file piped to sed -n with a range of at most 80 lines. Output beyond 5000 characters is cut off without notice, so check the last line number shown and read the next range if the function continues."
   - Design fix: C3's claim that this removes "the 150-line head silently returned" is backwards. read_file flags its truncation; run_command does not.

2. **"Never repeat a call you already made" contradicts step 6 ("rerun the reproducer").** A literal model will skip the rerun or stall.
   - Replace with: "Never repeat a search, a read or a failed call unchanged; rerunning the reproducer or the test command after an edit is expected."

3. **The check step can revert correct fixes and has no limit.**
   - With `-x`, only the first failure shows, which is usually the stale test.
   - v27's clause for pre-existing or environment failures was dropped, while "Any other new failure means ... remove or narrow that edit" was added. That brings back the rich_3043 revert, and it invites `git stash` baselines, a known way to lose patches (history v23).
   - "fix it instead of explaining it away" has no round limit, and `timeout 120` is 25% of the 8-minute budget.
   - Replace: "then timeout 120 python3 -m pytest on the module's test file with -q -x and tail -20."
   - With: "then timeout 60 python3 -m pytest on that module's test file with -q, piped into tail -15. Run pytest at most twice."
   - Add: "A failing test that does not exercise the lines you changed was failing before; ignore it. If pytest is disabled, rely on the reproducer. Never use git stash, git checkout or git reset."
   - Add: "At most two fix-and-recheck rounds, then submit."
   - Change "Run any repository code under timeout 30" so it matches: 30 for scripts, 60 for pytest.

4. **Backslashes are banned, but the prompt never says what to do when the fix needs one** (for example `"\n"`, regex classes or `\x1b`). In the traces, 74 of 79 corrupted `edit_file` calls contained literal backslash escapes and only 14 contained triple quotes, so the design's "~all from triple quotes" is wrong; backslashes are the main marker. The script fallback also needs a call budget.
   - Replace: "If edit_file reports a missing parameter, do not resend it; make the change with run_command python3 - ... writes the file. ... After a shell edit run python3 -m py_compile on the file."
   - With: "If the old or new code needs a backslash, triple quote or backtick, or edit_file reports a missing parameter, do not use or resend edit_file. In one run_command, run python3 - with a quoted heredoc that reads the file, asserts the old text occurs once, replaces it, writes the file, and then runs python3 -m py_compile on it in the same command. In that script prefer an old text with no backslashes and write strings as raw strings."
   - Why raw strings: v27's heredoc on fastapi_15588 failed with "Failed to find old_text" on the `\0` escape.

5. **`head -30` hides the source hit in docs-heavy repos.** `git grep` lists files alphabetically, so docs/ and docs_src/ come before the package. On fastapi the first source hit sits at output line 136 for include_router, 71 for ServerSentEvent and 831 for Depends.
   - Replace: "Use git grep -n for identifiers from the issue"
   - With: "Use git grep -n for identifiers from the issue, restricted to the package directory shown in the layout (git grep -n NAME -- PACKAGE_DIR)".

6. **The progress line primes broken tool calls and miscounts.** The Gemma call syntax is literally `call:run_command{...}`. v28 rich_3506 step 9 emitted exactly that as plain text without the opening token. A text-only turn triggers a nudge, and 3 nudges in a row end the session (agent_runner max_nudges=3). Starting every turn with "call N" makes this more likely. The model's own count also drifts from the harness count, which skips malformed calls, get_status and submit_patch.
   - Replace: "Before every tool call write one short line: call N of 28, diff empty or not, and what this call is for."
   - With: "Before every tool call write one short line: Progress N/28, files edited so far (none or their names), purpose of this call. get_status does not use up a call; check it if unsure."

7. **Reproducer mechanics.**
   - A script that exits non-zero becomes a CommandError that repeats stderr twice (error_message plus details.stderr, up to about 15k characters).
   - The first uncaught exception hides the remaining inputs.
   - Writing `EOF && cmd` on the terminator line silently writes the junk into the file, runs nothing and returns exit 0 (verified).
   - Replace the step 3 sentence with: "In one run_command, write /tmp/r.py with cat and a quoted heredoc, put EOF alone on its line, and run timeout 30 python3 /tmp/r.py on the next line. Wrap each input in try/except and print repr of the result or the exception. Exit code 124 means a hang. Use at most two calls on the reproducer before the first edit."

8. **Anchors.** A one-line anchor often fails with "occurs N times" and still costs a call. A copied `cat -n` number prefix matches none of the edit_file strategies (exact, flexible, regex, unescaped).
   - Replace: "old_string is one to three plain code lines copied from what you read"
   - With: "old_string is two or three plain code lines that occur once in the file, copied without the cat -n line numbers".

**What the design missed**

- **Run time against the 12 h cap.** v28's extra check and review steps raised the mean on the same 33 tasks from 217 s (v27) to 275 s. v29 adds a reproducer, pytest, git status/diff and py_compile, so expect a similar rise.
  - The gate's "≤ 200 s" is +10% over v27's 182 s. The team's own rule is base + 5% (about 191 s), plus the p95 projection "15 min + 120 × (mean + 30 s) ≤ 10.5 h". Use those.
  - Add gate metrics for: sessions ended by nudges, by the 80-turn limit and by the 8-minute cap; text-only turns; and the first-edit call taken from the harness count.
- **Calls before the first edit will likely go up, not down.** v29 requires, before any edit: a read of the whole function, reading around hits, comparing siblings, and a reproducer. v27 ignored its own "by call 12" rule in 21 of 46 tasks. C1's estimate of a mean first edit around call 10 has no data behind it; measure it in the lab.
- **pytest may be masked on the scorer.** If `enable_sandbox_testing` is false, a pytest stub prints a "disabled" message and exits 1; the default is true, and lab runs did run pytest. Without the skip clause in edit 3, the prompt would treat that output as a failure.
- **Checked and confirmed safe:** `.git/info/exclude` already covers `__pycache__`, `*.pyc` and `.pytest_cache`, so py_compile and pytest leave nothing in the diff. Each run_command read now holds at most 5,000 characters against read_file's 10,000, so context grows no faster than in v27.

Harness sources checked are under `(scratchpad)/wh31/venv/lib/python3.12/site-packages/`: `swegemma/tools/execution.py`, `swegemma/tools/workspace.py`, `swegemma/sandbox/subprocess.py`, `swegemma/harness/agent_runner.py` and `adk_eval_core/editing/edit.py`. The measurement clones are in `(scratchpad)/mech/`.
**Verdict: ship with edits.** Ship to the paired lab only, not to the leaderboard, and only after the gate fixes below. With the edits applied the prompt is 3,099 bytes (I applied them in memory; no file was written).

## Evidence check, per change (checked against lab12/13 traces and harness source)

**Supported by measurement (keep):**
- **write_file cannot write outside /workspace.** v27 tried write_file to /tmp in 29 of 48 tasks, and every one failed with "Path traversal detected". This is the best-supported change.
- **Pipe every search into head.** Over v27 and v28, bare grep commands failed 156 of 605 times. Grep piped into head failed 0 of 83 times.
- **Switch to a heredoc script on the first missing-parameter error.**
  - Once the model writes new_string with literal backslash-n escapes, the call is corrupted 55 of 67 times in v27 and 115 of 133 in v28t. With real line breaks it is corrupted 2 of 78 in v27 and 0 of 30 in v28t.
  - Heredoc run_command calls succeeded 39 of 44 times. python -c calls failed about 23% of the time in v28.
- **Reproducer via a /tmp heredoc under timeout.** v27 already tries a reproducer in most tasks. Its v28-lost wins (9425, 5624) used reproducers. v28 hit 2 TimeoutExceeded at 240 s; v28t hit 3.
- **Commit as soon as the line is known.** Supported by 4079 (v27) and 14419 (v28 only).
- **Never resend a failed call; comments and docstrings never fix an issue.** Cheap; v28 made docstring-only patches on 3105 and 4079.
- **Read with run_command instead of read_file.** read_file lost its range arguments in 17 of 387 v27 calls; run_command had 0 corrupted arguments. Supported, but see the 150-line problem below.

**Contradicted by the data:**
- **"By call 10".**
  - 10 of v27's 19 real solves made their first edit after call 10: 9425 at 26, 5624 at 19, 3518 at 20, 14372 at 19, 2725 at 18, 9753 at 17, 6644 at 16, 11194 at 15, 3006 at 15, 9555 at 11.
  - The design says the rule "keeps 9425 and 5624". The opposite is true: those were late-edit wins.
  - v28's call plan required an edit by call 12, yet its first edit moved later (mean call 15.3 vs 13.1). Edits never happened in 7 v28 tasks and 13 v28t tasks.
  - The 57% vs 24% resolve rate (first edit by call 8 vs after 12) is confounded by task difficulty.
- **"Up to 150 lines" via run_command.** run_command output is cut at 5,000 characters with no notice (swegemma tools/execution.py). The harness already tells the model this limit. 86% of 150-line `cat -n` windows from the rich and fastapi source exceed 5,000 characters; 80-line windows exceed it 6% of the time.
- **Ban on backslashes in new_string.** The measured trigger is the model writing literal backslash-n escapes. Edits containing backslashes without that garble succeeded 18 of 27 times in v27 and 27 of 28 in v28t. The ban also blocks legitimate code: 15588 needs `"\n" in v`, and 3535 needs a regex class. Triple quotes appear in only a minority of corrupted calls.
- **"py_compile after a shell edit … would have caught 3930".** 3930's SyntaxError came from edit_file, not a shell edit, so the rule would not have fired.
- **Step 6 as a fix for 3470.**
  - After the correct first edit, the visible test_capture_and_record (which expects "ABC\nHello\n") fails.
  - The issue is title-only, so "any other new failure means remove or narrow that edit" pushes toward v27's compensating edit or a revert.
  - On 3043, v27 already ignored the stale tests without this rule.
  - Step 6's net effect is uncertain (+1 on 3180, a risk on 3470 and 3043).

**Unsupported or zero gain (drop to keep the prompt short):**
- **C8 "memory is not evidence".** The design itself estimates zero gain.
- **The per-call state line.** Untested. The harness budget warnings and v28's call plan were both ignored.
- **"A warning to finalize does not mean you have edits".** No trajectory shows that misreading.
- **"Raise the way neighbouring checks do".** It helps only 14258, which is unsolvable, and that task has both an assert and a FastAPIError nearby.
- **"On every branch and parallel path".** No confirmed flip: 4006 also needs every character in a span. Over-editing is what failed v27 on 3180 and 3470, and v28 on 14487.
- **"Read around any hit before dismissing".** Only 14487 (unsolvable) and v28's run on 4079.
- **"Never use sed -i".** One v28 task (3278). v27's only sed -i, on 3535, worked.
- **The splitlines example.** It is rich_4076's gold diff, so a 4076 flip would be leakage, not a gain that transfers to private repos.

## Required edits to v29_system.md (old → new)

1. Remove: "Before every tool call write one short line: call N of 28, diff empty or not, and what this call is for."
2. Replace "If no message is given, write it with the issue's own words for the rule, in the format of nearby messages, and raise the way neighbouring checks do. If the issue is only a title or a link, turn it into a concrete input that fails through the public API." → "If no message is given, build it from the issue's own words for the rule, in the format of nearby messages."
3. Replace "; for a vague symptom also grep the operations that cause it, for example splitlines or strip for lost newlines." → "; for a vague symptom also grep the standard calls that could cause it."
4. Replace "Read with run_command, cat -n file piped to sed -n with a line range, taking the whole suspect function in one call (up to 150 lines). Read the lines around any hit before dismissing it." → "Read with run_command, cat -n file piped to sed -n with a line range, at most 80 lines per call, because command output is cut at 5000 characters without notice."
5. Replace "write one reproducer: run_command with cat > /tmp/r.py and a quoted heredoc, then timeout 30 python3 /tmp/r.py." → "write one reproducer in a single run_command: cat > /tmp/r.py with a quoted heredoc, then timeout 30 python3 /tmp/r.py." This saves one call per task.
6. Replace "By call 10 a source file must be changed; if not, edit your best candidate now. A warning to finalize your edits does not mean you have any. Make the smallest change that fixes the cause, in the direction the issue asks, on every branch and parallel path with the same defect." → "By call 12 a source file must be changed; if not, edit your best candidate now. Make the smallest change that fixes the cause, in the direction the issue asks. After the first edit, rerun the reproducer before changing anything else; if its output is now right, make no further edits."
   - The added sentence is the best-supported rule the design left out. Both 3180 and 3470 had a passing working tree after their first edit and were then broken by a second edit.
7. Replace "old_string is one to three plain code lines copied from what you read. Never put triple quotes, backslashes or backticks in old_string or new_string, and do not write docstrings." → "old_string is one to three code lines copied from what you read, never docstring lines. Write line breaks as real line breaks, never as backslash-n, and never put a backslash before a quote. If the new code itself needs a backslash, use the script below."
8. Remove: " Never use sed -i. After a shell edit run python3 -m py_compile on the file."
9. Replace "with -q -x and tail -20" → "with -q and tail -15". With -x, a stale failure that comes first hides real regressions.
10. Remove: "Only text seen in tool output is evidence, never memory of the project."

## What the design missed (fix before using the gate)

- **fastapi_14851 passes in-kernel with an empty patch** (v27 and v28 both have patch_chars 0 and resolved_kaggle_env true). The real v27 baseline is 19, not 20.
- **rich_4079's local regrade passes no-op patches**, because gold also fails locally and resolved_given_env forgives it. v28's docstring patch and v28t's no-op patch both show as resolved locally. Grade 4079 in-kernel only.
- **The noise estimate is not measured.** Lab 14 (the v27 replicate) has only kernel metadata and no graded results, so "±3" is asserted. A gate of +2 is inside that noise; run lab 14 first.
- **The gains are in-sample.** The rules and examples were fitted to these 48 tasks. goldpass_ids.txt holds 73 gold-passable tasks, 25 of them outside the 48; use those as a holdout in the gate.
- **The corrupted-edit metric is dominated by one task's loop.**
  - In v27, 30 of the 31 key-corrupted edit_file calls are fastapi_14258.
  - In v28t, by the wider count that also includes missing parameters, 60 of 115 are fastapi_14258 and 39 are fastapi_13537.
  - Replace "fewer than 10 corrupted edit calls" with "tasks with 3 or more consecutive identical failing calls".
- **"Mean first-edit call ≤ 10" rewards forced junk edits.** Replace it with: no loss among v27's late-edit wins (9425, 5624, 9753, 14372, 11194, requests_6644, 2725, 3006, 3518).
- **Other count errors in the design:**
  - The "89 CommandErrors read as a broken tool" were misread only in rich_3061.
  - On 14419, v27 did put an edit on disk (in the wrong direction); only v28 "had the right fix in mind" and never edited it.
  - Most of the 14 "maybe" tasks (3934, 3944, 3471, 3472, 3521, 3506) have title-plus-link issues, so the expected +2 to +4 is optimistic.

Files:
- Prompt: (scratchpad)/oct15/v29_system.md
- Lab results: (scratchpad)/lab12a_graded.jsonl, lab12b_graded.jsonl, lab13a_graded.jsonl, lab13b_graded.jsonl (same directory)
- Traces: (scratchpad)/lab12aout/lab/v27/r0/traces/ (and the matching lab12b and lab13 dirs)
- Harness limits: (scratchpad)/wh31/venv/lib/python3.12/site-packages/swegemma/tools/execution.py (5,000-character cap) and tools/workspace.py in the same directory
- Holdout candidates: (scratchpad)/goldpass_ids.txt
