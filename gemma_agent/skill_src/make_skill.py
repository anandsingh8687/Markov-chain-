"""Generate the swe_tools ADK skill (SKILL.md + scripts/install.py) into a bundle.

ADK runs skill scripts in a temporary directory, so the skill ships one
script, install.py, that writes the real tools into <repo>/.swetools/ and
git-excludes that directory. The agent then calls the tools with ordinary
run_command calls, which Gemma handles far more reliably than
run_skill_script's nested argument schema.

usage: python gemma_agent/skill_src/make_skill.py BUNDLE_DIR
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent / "swe_tools"

SKILL_MD = """---
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
"""

INSTALL_TEMPLATE = '''"""Install swe_tools into the repository (git-excluded)."""
import os, sys

FILES = __FILES__


def find_ws():
    for cand in (os.environ.get("PWD"), os.environ.get("SWE_WS"), "/workspace"):
        if cand and os.path.isdir(os.path.join(cand, ".git")):
            return cand
    d = os.getcwd()
    while d != "/":
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    sys.exit("error: repository not found")


ws = find_ws()
dest = os.path.join(ws, ".swetools")
os.makedirs(dest, exist_ok=True)
for name, src in FILES.items():
    with open(os.path.join(dest, name), "w") as fh:
        fh.write(src)
excl = os.path.join(ws, ".git", "info", "exclude")
os.makedirs(os.path.dirname(excl), exist_ok=True)
existing = open(excl).read() if os.path.exists(excl) else ""
if ".swetools/" not in existing:
    with open(excl, "a") as fh:
        fh.write("\\n.swetools/\\n")
print("installed .swetools/ in the repository (git-excluded). Use with run_command:")
print("  python3 .swetools/locate.py TERM [TERM ...]      # find the code for the issue")
print("  python3 .swetools/show.py FILE START [END]         # numbered lines")
print("  python3 .swetools/edit.py FILE START END <<'EOF'   # replace lines START..END with the heredoc text")
print("  python3 .swetools/check.py --repro /tmp/repro.py   # before/after repro + tests; VERDICT")
'''


def main():
    bundle = Path(sys.argv[1])
    files = {p.name: p.read_text() for p in sorted((HERE / "tools").glob("*.py"))}
    skill = bundle / "skills" / "swe-tools"
    (skill / "scripts").mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(SKILL_MD)
    (skill / "scripts" / "install.py").write_text(INSTALL_TEMPLATE.replace("__FILES__", repr(files)))
    print("wrote", skill)


if __name__ == "__main__":
    main()
