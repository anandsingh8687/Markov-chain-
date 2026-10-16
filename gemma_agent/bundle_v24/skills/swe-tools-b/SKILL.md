---
name: swe-tools-b
description: Installs attempt B's tools into /tmp/b/t and B's own copy of the repository at /tmp/b/repo. Run scripts/install_b.py once at the start.
---
# swe-tools-b

Run once, first thing: the run_skill_script tool with skill_name swe-tools-b and file_path scripts/install_b.py.
It creates your own copy of the repository at /tmp/b/repo and installs your shell commands under /tmp/b/t/,
which you run with the run_command tool (see your instructions).
