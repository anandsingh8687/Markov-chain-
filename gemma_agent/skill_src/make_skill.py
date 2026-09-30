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
- python3 .swetools/run.py /tmp/script.py : runs a Python script against the repository (15 s limit; never re-runs an unchanged script).
- python3 .swetools/status.py : where the work stands (patch, repro, last verdict, time) and the next step.
- python3 .swetools/check.py --repro /tmp/repro.py [TEST_FILE ...] : repro before and after your change,
  stray or forbidden files, syntax, imports and the related tests. Ends with a VERDICT.

The .swetools directory is git-excluded, so it never becomes part of the patch.
"""

# The install logic runs from a string (BODY) so that it can write an identical copy of the whole installer
# to .swetools/install.py (a re-run shim for the model).
INSTALL_BODY = r"""
import os, sys, time, json, hashlib, tempfile, subprocess


def find_ws():
    for cand in (os.environ.get("PWD"), os.environ.get("SWE_WS"), os.getcwd(), "/workspace"):
        if cand and os.path.exists(os.path.join(cand, ".git")):
            return cand
    d = os.getcwd()
    while d != "/":
        if os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    sys.exit("error: repository not found")


def git(ws, *args):
    try:
        r = subprocess.run(["git"] + list(args), cwd=ws, capture_output=True, text=True, timeout=20,
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def write_atomic(path, text, mode=None):
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w") as fh:
        fh.write(text)
    if mode:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


ws = find_ws()
dest = os.path.join(ws, ".swetools")
_mark = hashlib.sha256(os.path.realpath(ws).encode("utf-8")).hexdigest()[:16]
tmpd = tempfile.gettempdir()
swe = os.path.join(tmpd, ".swe", _mark)
os.makedirs(swe, exist_ok=True)
# Guard state (views, repro, rewrites, verdict) belongs to one session: reset it only for a new baseline.
run_id = git(ws, "rev-parse", "-q", "--verify", "_swegemma_baseline^{commit}") or git(ws, "rev-parse", "HEAD")
id_path = os.path.join(swe, "run_id")
try:
    old_id = open(id_path).read().strip()
except OSError:
    old_id = None
if old_id != run_id:
    for _n in (".swetools_state.json", ".swetools_seen"):
        try:
            os.remove(os.path.join(tmpd, "%s-%s" % (_n, _mark)))
        except OSError:
            pass
    write_atomic(id_path, run_id)
    write_atomic(os.path.join(swe, "t0"), "%.0f" % time.time())
else:
    try:
        age = time.time() - float(open(os.path.join(swe, "t0")).read())
    except (OSError, ValueError):
        age = 10 ** 9
    if age > 1200:
        write_atomic(os.path.join(swe, "t0"), "%.0f" % time.time())
os.makedirs(dest, exist_ok=True)
for name, src in FILES.items():
    write_atomic(os.path.join(dest, name), src)
# Shims for commands Gemma sometimes writes: `.swetools/run_command CMD` and `python3 .swetools/install.py`.
write_atomic(os.path.join(dest, "run_command"), SHIM, 0o755)
write_atomic(os.path.join(dest, "install.py"),
             "FILES = %r\nMAPS = %r\nSHIM = %r\nBODY = %r\nexec(BODY)\n" % (FILES, MAPS, SHIM, BODY))
excl = os.path.join(ws, ".git", "info", "exclude")
try:
    os.makedirs(os.path.dirname(excl), exist_ok=True)
    existing = open(excl).read() if os.path.exists(excl) else ""
    if ".swetools/" not in existing:
        with open(excl, "a") as fh:
            fh.write("\n.swetools/\n")
except OSError:
    pass
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
print("  python3 .swetools/run.py /tmp/script.py <<'EOF'       # write the script from the heredoc and run it (15 s limit)")
print("  python3 .swetools/check.py --repro /tmp/repro.py   # before/after repro + tests; VERDICT")
print("  python3 .swetools/status.py                        # where your work stands and the next step")
print("Every tool output starts with a state line: [T+time/300 | patch | repro before->now | check | rewrites].")
src = os.path.join(ws, "src")
if os.path.isdir(src) and any(os.path.isfile(os.path.join(src, d, "__init__.py")) for d in os.listdir(src)):
    print("NOTE: src/ layout. The tools import the code from src/; a plain python3 command may import an installed "
          "copy instead, so run scripts with run.py.")
"""

SHIM = r"""#!/usr/bin/env python3
# Runs its argument as a shell command (for calls written as `.swetools/run_command CMD`).
import json, os, subprocess, sys
text = " ".join(sys.argv[1:]).strip()
if text.startswith("{"):
    try:
        text = json.loads(text).get("command", text)
    except Exception:
        text = text.strip("{} ")
        for key in ('"command":', "command:", "'command':"):
            if text.startswith(key):
                text = text[len(key):].strip().strip('"').strip("'")
if text.startswith("command="):
    text = text[len("command="):]
if not text:
    sys.exit("usage: .swetools/run_command 'shell command' (better: call the run_command tool directly)")
sys.exit(subprocess.call(["/bin/bash", "-c", text]))
"""

INSTALL_TEMPLATE = '''"""Install swe_tools into the repository (git-excluded)."""
FILES = __FILES__
MAPS = __MAPS__
SHIM = __SHIM__
BODY = __BODY__
exec(BODY)
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
        INSTALL_TEMPLATE.replace("__FILES__", repr(files)).replace("__MAPS__", repr(maps))
        .replace("__SHIM__", repr(SHIM)).replace("__BODY__", repr(INSTALL_BODY)))
    print("wrote", skill)


if __name__ == "__main__":
    main()
