# v29 design: v27 YAML unchanged, new 3.5 KB prompt

The prompt is at `(scratchpad)/oct15/v29_system.md`. It is 3,477 bytes, plain ASCII, with no braces, backticks or code fences.

I built a test bundle from the v27 YAML plus this prompt at `(scratchpad)/oct15/v29lint`, and `lint_bundle.py` passes it. Its 17.2 h worst-case warning is the same as v27 and v28. I have not created `gemma_agent/bundle_v29` in the repo; to build it, copy `bundle_v27` and replace `prompts/system.md` with this file.

## 1. Failure causes, ranked

The 33 failed tasks are the 28 that v27 failed plus the 5 that v27 solved and v28 lost: rich_3043, fastapi_9425, fastapi_5624, fastapi_9753 and rich_3278. Since v29 starts from v27, it first has to keep those 5, then gain among the 28.

| Rank | Primary cause | Count | Tasks | Can a prompt fix it? |
|---|---|---|---|---|
| 1 | needs_info_not_in_issue | 10 | 14487, 15800, 15661, 14479, 3942, 3930, 3061, 3105 (unsolvable); 3535, 3944 (maybe) | **No** for 8: exact strings or APIs the issue never states. Partly for 3535 and 3944. |
| 2 | wrong_semantics | 7 | 3470, 3468, 3506, 14419, 3052, 3471, 3934 | **Yes**, rated maybe or yes: reproduce, check direction, compare siblings, don't explain away leftover wrong output. |
| 3 | never_edited | 6 | 9425 and 5624 (v28 regressions), 3472, 4076; 14306 and 3938 (unsolvable) | **Yes**: commit as soon as the line is known, edit by call 10, a self-kept call/diff line. |
| 4 | wrong_location | 3 | 9753 (v28 regression), 3521, 3772 | **Yes**: read whole functions, use a reproducer, search the issue's own words. |
| 5 | edit_tool_rejections_loop | 2 | 3278 (v28 regression); 14258 (unsolvable) | **Yes**: plain anchors, switch to a script on the first parameter error, no `sed -i`. |
| 6 | contract_mismatch_names_or_messages | 1 | 15588 | **Maybe**: write the message from the issue's own words. |
| 6 | broke_existing_behaviour | 1 | 3180 | **Yes**: a new failure in an unrelated test means remove the extra edit. |
| 6 | incomplete_fix_missed_parallel_or_registration | 1 | 4006 | **Maybe**: fix every branch with the same defect. |
| 6 | ran_out_of_calls_before_finishing | 1 | 4079 | **Yes**: commit as soon as the line is known. |
| 6 | other (stale tests) | 1 | 3043 (v28 regression) | **Yes**: a test asserting the old behaviour is expected to fail. |

What is left to win among v27's 28 failures:
- **Yes (3):** 3180, 4079, 14419.
- **Maybe (14):** 15588, 3535, 3470, 4006, 3468, 3521, 3506, 3472, 3944, 4076, 3052, 3471, 3772, 3934.
- **Unsolvable (11).**

Mechanisms that cut across many tasks:
- Late first edit: 21 of 46 tasks edited after call 12 and resolved about 25%, against about 55% when the first edit came by call 8.
- 31 corrupted edit_file calls (triple quotes, backslashes, `name: Type` text) and 17 corrupted read_file ranges.
- 89 "no match" grep exits shown as CommandError and read as a broken tool.
- Repeated identical calls.
- v27's prompt tells the agent to use /tmp, but write_file refuses /tmp.
- Repro runs with no timeout cost 240 s each in v28 on 14258 and 4006.

**Why v28 lost 5 tasks:**
- Its 40-line reads and searches built on its own guess missed the bug in 5624 and 9753.
- It allowed no reproducer files, so 9425 never confirmed the failure and never edited.
- Its "use the traceback to correct" rule made 3043 revert a correct fix.
- On 3278 it widened the issue's range on its own and corrupted the file with `sed -i`.

## 2. v29 change set

**Config: none.** agent.yaml, sampling.yaml and eval_config.yaml stay byte-identical to v27/v28 (section 4 explains why).

**Prompt: full text (`v29_system.md`)**

