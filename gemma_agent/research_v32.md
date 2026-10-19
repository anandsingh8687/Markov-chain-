I've written the v32 prompt: 4,796 bytes, with no braces, backticks or code fences. It starts from v30's prompt and leaves v30's YAML unchanged. Nothing has been run on it yet, so every effect and cost figure below is an estimate from the 21 analyses and needs a lab check.

File: (scratchpad)/oct15/v32_system.md

## Excluded before designing
Six of the 21 failures cannot be fixed with a prompt rule, so no rule was built for them.
- **Information not in the issue:** MEDS-242, setuptools-4985, cryptography-12673, twyn-317.
- **Lab test environment:** pyqasm-155 (the required message is also unguessable) and pdm-3759 (a test that needs the network).

The recommendation is to tag these in the eval set and drop them from failure mining. That leaves 15 tasks the rules can reach.

## Changes (v30 to v32), with the tasks each targets

**A. Fewer empty patches**
1. **Edit first when the fix is already known.** Step 3 now opens with: "If you can already write the fix, edit first; the reproducer then checks it." The reproducer is still written when no fix is known yet, which keeps the 11/23 benefit of reproducing first. Targets: montepy-882 (v29 had the exact fix by call 11, then lost it to compaction), pyomo v30, cyclopts v30.
2. **Treat reproducer errors the issue doesn't describe as script mistakes.** An import error, missing attribute or wrong arguments means the script is misusing the API. Fix it once from a call in a test, or drop it. Never read library code to explain it, and never change repo files to make it run. Targets: cyclopts-633 (8 calls lost), pyqasm-168 v29 (15 calls lost, plus stub files written into the repo), jsonargparse, pyflakes v29, pint-pandas, lektor v29, twyn v29 (overwrote real data files).
3. **Recover cleanly after compaction.** If earlier outputs became a summary, the summary describes the model's own work and its edits are already on disk: run git diff, read the function once, then edit. This applies to all 13 empty runs, where compaction always came before any edit. Targets: montepy v29, pyqasm-155, pyflakes v30, lektor v29 (read the summary as "the previous AI fixed it"), setuptools v30.
4. **Reads.** Read only through run_command (read_file arguments get garbled), in 40-80 line ranges starting at the function's def line. Targets: garbled read_file calls in pyomo, setuptools, plopp, MEDS and pyqasm-168 (11/188 v30 reads); tiny reads in smart_open, cyclopts and jsonargparse (the last missed the needed line by one).
5. **First search uses -i, plus a definitions grep for vague issues.** All greps are case-insensitive. When the issue names no identifier, the first batch also greps for definitions matching rare title words. Targets: cyclopts, lektor, pyflakes v29 (missed `def GLOBAL`), twyn.
6. **Budget warning applies whether or not an edit exists.** The rule is now "stop reading; make every planned change". Target: pyqasm-155 v30.

**B. Semantic correctness once the file is found**

