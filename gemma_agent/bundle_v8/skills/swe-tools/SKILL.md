---
name: swe-tools
description: Installs repository tools into /workspace/.swetools (locate code, show numbered lines, edit line ranges, check a patch with a before/after repro). Run scripts/install.py once at the start.
---
# swe-tools

Run once, first thing: `run_skill_script(skill_name="swe-tools", file_path="scripts/install.py")`.
It installs tools you then call with `run_command`:

- `python3 .swetools/locate.py TERM [TERM ...]` - ranks the definitions most relevant to the
  issue's identifiers, messages and phrases, shows exact text hits and the test files for that code.
- `python3 .swetools/show.py FILE START [END]` - numbered lines (`show.py FILE /regex/` for matching lines).
- `python3 .swetools/edit.py FILE START END <<'EOF'` ... `EOF` - replace lines START..END with the heredoc text.
- `python3 .swetools/check.py --repro /tmp/repro.py [TEST_FILE ...]` - runs the repro without and with your
  change, checks stray/forbidden files, syntax, imports and the related tests. Ends with a VERDICT.

The .swetools directory is git-excluded, so it never becomes part of the patch.
