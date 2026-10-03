---
name: swe-tools
description: Installs repository tools into /workspace/.swetools - locate code, show numbered lines, edit line ranges, check a patch with a before/after repro. Run scripts/install.py once at the start.
---
# swe-tools

Run once, first thing: the run_skill_script tool with skill_name swe-tools and file_path scripts/install.py.
It installs these commands, which you run with the run_command tool:

- python3 .swetools/locate.py TERM [TERM ...] : ranks the definitions most relevant to the issue terms.
- python3 .swetools/show.py FILE START [END] : numbered lines. show.py FILE /regex/ prints matching lines.
- python3 .swetools/edit.py FILE START END, then a quoted heredoc with the new lines : replaces lines START..END.
- python3 .swetools/run.py /tmp/script.py : runs a Python script against the repository (never re-runs an unchanged script).
- python3 .swetools/check.py --repro /tmp/repro.py [TEST_FILE ...] : repro before and after your change,
  stray or forbidden files, syntax, imports and the related tests. Ends with a VERDICT.

The .swetools directory is git-excluded, so it never becomes part of the patch.
