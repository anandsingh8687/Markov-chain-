"""Generate the swe_tools ADK skill (SKILL.md + scripts/install.py) into a bundle.

ADK runs skill scripts in a temporary directory, so the skill ships one
script, install.py, that writes the real tools into <repo>/.swetools/ and
git-excludes that directory. The agent then calls the tools with ordinary
run_command calls, which Gemma handles far more reliably than
run_skill_script's nested argument schema.

usage: python gemma_agent/skill_src/make_skill.py BUNDLE_DIR [--no-maps]
       python gemma_agent/skill_src/make_skill.py BUNDLE_DIR --duo [--budget 300] [--deadline 250]
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


DUO_ONLY = ("_duo.py", "pick_patch.py", "sh.py", "done.py")  # not installed in solo mode (v23 behaviour unchanged)

# ---------------------------------------------------------------- duo mode (bundle_v24)
# Three skills, one per agent, so attempt B can never run attempt A's installer. Every installer installs
# BOTH tool sets (idempotent, under a flock) and prints only its own command table; the finisher's script
# installs too and then runs the picker.

DUO_SKILLS = {
    "a": ("swe-tools-a", "install_a.py",
          "Installs attempt A's repository tools into /workspace/.swetools. Run scripts/install_a.py once at the start."),
    "b": ("swe-tools-b", "install_b.py",
          "Installs attempt B's tools into /tmp/b/t and B's own copy of the repository at /tmp/b/repo. Run "
          "scripts/install_b.py once at the start."),
    "fin": ("swe-tools-fin", "pick_patch.py",
            "Backup only - picks the best patch of both attempts and writes it into /workspace."),
}

DUO_SKILL_MD = """---
name: {name}
description: {desc}
---
# {name}

{body}
"""

DUO_SKILL_BODY = {
    "a": "Run once, first thing: the run_skill_script tool with skill_name {name} and file_path scripts/{script}.\n"
         "It installs shell commands under .swetools/ that you run with the run_command tool (see your instructions).",
    "b": "Run once, first thing: the run_skill_script tool with skill_name {name} and file_path scripts/{script}.\n"
         "It creates your own copy of the repository at /tmp/b/repo and installs your shell commands under /tmp/b/t/,\n"
         "which you run with the run_command tool (see your instructions).",
    "fin": "Only if `python3 .swetools/pick_patch.py --finisher` says No such file: the run_skill_script tool with\n"
           "skill_name {name} and file_path scripts/{script}.",
}

DUO_BODY = r"""
import os, sys, time, json, hashlib, tempfile, subprocess, shutil, fcntl


def find_ws():
    here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""
    try:
        c = json.load(open(os.path.join(here, "_cfg.json"))) if here else {}
        if c.get("real_ws") and os.path.exists(os.path.join(c["real_ws"], ".git")):
            return c["real_ws"]
    except (OSError, ValueError):
        pass
    for cand in (os.environ.get("PWD"), os.environ.get("SWE_WS"), os.getcwd(), "/workspace"):
        if cand and os.path.exists(os.path.join(cand, ".git")) and "/b/repo" not in cand:
            return cand
    sys.exit("error: repository not found")