7. **Check every site the case reaches.** This replaces v30's trace-the-value rule. Before editing, git grep -w the attribute or helper the case uses, to see its other definitions (subclasses, backends) and every line that sets or checks it. The fix must hold for every value those definitions return, None included. If the issue says something should also work somewhere, give it the same state and handling, not a guard that skips it. Targets: plopp-445, pyflakes-836, pyqasm-155 (multi-site), pyomo (the bare-name grep).
8. **Reproducer content.** Start with the issue's example exactly as written, adding no argument or key it lacks. Then loop over variants: each method or mode, boundary values, and several values in one call. Targets: bigquery-2218 (v29 added a "role" key itself and hid the bug), pint-pandas-287, jsonargparse-839, cyclopts.
9. **Check output against the issue's wording, then stop.** The issue is the spec, not the current code. The fix is done once the output matches the issue's words in form and place (key or value, type, raised or returned). After that, go to the test step and edit nothing more unless a test fails; undo any edit that turns a right output wrong or breaks a passing test. Targets: click-2935 (both runs broke a passing fix), pysmt-812, pyflakes v30, bigquery v29, plus the earlier cases 3180, 3470 and 14487.
10. **Find tests by content as well as filename.** One call lists files matching the module name and files that mention the changed function (grep -l). Skip pytest only if both lists are empty. Targets: plopp v30 (skipped pytest because no filename matched), pyflakes v30, click v29.
11. **Judge each failing test by its input.** This replaces v30's blanket "a test expecting old behaviour will fail; keep your fix". Keep the fix only if the issue states the new result for that test's input; otherwise change the code. Never edit tests, even if the issue asks. Targets: canvasapi-716 (v29 rewrote a test), pysmt v30 (dismissed the test that pinned the issue's own input).
12. **Features.**
    - Add code beside the closest sibling without rewriting existing code.
    - Give new optional arguments no-op defaults.
    - Register the new name wherever a grep of the sibling's name shows it imported or listed.
    - Targets: pyjanitor-1451 (v30 was missing only `=None`), cryptography v30 (looked for registration in the wrong file), cryptography v29 (a refactor corrupted the file).
13. **Edit mechanics.**
    - old_string is one to three lines from the latest output; to insert, anchor on the next def line and repeat it.
    - Never retype a whole function.
    - The backslash-before-quote rule now covers write_file too.
    - Any command that writes a .py file ends with py_compile.
    - Targets: smart_open, canvasapi v30, pyqasm-155 v29, pdm v30 (an indentation break), pyjanitor (both runs).

**Removed from v30** to make room: "Run code instead of tracing it by hand", "If a read is cut off, read on from the last line", "If no test file matches, skip", "narrow it", the long trace-the-value sentence, and some wording.

## Expected effect
- **Most likely to flip:** click-2935, plopp-445 (v30's failure), pyjanitor-1451 and cyclopts-633.
- **Possible:** pysmt, pyflakes, jsonargparse, lektor, pint-pandas, smart_open.
- **Made more reliable (these split between v29 and v30):** montepy, canvasapi, bigquery, pyqasm-168.
- **Unlikely:** pyomo. I cut the clause saying a try must also cover the use of its result, because only one task supports it.
- **On lab 20a:** about +2 to +4 over v30's 12/30, and fewer empties (7 down to roughly 3-4). With n=30 this is within noise, so judge it on split A with McNemar.

## Token and call budget
| Item | Calls per task | Completion tokens |
|---|---|---|
| Tests by content: pytest now runs where v30 skipped | about +0.3 | about +50 |
| Site grep (replaces trace-the-value searches) | about 0 | about 0 |
| git diff after compaction (about 1.1 compactions per task; replaces re-reads, 61% of which follow compaction) | about 0 to -0.5 | lower |
| Edit-first, script-misuse stop, stop-after-fix | -0.5 to -1 (5-15 calls saved in the tasks where they fire) | lower |
| 40-80 line reads, anchor inserts, no read_file | about -0.5 | lower |
| **Net** | **about -0.5 to -1** | **at or below v30** |

- The prompt grows by 139 bytes (about 35 cached tokens). Lab 17 measured no time cost for prompt length.
- The rules that save calls are the kind Gemma has followed poorly before, so the lab must check:
  - mean calls and completion tokens at or below v30;
  - compactions per task no more than v30 + 0.1;
  - the first-edit call comes earlier;
  - the empty-patch count drops;
  - how often pytest now runs.

## Rejected ideas
- **Removing read_file (and the graph tools) from the YAML.** It would stop the garbling with no prompt cost, but if the model still calls a removed tool the ADK most likely raises an exception and the run ends (I didn't verify this). Prompt wording is the safer route; it could be tested as a lab variant later.
- **Wrapping the whole check in try/except** (pyomo only) and **"X as Y" routing** (pysmt only) as separate rules. Both are partly covered by changes 7 and 9.
- **Another budget-warning or call-12 forcing rule.** v30's version was followed in 0 of 7 empty runs, and the edits it would have forced (jsonargparse, pint-pandas, smart_open) were wrong. It was kept short rather than strengthened.
- **"Make the same change at sibling sites"** (click: the twin edit was what broke it). **"Always guard against None"** (fits plopp only). Guessing messages or names (pyqasm-155, cryptography, twyn, setuptools).
- **"Skip the reproducer when the PR lists changes."** In lab 20a, runs that reproduced first solved 11/23 versus 1/7, so only "make each listed source change" was kept.
- **Showing the last frame of each traceback** in the reproducer (pint-pandas): it adds completion tokens and rests on one task. **Rules about xfail tests:** many PRs exist to remove xfail markers.
- **Fixes that belong to the lab, not the prompt:** add the eval repos' build requirements (Cython, setuptools_scm) to the kit wheels; recheck gold patches in the offline sandbox; tag tasks where the asserted text is hidden or the task text is only issue references. With pdm-3759 counted as solved by both, lab 20a becomes v29 12/30 and v30 13/30.
# Reviews
**Verdict: ship with edits.** v32 goes to the lab only, not the leaderboard, until it passes the gate. Most of the rules would carry over to unfamiliar private repos. Three of them, as written, push the model to undo or redo fixes that were already right. Together with three wording problems and some silent removals, they put tasks v30 already solves at risk. The token and call estimate is also too optimistic. A version with every edit below applied is at `(scratchpad)/oct15/v32r_system.md`: 5,274 bytes, no braces or backticks, and every old sentence below was checked to appear exactly once.

## Evidence the design missed
- **Gold patches often change existing tests.** In 8 of the 21 failure tasks, the gold patch rewrites or removes existing test assertions or fixtures: montepy, canvasapi, smart_open, pysmt, setuptools, pyqasm-155, pyqasm-168 and twyn. So the correct fix fails an old test. v30 solved montepy and canvasapi without running pytest, and v29 solved smart_open. v32's "skip only if both lists are empty" makes pytest run on tasks like these, and rule 11 plus the undo sentence then push toward the old behaviour.
- **pysmt is misread.** Gold also fails the test v30 "dismissed": test.patch replaces `assertEqual(..., ":this_is_considered_a_value")` with `assertRaises(StopIteration)`. Following that test could not have fixed pysmt.
- **canvasapi v30 (solved) breaks the misuse rule.** Its reproducer showed `TypeError('Parameter my_feature must be of type Feature.')` and then `AttributeError: 'str' object has no attribute 'name'`, both raised inside `obj_or_str`. The issue describes neither, yet that error is the bug. v32 would class it as API misuse and drop it.
- **Reads lose their truncation warning.** read_file returns up to 150 lines or 10,000 characters and says when it truncated (`swegemma/tools/workspace.py`). run_command cuts at 5,000 characters with no notice (`budget.py`). v32 moves every read to run_command (v30 made 188 read_file calls) and also deletes the "read on from the last line" sentence.
- **Test folders vary.** "The tests folder" doesn't fit `jsonargparse_tests/`, `pysmt/test/`, `pyflakes/test/`, `pint_pandas/testsuite/` or `pyomo/util/tests/`: 5 of 21 tasks.
- **Most runs already hit the call cap.** 14 of 21 v30 failure runs (16 of 21 for v29) used 27 or more calls. A call "saved" there is spent on something else, not saved. Each mandatory addition (the site grep, git diff after every compaction, more pytest runs at up to 60 s each) takes a call away from the edit. The longer reproducer loop over variants is missing from the token table. Expect tokens and time at or above v30, not below.

## Required edits (old -> new)
1. "If an edit turns a right output wrong or breaks a passing test, undo it." -> "If an edit turns a right reproducer output wrong, undo that edit."
   - The unconditional undo can leave an empty diff on exactly the 8 tasks above.
2. "For each new failure, check its input: keep your fix only if the issue states the new result for that input; else change your code until it passes." -> "For each new failure, compare its assertion with the issue: if the issue's new behaviour explains the changed result, keep your fix, as hidden tests replace outdated ones; if it checks something the issue does not touch, narrow your edit and rerun once."
   - The old wording defaults to the outdated test, and "until it passes" is an open-ended loop that contradicts "at most twice".
   - The new wording keeps canvasapi's string-input fix and still catches v29's AttributeError-to-TypeError over-edit.
3. "run git diff, read the function to change once, then edit." -> "run git diff; if a planned change is missing, read that function once and make it, else continue from the step the summary reached."
   - At about 1.1 compactions per task, many come after an edit (lektor v29 edited first). An unconditional "then edit" reworks finished fixes, which is click's failure mode.
4. "(key or value, type, raised or returned), the fix is done:" -> "(key or value, type, raised or returned) and each listed change is made, the fix is done:"
   - Without this, it contradicts step 1 and stops multi-site fixes such as pyqasm-155 early.
5. "An error the issue does not describe (import error, missing attribute, wrong arguments) means misuse of the API:" -> "An error the issue does not describe, raised outside the code the issue names (import error, setup, your own call's arguments), means misuse or setup:"
   - This still covers cyclopts, pyqasm-168 and twyn, and stops canvasapi's real bug being dropped.
6. "Before editing, git grep -n -w the attribute or helper the case uses, to see" -> "Before editing, in the same run_command as your next read, git grep -n -w the attribute or helper the case uses in the package into head -20, to see"
   - Without a cap, a common attribute name fills the 5,000-character output and brings compaction forward. On its own it also costs one extra call per task.
7. "for every value those definitions return, None included;" -> "for every value those definitions return;"
   - "None included" brings back the "always guard against None" rule the design rejected as plopp-only, and invites guards at every site.
8. "git grep -l -F of the changed function's name in the tests folder, each into head -10." -> "git grep -l -F the changed function's name -- '*test*', each into head -10."
9. "output is cut at 5000 characters silently." -> "output is cut at 5000 characters silently, so if a read stops before its last line, read on from the last line shown."
10. "Any command that writes a .py file ends with python3 -m py_compile on it." -> "A shell command that writes a repo .py file ends with python3 -m py_compile on it."
    - As written, it covers the reproducer heredoc and invites a separate compile call after each edit_file. pdm's break came from a `python3 -c` script, which the new wording still covers.
11. "If you can already write the fix, edit first; the reproducer then checks it. Else, if the issue shows no error output," -> "If the issue states the change to make, edit first, then check it with the reproducer below. If the issue shows no error output,"
    - Gemma will rate itself able to write the fix on most tasks, which moves runs out of the reproduce-first group (11/23 versus 1/7 in lab 20a).
    - "Else" also makes the reproducer look optional in the edit-first branch.

## Recommended edits (silent removals worth restoring)
These v30 sentences were dropped but are not in the design's "Removed" list.
- "call submit_patch once, then reply in one line." -> "call submit_patch once, then reply in one line with no tool call."
- "set PYTHONPATH to the folder holding the package." -> "set PYTHONPATH to the folder holding the package (for a src layout, /workspace/src)."
  - 8 of the 21 tasks use a src layout.
- "Make the smallest change asked for, then rerun the reproducer." -> "Make the smallest change asked for (comments or docstrings alone never fix it), then rerun the reproducer."
  - This was a measured rule: v28 made docstring-only patches on 3105 and 4079.

## Optional edits (not applied in v32r)
- "git grep -n -i -F per distinctive string" -> "git grep -n -F per distinctive string (add -i for plain words)". Case-insensitive search on short class names floods head -10.
- "'def [a-z_]*WORD'" -> "'(def|class) [a-z_]*WORD'".
- "(each method or mode, boundary values, several values in one call)" -> "(each method or mode the issue names, several values in one call)". This saves tokens and avoids fixes outside the issue's scope.

## Rules that look general enough
- Reading only through run_command, once the continuation sentence is back.
- "Never change repo files to make it run."
- Stopping once the output matches the issue (the click lesson).
- Finding tests by content.
- The feature rules: sibling placement, no-op defaults, registration.
- "Never retype a whole function."
- The short budget_warning wording.

## Lab gate additions
Run the gate on all 30 tasks and pair against v30's solved tasks.
- Mean completion tokens and predicted time must be at or below v30.
- Count runs whose diff shrinks after a pytest call.
- Count edits made after compaction when the diff was already non-empty.
- Count empty patches caused by an undo.
- Check montepy, canvasapi, bigquery and smart_open specifically for regressions.
**Verdict: ship with edits.** Send v32 to the lab, not to Kaggle. As written, v32 most likely uses more calls and tokens than v30, not fewer. My central estimate is about +0.4 calls and +200 completion tokens per task, roughly +2–3% time, with a range from −300 to +900 tokens. The top of that range reaches the 12 h limit. Six edits remove the main added costs and bring the estimate to about −0.3 calls and −150 tokens per task.

**What the v30 traces show** (lab 20a, all 30 tasks; v30 averages 8,700 completion tokens, 26.8 LLM calls, 1.57 compactions and 312 virtual seconds per task):

| Phase | Steps per task | Tokens per step | Share of all tokens |
|---|---|---|---|
| Reproducer writes | 3.63 | 764 | 32% |
| Searches | 7.1 | 263 | 21% |
| Reads (8.1 read_file + 0.7 cat) | 8.8 | 176 / 344 | 19% |
| Edits | 2.5 | 514 | 15% |
| Test find + pytest | 1.14 | about 140 | 2% |

- **Reproducers:** 18 of 30 tasks wrote more than the "at most twice" limit allows. 16 rewrites came straight after an import, attribute or type error.
- **Message text:** it is about 68% of completion tokens. In practice the thinking is the visible text, so the "few short lines" rule is the only length limit.
- **Compactions:** the design says about 1.1 per task; the measured figure is 1.57 (47 in 30 tasks). They are triggered by prompt size, not call count: all 47 fired at 14.3k–18.0k prompt tokens.
  - 26 of the 47 came after the first edit, and 21 of those still had at least 3 calls left. That covers 11 of the 12 solved tasks.
  - After those compactions v30 went on to test or finish; it did not re-read.
  - Only 29 of 85 re-reads came within 4 steps of a compaction.
- **Capped tasks** (27–28 calls) cost 9,230 tokens and 325 s each. The hidden set is harder (17% solved versus 37% here), so more of its tasks will be capped. That makes tokens per step and compactions matter more there than call savings.
- **Margin:** with v29 at about 97% of 12 h, v30 sits at roughly 88–93%.

**Effect of each rule** (estimated per task, at the compliance Gemma has shown before):
- **Compaction rule as written:** +0.5 to +1.0 calls, +100 to +250 tokens. After a fix it adds git diff, a read and an edit, which is also how click-2935 broke a passing fix.
- **Unconditional test listing:** +0.35 to +0.6 calls, +100 to +150 tokens (the design says +0.3 and +50). 7 of the 13 v30 tasks that ran pytest never needed a find call.
- **Site grep before editing:** +0.2 to +0.5 calls, +65 to +150 tokens, about +0.05 compactions. It is a separate call before every edit and has no head limit. v30 used -w in 0 of 200 greps, so it replaces nothing.
- **py_compile, if Gemma applies it to edit_file:** up to +1.4 calls. v30 averaged 1.43 successful edit_file calls per task.
- **Reproducer variant loop:** 0 to +300 tokens.
- **Weaker thought limit and the dropped "run instead of trace" line:** 0 to +275 tokens.
- **Savings:** stop-after-fix gives −0.3 to −0.8 calls and −150 to −400 tokens (click alone spent 11.6k tokens after its first edit). The misuse stop gives −0.1 to −0.3 calls and −100 to −250 tokens.
- **The asymmetry:** the savings rest on "stop" rules Gemma has ignored before. v30's tracked recipes were mostly ignored too: read_file 244 times versus 21 cat reads, batched greps 26/200, reproducer cap broken in 18/30 tasks. Of the new costs, the post-fix compaction rule and the test listing tell Gemma to do something extra, and those cost calls even under v30-level compliance.

**Required edits (old → new):**
1. "If earlier outputs became a summary, it describes your own work, its edits on disk: run git diff, read the function to change once, then edit." → "If earlier outputs became a summary, it describes your own work: put git diff in your next run_command; if it shows no source change, read the function to change once, then edit; otherwise carry on with the step you were on."
2. "In one run_command: git ls-files | grep for the module name, and git grep -l -F of the changed function's name in the tests folder, each into head -10." → "If no test file path has been shown yet, in one run_command: git ls-files | grep for the module name, and git grep -l -F of the changed function's name in the tests folder, each into head -10."
3. "Before editing, git grep -n -w the attribute or helper the case uses, to see its other definitions (subclasses, backends) and each line setting or checking it." → "Before editing, git grep -n -w the attribute or helper the case uses into head -20, batched with your last read, to see its other definitions (subclasses, backends) and each line setting or checking it."
4. "Keep thoughts short: what the output showed, which call is next." → "Keep thoughts to a few short lines: what the output showed, which call is next."
5. "then loop over variants of the named operation (each method or mode, boundary values, several values in one call), printing repr of each result or exception." → "then loop over a few variants of the named operation (another method or mode, a boundary value, several values in one call), printing repr of each result or exception."
6. "Any command that writes a .py file ends with python3 -m py_compile on it." → "A run_command that edits a repo .py file ends with python3 -m py_compile on it; after edit_file, the reproducer rerun is the check." The pdm indentation break came through edit_file, and the reproducer's import caught it.

**Optional (cheap; prompt length has no measured cost):**
- **write_file and /tmp:** "In edit_file and write_file use real line breaks, never backslash-n, and no backslash before a quote." → "In edit_file and write_file (which cannot write to /tmp) use real line breaks, never backslash-n, and no backslash before a quote." The v30 sentence about this was dropped while write_file is now named.
- **Stop after submitting:** "call submit_patch once, then reply in one line." → "call submit_patch once, then reply in one line with no further tool call."
- **Bound the test-fix loop:** "else change your code until it passes." → "else change your code once and rerun."

**Lab checks on time:**
- Mean completion tokens: at most 8,700 per task overall, at most 9,230 on capped tasks, and at most 325 per LLM call.
- Compactions: at most 1.67 per task.
- Count:
  - edits made after a compaction that follows a fix;
  - standalone py_compile calls;
  - test-find calls in tasks where the test path was already shown.

Analysis scripts and per-step data are in `(scratchpad)/v32time/` (`phase.py`, `split.py`, `v30_steps.json`, `v29_steps.json`). The source traces are in `(scratchpad)/lab20aout/lab/`.
**Verdict: ship with edits.** v32 is fit for the next lab run once the 10 required edits below are made. It should not be submitted until that lab passes. The patched prompt is 5,385 bytes, with no braces or backticks; all 10 edits apply cleanly to a copy.

Evidence comes from the full lab 20a traces, `(scratchpad)/lab20aout/lab/v{29,30}/r0`: 60 runs, plus their call logs. I detected compaction where prompt tokens dropped between calls.

**Required edits (old -> new)**

R1. **Compaction rule fires after the edit, which contradicts "edit nothing more".** In 36 of 60 runs a compaction came after the first successful edit, including 10 of v30's 12 solved runs: mahjong, bigquery, montepy, django-bird, meltano, smart_open-892, libpysal, sunpy, fawltydeps, canvasapi. The design assumed compaction comes before any edit, which holds only for empty runs. As written, the rule orders "read, then edit" on fixes that are already done, the click-2935 failure, and adds about 2 calls. Models also don't recognise the summary: lektor v29 and pyflakes v30 took it for "the Context" or "the previous AI".
- Old: "If earlier outputs became a summary, it describes your own work, its edits on disk: run git diff, read the function to change once, then edit."
- New: "Text that speaks of the AI or the conversation is a summary of your own earlier steps, and its edits are on disk: run git diff; if it shows no change, read the function to change once, then edit; else go on from the step you were on."

R2. **Edit-first contradicts "if nothing fails".** On the edit-first path the reproducer runs on fixed code, so "nothing fails" is the success signal. pyflakes v30 took a passing reproducer to mean the bug was "already fixed".
- Old: "if nothing fails, your inputs missed the case."
- New: "if nothing fails before any edit, your inputs missed the case."

R3. **The misuse rule marks real bugs as misuse.** A reproducer is only written when the issue shows no error, so every error is one "the issue does not describe". The real bugs in these runs were TypeErrors raised inside the package: click "sequence item 0: expected str instance, NoneType found", pint-pandas "numpy.float64 has no len()", bigquery "unhashable type: 'dict'". The real misuse cases were raised on the script's own line or on import: cyclopts "app.help()", pyqasm-168 "No module named pyqasm._version".
- Old: "An error the issue does not describe (import error, missing attribute, wrong arguments) means misuse of the API: fix it once from a call in a test, or drop it; never read code to explain it or change repo files to make it run."
- New: "An import error, or an error naming an attribute or argument your own script wrote, means misuse of the API: fix it once from a call in a test, or drop it; never read code to explain it or change repo files to make it run. Other errors raised inside the package may be the bug."

R4 and R5. **Stop-after-fix contradicts multi-site changes, and "undo" is unsafe.** "Edit nothing more" blocks the changes the issue lists, other sites (pyqasm-155) and registration (pyjanitor) once the first output matches. "Undo it" invites `git checkout`, which wipes the whole file; earlier traces include `git checkout -f` and `git checkout rich/console.py`.
- Old: "the fix is done: go to step 6 and edit nothing more unless a test fails. If an edit turns a right output wrong or breaks a passing test, undo it."
- New: "the fix is done: make any planned change still missing (a listed change, another site, a registration), then go to step 6 and edit nothing more unless a test fails. If an edit turns a right output wrong or breaks a passing test, undo that edit with edit_file, never with git checkout, restore or stash."

R6. **Test-failure rule.** The issue in canvasapi-716 says "update tests accordingly", and the old test fails after a correct fix, so the literal rule reverts the fix. "Until it passes" also contradicts "at most twice".
- Old: "keep your fix only if the issue states the new result for that input; else change your code until it passes."
- New: "keep your fix if the issue states the new result for that input or says tests are updated; else change your code once and rerun."

R7. **The edit fallback lost "quoted" and "raw strings".** It exists for code that needs backslashes. 216 of 218 heredocs in lab 20a were unquoted (`<<EOF`) even though the prompt said "quoted heredoc". In meltano, `$ref` expanded to nothing. pdm v30 used `python3 -c '...'` and hit a bash syntax error.
- Old: "do not resend: run a python3 heredoc script that asserts the old text occurs once and replaces it."
- New: "do not resend: in one run_command run python3 - <<'EOF' (quotes included, never python3 -c) with a script that asserts the old text occurs once and replaces it using raw strings."

R8. **The -w grep has no limit.** A bare git grep with no match exits 1 and shows as a CommandError (cyclopts shows several). Greps without head hit the 5000-character cut in v30: alias, obj_or_id, Ensure.
- Old: "Before editing, git grep -n -w the attribute or helper the case uses, to see"
- New: "Before editing, git grep -n -w the attribute or helper your fix touches in the package into head -20, to see"

R9. **The pyjanitor rule doesn't fire on its own target.** v30 treated `new_name` as required, not "optional".
- Old: "give new optional arguments no-op defaults,"
- New: "give each new parameter after the first a default that changes nothing (often None),"

R10. **Anchoring on the next def puts new code between a decorator and its def.** Every pyjanitor function has `@pf.register_*`, and pdm v30 broke indentation around `@staticmethod`. "Never retype a whole function" also blocks how v30 actually solved montepy: one 35-line old_string. 26 of 43 successful v30 edits had 4 or more lines, with the same error rate as short ones.
- Old: "to insert, anchor on one such line (say, the next def) and repeat it in new_string. Never retype a whole function."
- New: "to insert, anchor on the first line of the next block (its decorator if it has one, else its def) and repeat it in new_string. Never retype lines from memory."

R11. **Restore the cut-recovery clause.** All reads move to run_command, but 91 of 227 v30 read_file calls returned more than 80 lines (up to 150), and 4 of 21 v30 run_command reads were cut.
- Old: "output is cut at 5000 characters silently."
- New: "output is cut at 5000 characters silently; if a read ends before its last line, read on from there."

**Recommended edits**
- O1. "cat into /tmp/r.py with a quoted heredoc, EOF alone on its line" -> "cat > /tmp/r.py <<'EOF' (quotes included), EOF alone on its line"
- O2. "git grep -l -F of the changed function's name in the tests folder" -> "git grep -l -F of the changed function's name -- '*test*'". Tests sit inside the package in pyomo/util/tests, pint_pandas/testsuite and sunpy; I checked that the pattern matches nested paths.
- O3. "Any command that writes a .py file ends with python3 -m py_compile on it." -> "Any run_command that changes a repo .py file ends with python3 -m py_compile on it." The current wording also catches /tmp/r.py and is unclear for edit_file.
- O4. "git grep -n -i -F per distinctive string in the package" -> "git grep -n -F per distinctive string in the package", keeping -i only in the definitions grep. In v30, 22 of 39 greps with head -10 already filled all 10 lines. Grep lines average 91 characters, so five full greps come to about 4,600 characters, and the definitions grep, last in the batch, is the first thing the cut drops.
- O5. Restore "(for a src layout, /workspace/src)" after "set PYTHONPATH to the folder holding the package".
- O6. "several values in one call" -> "several values in one API call"

**Corrections to the design's numbers**
- **Compactions:** 1.57 per task in lab 20a, not 1.1, at about 25 virtual seconds each. With R1, git diff costs about one call per compaction.
- **Pytest time:** each run takes 11.3 s on average (median 1.4, max 73). The +0.3 runs per task costs about 3 to 4 s of wall time per task, which is not counted in the table.
- **Reads:** capping reads at 80 lines may need more read calls, not 0.5 fewer.
- **"None included" (rule 7):** this is in effect the "always guard against None" idea the design rejected. Either keep it and drop that rejection, or remove it. It is not a required edit.
- **If v32r's batching is merged:** a -w grep with head -20 (about 1,800 characters) plus an 80-line read (about 3,300 characters at the median) is roughly 5,100 characters and will be cut. Use head -10 or a 60-line read when batching them.

**Rules the lab must track:** "By call 12" and "at budget_warning stop reading" are not enforceable by prompt. In 11 of 60 runs an edit_file was refused with "Tool call budget exhausted": v29 montepy, MEDS, jsonargparse, pyflakes, pysmt, pyqasm-168; v30 cyclopts, lektor, jsonargparse, pyomo, setuptools. Add that count, heredoc quoting, git checkout use and post-compaction edits to the lab metrics.

The edited prompt is at `(scratchpad)/rv32m/v32_mech.md`, and the script that applies the edits is `(scratchpad)/rv32m/apply.py`.
