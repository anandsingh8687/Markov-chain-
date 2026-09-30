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
"""

INSTALL_TEMPLATE = '''"""Install swe_tools into the repository (git-excluded)."""
import os, sys

FILES = __FILES__
MAPS = __MAPS__


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
# Fresh guard state for this workspace (views, repro, context count), in case a TMPDIR is reused.
import hashlib, tempfile
_mark = hashlib.sha256(os.path.realpath(ws).encode("utf-8")).hexdigest()[:16]
for _n in (".swetools_state.json", ".swetools_seen"):
    try:
        os.remove(os.path.join(tempfile.gettempdir(), "%s-%s" % (_n, _mark)))
    except OSError:
        pass
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
for name, text in MAPS.items():
    pkg_dirs = {"fastapi": ["fastapi"], "rich": ["rich"], "requests": ["src/requests", "requests"], "httpx": ["httpx"]}[name]
    if any(os.path.isfile(os.path.join(ws, d, "__init__.py")) for d in pkg_dirs):
        with open(os.path.join(dest, "map.txt"), "w") as fh:
            fh.write(text)
        print("REPOSITORY MAP (also saved as .swetools/map.txt):")
        print(text)
        break
print("installed .swetools/ in the repository (git-excluded). Use with run_command:")
print("  python3 .swetools/locate.py TERM [TERM ...]      # find the code for the issue")
print("  python3 .swetools/show.py FILE START [END]         # numbered lines")
print("  python3 .swetools/edit.py FILE START END <<'EOF'   # replace lines START..END with the heredoc text")
print("  python3 .swetools/run.py /tmp/script.py <<'EOF'       # write the script from the heredoc and run it")
print("  python3 .swetools/check.py --repro /tmp/repro.py   # before/after repro + tests; VERDICT")
'''


def main():
    bundle = Path(sys.argv[1])
    files = {p.name: p.read_text() for p in sorted((HERE / "tools").glob("*.py"))}
    skill = bundle / "skills" / "swe-tools"
    (skill / "scripts").mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(SKILL_MD)
    maps_dir = HERE.parent / "maps"
    maps = {p.stem: p.read_text() for p in sorted(maps_dir.glob("*.txt"))} if maps_dir.is_dir() else {}
    if "--no-maps" in sys.argv:
        # The maps were written from the newest commits and mislead on older checkouts (v15/v16 traces).
        maps = {}
    (skill / "scripts" / "install.py").write_text(
        INSTALL_TEMPLATE.replace("__FILES__", repr(files)).replace("__MAPS__", repr(maps)))
    print("wrote", skill)


if __name__ == "__main__":
    main()