> You are fixing one issue in the Python repository at /workspace. A grader applies your git diff to a clean copy and runs hidden tests. Only the diff counts: an empty diff fails, and a correct diff passes even if you never ran a test. Limits: 28 tool calls and 8 minutes. When a limit is reached, the files on disk are graded as they stand.
>
> Before every tool call write one short line: call N of 28, diff empty or not, and what this call is for.
>
> 1. Read the issue. Note every exact name, exception type, message and return value it states; use them character for character. If no message is given, write it with the issue's own words for the rule, in the format of nearby messages, and raise the way neighbouring checks do. If the issue is only a title or a link, turn it into a concrete input that fails through the public API.
>
> 2. Find the code. Use git grep -n for identifiers from the issue; for a vague symptom also grep the operations that cause it, for example splitlines or strip for lost newlines. Pipe every search into head -30. Empty output means no match: never repeat a search. Read with run_command, cat -n file piped to sed -n with a line range, taking the whole suspect function in one call (up to 150 lines). Read the lines around any hit before dismissing it. Compare with sibling functions that do the same job: a step they do and this one skips is a common bug. Do not call search_similar_code, get_code_neighbors or get_code_subgraph.
>
> 3. If the issue shows no error output, write one reproducer: run_command with cat > /tmp/r.py and a quoted heredoc, then timeout 30 python3 /tmp/r.py. Use the public API, several varied inputs and print repr of results. write_file cannot write outside /workspace. Run any repository code under timeout 30.
>
> 4. Edit early. As soon as you can name the line to change, your next call is the edit. By call 10 a source file must be changed; if not, edit your best candidate now. A warning to finalize your edits does not mean you have any. Make the smallest change that fixes the cause, in the direction the issue asks, on every branch and parallel path with the same defect. Comments, docstrings and renames never fix an issue.
>
> 5. Edit with edit_file: old_string is one to three plain code lines copied from what you read. Never put triple quotes, backslashes or backticks in old_string or new_string, and do not write docstrings. If edit_file reports a missing parameter, do not resend it; make the change with run_command python3 - and a quoted heredoc that reads the file, asserts the old text occurs once, replaces it and writes the file. Never use sed -i. After a shell edit run python3 -m py_compile on the file.
>
> 6. Check through the public entry point: rerun the reproducer, then timeout 120 python3 -m pytest on the module's test file with -q -x and tail -20. A test that expects the old behaviour the issue asks to change will fail; never undo your fix for it. Any other new failure means an edit broke something: remove or narrow that edit. If wrong output remains, fix it instead of explaining it away.
>
> 7. Run git status --short and git diff, delete stray files you created, call submit_patch and stop with a one-line summary.
>
> Rules: never create, edit or delete test files. Do not install packages. Never repeat a call you already made. Only text seen in tool output is evidence, never memory of the project. Every issue needs a source change. If get_status shows under 90 seconds left, call submit_patch.

## 3. What each change targets and the expected gain

Gains are lab tasks out of 48, against v27's 20. The lab's run-to-run noise is about ±3, so these are estimates, not measurements.

| # | Change | Targets | Expected gain |
|---|---|---|---|
| C1 | One-line state before each call (call N, diff empty or not); edit as soon as the line is known; edit by call 10, not 12; "a finalize warning does not mean you have edits" | 4079 and 14419 (both had the right fix in mind, never on disk); 3472, 4076; keeps 9425 and 5624 (v27 won those narrowly) | +1 to 1.5; first edit's mean call drops from 13.1 to about 10 |
| C2 | Edit mechanics: 1–3 plain anchor lines, no triple quotes, backslashes or backticks, no docstrings; switch to a heredoc script on the **first** parameter error (v28 waited for two); no `sed -i`; py_compile after shell edits | Saves turns on 15588 (5 failed calls), 3535 (10), 3061, 15800, 14258; keeps 3278; would have caught 3930's syntax error | +0.5; corrupted edits from 31 to under 10; less time lost |
| C3 | Read through run_command (`cat -n` piped to `sed`), one whole function per call; read around a hit before dismissing it | Removes the 17 corrupted read_file ranges (that tool takes 3 arguments, `cat -n` takes 1) and the 150-line head silently returned for whole-file reads; keeps 5624 and 9753; helps 3521 and 3938 | +0.3 |
| C4 | Pipe every search into `head` (exit code 0, so no misleading CommandError); empty output means no match, never repeat; grep the operation behind a vague symptom | The 89 no-match CommandErrors; 3061, 14306 and 4076 (`splitlines`); 3472; repeated greps in 14487, 3938 and 9425 | +0.5, mostly calls saved |
| C5 | For issues with no error output: one reproducer via a /tmp heredoc, public API, varied inputs, `repr` output, `timeout 30`; also fixes v27's /tmp contradiction | 3521 and 3506 (an invariant sweep finds the bug); 3934 (output was not visible); 9425 (the reproducer is how v27 won); 3772, 3468; the 240 s hangs in 4006 and 14258 | +1 |
| C6 | Check rules: stale tests are expected to fail, never revert for them; any other new failure means remove or narrow the extra edit; don't explain away leftover wrong output | 3043 (v28's revert); 3180 (broke 4 existing wrap tests); 3470 (second, compensating edit); 3468 (leftover stderr explained away); 3052 (doubted the result, then rationalised it) | +0.5 to 1 |
| C7 | Meaning: message built from the issue's own words, raised like neighbouring checks; change in the direction the issue asks; fix every branch and parallel path; a step skipped versus sibling functions; comment/docstring/rename edits never count | 15588 ("must be a single line"), 14258 (gets the type right, not the message), 14419 (wrong direction), 4006 (all loop branches), 9753, 3471 (sanitising missing on one path); 3944, 3105 and 3506 (no-op edits) | +0.5 |
| C8 | Only tool output is evidence, never memory of the project | 3942 and 3105 (invented upstream facts); limits damage, flips nothing | 0 |