def git(ws, *args, timeout=60):
    try:
        r = subprocess.run(["git"] + list(args), cwd=ws, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def write_atomic(path, text, mode=None):
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w") as fh:
        fh.write(text)
    if mode:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def add_exclude(repo, lines):
    excl = os.path.join(repo, ".git", "info", "exclude")
    try:
        os.makedirs(os.path.dirname(excl), exist_ok=True)
        existing = open(excl).read() if os.path.exists(excl) else ""
        add = [l for l in lines if l not in existing.split("\n")]
        if add:
            with open(excl, "a") as fh:
                fh.write("\n" + "\n".join(add) + "\n")
    except OSError:
        pass


def write_tools(dest, cfg, role):
    os.makedirs(dest, exist_ok=True)
    for name, src in FILES.items():
        write_atomic(os.path.join(dest, name), src)
    write_atomic(os.path.join(dest, "_cfg.json"), json.dumps(cfg))
    write_atomic(os.path.join(dest, "install.py"),
                 "ROLE = %r\nFILES = %r\nSHIM = %r\nBUDGET = %r\nDEADLINE = %r\nBODY = %r\nexec(BODY)\n"
                 % (role, FILES, SHIM, BUDGET, DEADLINE, BODY))


ws = find_ws()
tmpd = tempfile.gettempdir()
mark = hashlib.sha256(os.path.realpath(ws).encode("utf-8")).hexdigest()[:16]
D = os.path.join(tmpd, ".swe", mark)
os.makedirs(D, exist_ok=True)
brepo = os.path.join(tmpd, "b", "repo")
btools = os.path.join(tmpd, "b", "t")
common = {"mode": "duo", "real_ws": ws, "budget_s": BUDGET, "deadline_s": DEADLINE,
          "repos": {"a": ws, "b": brepo}}
cfg_a = dict(common, att="a", ws=ws, scratch=os.path.join(tmpd, "a"), display_scratch="/tmp/a",
             tools_display=".swetools")
cfg_b = dict(common, att="b", ws=brepo, scratch=os.path.join(tmpd, "b"), display_scratch="/tmp/b",
             tools_display="/tmp/b/t")
notes = []
lockf = open(os.path.join(D, "lock"), "a+")
end = time.time() + 90
while True:
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except OSError:
        if time.time() > end:
            sys.exit("error: another install is still running; run this again")
        time.sleep(0.1)
try:
    code, sha, _ = git(ws, "rev-parse", "-q", "--verify", "_swegemma_baseline^{commit}")
    if code or not sha:
        code, sha, _ = git(ws, "rev-parse", "HEAD")
    run_id = sha
    id_path = os.path.join(D, "run_id")
    try:
        old_id = open(id_path).read().strip()
    except OSError:
        old_id = None
    if old_id != run_id:  # a new session on this checkout: forget the old tool state
        for m in (mark, hashlib.sha256(os.path.realpath(brepo).encode("utf-8")).hexdigest()[:16]):
            for n in (".swetools_state.json", ".swetools_seen"):
                try:
                    os.remove(os.path.join(tmpd, "%s-%s" % (n, m)))
                except OSError:
                    pass
        for n in ("final.json", "promote.json", "nudges.json", "wstate.json", "wstate.diff", "done.json",
                  "last_a.json", "last_b.json", "warn_a", "warn_b", "tripwire.json"):
            try:
                os.remove(os.path.join(D, n))
            except OSError:
                pass
        shutil.rmtree(os.path.join(D, "snap"), ignore_errors=True)
        write_atomic(id_path, run_id)
        write_atomic(os.path.join(D, "t0"), "%.0f" % time.time())
    for d in (os.path.join(tmpd, "a"), os.path.join(tmpd, "b")):
        os.makedirs(d, exist_ok=True)
    # attempt A: tools in /workspace/.swetools (git-excluded) + shims
    add_exclude(ws, [".swetools/", "*.swepromote"])
    dest_a = os.path.join(ws, ".swetools")
    write_tools(dest_a, cfg_a, "a")
    write_atomic(os.path.join(dest_a, "run_command"), SHIM, 0o755)
    # attempt B: a private clone of the baseline commit (created once; never reset once it exists)
    ok = False
    if os.path.isdir(os.path.join(brepo, ".git")):
        c2, head, _ = git(brepo, "rev-parse", "HEAD")
        ok = not c2 and head == sha
    if not ok:
        shutil.rmtree(brepo, ignore_errors=True)
        tmpc = brepo + ".new"
        shutil.rmtree(tmpc, ignore_errors=True)
        os.makedirs(os.path.dirname(brepo), exist_ok=True)
        c1, _, err = git(os.path.dirname(brepo), "clone", "-q", "--shared", "--no-checkout", ws, tmpc)
        c2 = 1
        if not c1:
            c2, _, err = git(tmpc, "checkout", "-q", "--detach", sha)
        if c1 or c2:
            notes.append("could not create /tmp/b/repo: %s" % err[-200:])
        else:
            try:
                shutil.copy(os.path.join(ws, ".git", "info", "exclude"), os.path.join(tmpc, ".git", "info", "exclude"))
            except OSError:
                pass
            sys.path.insert(0, dest_a)
            try:
                import check as _check
                _check._copy_ignored(ws, tmpc)
            except Exception as exc:
                notes.append("ignored files not copied: %s" % exc)
            os.rename(tmpc, brepo)
    if os.path.isdir(os.path.join(brepo, ".git")):
        add_exclude(brepo, [".swetools/", "*.swepromote"])
    write_tools(btools, cfg_b, "b")
    write_atomic(os.path.join(btools, "run_command"), SHIM, 0o755)
    # Tripwire baseline: the first install records /workspace's state, so a plain command that changes it before
    # any helper tool has run (e.g. attempt B's first command) is still undone at the next tool call. Without
    # this the first after_tool would record that change as tool-made (fake-LLM smoke scenario plain_b).
    if not os.path.exists(os.path.join(D, "wstate.json")):
        try:
            sys.path.insert(0, dest_a)
            import _duo as _d
            h, raw = _d._wstate()
            if h is not None:
                with open(os.path.join(D, "wstate.diff.tmp"), "w", encoding="utf-8", errors="surrogateescape") as fh:
                    fh.write(raw)
                os.replace(os.path.join(D, "wstate.diff.tmp"), os.path.join(D, "wstate.diff"))
                write_atomic(os.path.join(D, "wstate.json"), json.dumps({"h": h, "by": "install"}))
        except Exception as exc:
            notes.append("tripwire baseline not recorded: %s" % exc)
finally:
    fcntl.flock(lockf, fcntl.LOCK_UN)
    lockf.close()

for n in notes:
    print("NOTE: " + n)
src_layout = os.path.isdir(os.path.join(ws, "src")) and any(
    os.path.isfile(os.path.join(ws, "src", d, "__init__.py")) for d in os.listdir(os.path.join(ws, "src")))
if ROLE == "a":
    print("installed .swetools/ in /workspace (git-excluded). Use with run_command:")
    print("  python3 .swetools/locate.py TERM [TERM ...]         # find the code for the issue")
    print("  python3 .swetools/show.py FILE START [END]           # numbered lines")
    print("  python3 .swetools/edit.py FILE START END <<'EOF'     # replace lines START..END with the heredoc text")
    print("  python3 .swetools/run.py /tmp/a/repro.py <<'EOF'     # write the script from the heredoc and run it (15 s limit)")
    print("  python3 .swetools/check.py --repro /tmp/a/repro.py   # before/after repro + tests; VERDICT / GATE")
    print("  python3 .swetools/status.py                          # where your work stands and the next step")
    print("  python3 .swetools/sh.py <<'EOF'                      # a shell command that changes files (git checkout, rm)")
    print("  python3 .swetools/done.py                            # your attempt is finished (never reply with text)")
    print("Every tool output starts with a state line: [A /workspace | T+time/%d | patch | repro before->now | check | ...]." % DEADLINE)
    print("A plain command that changes /workspace is undone at the next tool call: change files only with these tools.")
    if src_layout:
        print("NOTE: src/ layout. The tools import the code from src/; run scripts with run.py.")
elif ROLE == "b":
    print("installed your tools in /tmp/b/t and your own copy of the repository in /tmp/b/repo. Use with run_command:")
    print("  python3 /tmp/b/t/locate.py TERM [TERM ...]           # find the code for the issue")
    print("  python3 /tmp/b/t/show.py FILE START [END]            # numbered lines of YOUR copy")
    print("  python3 /tmp/b/t/edit.py FILE START END <<'EOF'      # replace lines START..END in YOUR copy")
    print("  python3 /tmp/b/t/run.py /tmp/b/repro.py <<'EOF'      # write the script and run it against YOUR copy")
    print("  python3 /tmp/b/t/check.py --repro /tmp/b/repro.py    # before/after repro + tests; VERDICT / GATE")
    print("  python3 /tmp/b/t/status.py                           # where your work stands and the next step")
    print("  python3 /tmp/b/t/sh.py <<'EOF'                       # any other shell command (grep, git diff, pytest) in YOUR copy")
    print("  python3 /tmp/b/t/done.py                             # your attempt is finished (never reply with text)")
    print("FILE is relative to your copy, e.g. src/pkg/mod.py. submit_patch submits /workspace, which is NOT your copy:")
    print("never call submit_patch before a tool prints FINAL.")
    if src_layout:
        print("NOTE: src/ layout. The tools import the code from src/.")
else:
    r = subprocess.run([sys.executable, os.path.join(ws, ".swetools", "pick_patch.py"), "--finisher"], cwd=ws,
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stdout.write(r.stderr[-1000:])
"""

DUO_TEMPLATE = '''"""swe-tools (duo): install both attempts' tools (idempotent)."""
ROLE = __ROLE__
FILES = __FILES__
SHIM = __SHIM__
BUDGET = __BUDGET__
DEADLINE = __DEADLINE__
BODY = __BODY__
exec(BODY)
'''


def _arg(name, default):
    if name in sys.argv:
        return int(sys.argv[sys.argv.index(name) + 1])
    return default


def main_duo(bundle):
    files = {p.name: p.read_text() for p in sorted((HERE / "tools").glob("*.py"))}
    stems = [n[:-3] for n in files] + ["install", "install_a", "install_b", "pick_patch"]
    clash = [s for s in stems if s in sys.stdlib_module_names]
    assert not clash, "tool names shadow stdlib modules: %s" % clash
    budget, deadline = _arg("--budget", 300), _arg("--deadline", 250)
    for role, (name, script, desc) in DUO_SKILLS.items():
        skill = bundle / "skills" / name
        (skill / "scripts").mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(DUO_SKILL_MD.format(
            name=name, desc=desc, body=DUO_SKILL_BODY[role].format(name=name, script=script)))
        (skill / "scripts" / script).write_text(
            DUO_TEMPLATE.replace("__ROLE__", repr(role)).replace("__FILES__", repr(files))
            .replace("__SHIM__", repr(SHIM)).replace("__BUDGET__", repr(budget))
            .replace("__DEADLINE__", repr(deadline)).replace("__BODY__", repr(DUO_BODY)))
        print("wrote", skill)


def main():
    bundle = Path(sys.argv[1])
    if "--duo" in sys.argv:
        return main_duo(bundle)
    files = {p.name: p.read_text() for p in sorted((HERE / "tools").glob("*.py")) if p.name not in DUO_ONLY}
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
