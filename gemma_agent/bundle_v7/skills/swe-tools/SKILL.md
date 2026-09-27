---
name: swe-tools
description: Installs fast repository tools into /workspace/.swetools (locate relevant code, check a patch). Run scripts/install.py once at the start.
---
# swe-tools

Run once, first thing: `run_skill_script(skill_name="swe-tools", file_path="scripts/install.py")`.
It installs two tools you then call with `run_command`:

- `python3 .swetools/locate.py TERM [TERM ...]` - ranks the definitions most relevant to the
  issue's identifiers, messages and phrases, shows exact text hits and the test files for that code.
- `python3 .swetools/check.py [TEST_FILE ...]` - checks the patch: stray/forbidden files, syntax,
  imports, runs the related tests and tells which failures your change caused. Ends with a VERDICT.

The .swetools directory is git-excluded, so it never becomes part of the patch.