**Total expected:** about 22–24 of 48 in the lab, roughly +2 to +4 over v27. On the public board that should be about +1 task over the 0.22 recipe.

**Promotion gate:** a paired lab of v27 vs v29 on the same 48 tasks. Promote v29 only if:
- it resolves at least as many as v27 plus 2;
- it loses no more than 2 of v27's 20;
- mean first-edit call is 10 or lower;
- there are fewer than 10 corrupted edit_file calls;
- mean time per task is at most 200 s.

## 4. What I deliberately did not change, and why

- **The YAML** (T 0.2, top_p 0.95, 8192 output tokens, thinking 4096, include_thoughts true, 240 s / 28 calls / 8 min / 80 turns, 9 tools). It is the measured config behind 0.18, 0.22 and v27.
  - include_thoughts false (v28t) gave 16 vs 15, which is noise, with 8 session timeouts.
  - Hangs are handled in the prompt with `timeout 30`. Lowering `timeout_seconds` would only have mattered on 2 tasks, and it risks cutting off slow test files in the private repos.
  - Raising `max_tool_calls` would break the 12 h envelope. The problem is when the first edit happens, not the call cap.
- **Graph tools stay declared but forbidden in the prompt.** Declaring them guards against a crash when they are called, and both measured public recipes do the same.
- **No v28 structure:** no call-phase plan, no batched multi-search, no 40-line reads, no "python -c only when the issue has a snippet", no rule to fix from the traceback, no list of registration points, no FastAPI docs_src rule. Each of these is traced to a specific v28 loss (5624, 9753, 9425, 3043), and the FastAPI rule is tied to one repo. The prompt stays under 3.5 KB because the 7.2 KB version measured worse.
- **No guessing rules for the 11 unsolvable tasks** (exact messages or APIs not in the issue). No rule can produce those strings, and pushing guesses would hurt verbatim-literal tasks like 14479.
- **Task-specific rules dropped to save space:** approximation vs authoritative table (3535), return the canonical choice (3052), exit with status 1 on broken pipe (3468), read CHANGELOG/git log for recent regressions (3944), visited-set for cyclic structures (3772). The generic rules (reproducer with varied inputs, direction check, don't explain away wrong output, every branch) cover part of each.
- **Harness changes are out of the bundle's control:** blocking repeated failing calls, diff-aware budget warnings, reporting grep exit 1 as "ok", unescaping edit_file's new_string. The prompt does what it can instead: C1 replaces diff-aware warnings; C4's pipe into `head` replaces the grep-exit fix.
- **Kept from v27:** the grader framing, "a correct diff passes even untested", verbatim literals, no test edits, "every issue needs a source change", and the 90-second submit rule. The last two now come with the rule that a change must alter runtime behaviour, so the agent cannot satisfy them with a docstring edit (what v28 did on 3105 and 4079).

**Known risks:**
- The reproducer step could push the first edit later. It is limited to issues with no error output, and the call-10 deadline still applies.
- The per-call state line adds about 20 tokens per turn.
- Gemma may miscount calls after context compaction. The harness warnings from call 18 onward give it the true count.