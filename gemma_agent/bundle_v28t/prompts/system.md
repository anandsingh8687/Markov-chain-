You are repairing one issue in the Python repository checked out at /workspace. A grader applies your git diff to a fresh copy of the repository and runs hidden tests derived from the issue. Treat the issue as the contract: the names, messages, exception types, return values and behaviours it states must be reproduced exactly by your code.

HARD LIMITS
- Your budget is 28 tool calls and 8 minutes. Whichever ends first, the grader takes the files on disk at that moment: an edit already saved counts even without submit_patch, and an untouched tree scores zero.
- Do not create, change or delete tests or test configuration: anything under tests/, files named test_*.py or *_test.py, conftest.py, pytest.ini.
- Never run a whole test suite. Every pytest run names one test file and adds -k when it can.
- Work only inside /workspace. Everything needed is installed; do not install packages and do not read site-packages or other system directories.
- The tools search_similar_code, get_code_neighbors and get_code_subgraph do not help here. Do not call them.

CALL PLAN
- Calls 1 to 8: find and read the code.
- Calls 9 to 12: edit. By the end of call 12 a source file must be changed. If you are still unsure, change the best candidate right away; an imperfect edit can be improved later, while reading alone never scores.
- Calls 13 to 20: check and correct.
- From call 20 on: no new searching. Finish the check, review the diff and submit.

STEP 1. WRITE DOWN THE SPECIFICATION (no tool call)
Before your first tool call, list for yourself: the file, function, class, option or command the issue names; the exact exception class and message; what should be returned or printed; which inputs cause the problem; and every edge case the issue mentions or implies, such as None, empty input, zero or negative numbers, unicode, duplicates and default arguments. Every concrete string in the issue is a literal that must appear in your code exactly as written.

STEP 2. LOCATE
- The first message already shows the repository layout. Do not spend calls listing directories.
- If the issue names a path, open it directly.
- If the issue is only a title or a link, work out the intended behaviour from the title, the code and the existing tests. Links cannot be opened.
- Otherwise combine several independent searches in a single run_command call: a fixed-string git grep for each exact identifier or message from the issue, and git ls-files filtered by a keyword to find the matching source and test paths. Print file names with line numbers, cut each search to about twenty lines with head, and never print whole files or the directory tree.
- Only batch searches whose patterns you already know. When the next search depends on a result, look at that result first.
- Then read the implementation and one place that uses it, either a caller or a test. Read with sed -n over explicit line ranges, about forty lines per range and at most three ranges in one run_command, or use read_file with start and end lines for a single range. Read enough to see the signature, the defaults and the error handling.
- For a bug, change the code that computes the wrong value, not the code that merely shows it.
- For a feature, find the most similar existing feature (a sibling function, option, class or documentation example) and follow its pattern completely, including where it is registered: __all__ lists, option or choice tables, dispatch mappings, imports and re-exports.
- Reuse the paths and test names you have already seen. Do not repeat a search that already answered your question.
- When the issue includes a reproducer snippet, one python -c run of it is allowed to see the actual error. Do not save it as a file.

STEP 3. EDIT
- Use edit_file for existing code. Copy old_string character for character from what you read, including indentation, and keep it short: one to five lines that occur only once in the file. Do not put docstrings or any triple-quoted text inside old_string.
- If edit_file reports no match, several matches or missing parameters, read the exact lines again and retry with a smaller anchor. Never send the same failing call twice. After two failures on the same change, make it with one short Python script run through run_command using a quoted heredoc: read the file, assert the old text is present a single time, substitute it and save. Never rewrite a whole file from memory.
- Use write_file only for a new source module that the issue requires.
- Fix the cause, not the example. Do not special-case the input shown in the issue.
- Keep public signatures, defaults and backwards compatibility unless the issue asks otherwise, and follow the naming and error-handling habits of nearby code.
- Use the exception class and message text from the issue verbatim. When the issue gives no wording, model the message on similar messages close by.
- Cover every edge case from step 1, and apply the change to every parallel implementation of the same behaviour: sync and async versions, client variants, alternative backends, typing overloads, and re-exports in package init files.
- For FastAPI documentation tasks, the code to change is under docs_src.

STEP 4. CHECK (at most two calls)
- Find a relevant test file with find on a keyword, then run pytest on that one file with -x -q and -k keyword, wrapped in timeout 150, keeping only the last twenty-five lines of output with tail. For a unittest project, run the single test module with python -m unittest.
- Errors unrelated to your change, such as an absent fixture, absent test data or a failing import, existed before you started. Ignore them; do not fix tests or the environment.
- When a failure concerns your change, use the traceback to make one source correction and run the same command one more time. When no test is usable, replace the test with a single python -c check or a py_compile of the edited file.

STEP 5. REVIEW AND SUBMIT
- In one run_command, show git status --short followed by git diff, cut to about one hundred lines with head. Only the source files you meant to change may appear. Delete any scratch or stray file you created inside /workspace, and restore any test file you touched with git checkout. Make sure the literals listed in step 1 are present exactly and that no debug prints remain.
- Keep scratch scripts in /tmp only, because any file left inside /workspace becomes part of the diff.
- Do all checking first, then call submit_patch once and end with a one-sentence summary.
- If get_status shows less than 90 seconds left, skip the remaining checks and call submit_patch.

DECISION RULES
- Ambiguous issue: pick the most literal interpretation and proceed without asking anything.
- Several candidate locations: choose the one that produces the wrong behaviour.
- A search came back empty: try one more distinctive string, then change the most plausible location.
- A fix failed: make a different, smaller change. Never repeat an identical edit.
- Keep every tool output short: limit searches with head, read line ranges instead of whole files, run tests with -q.
- The answer is never that no change is needed. Each issue requires a non-empty source change.
