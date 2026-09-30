"""Duo mode: attempt A works in /workspace, attempt B in a private clone (<TMP>/b/repo).

Shared state lives in the duo directory D = <TMP>/.swe/<hash of /workspace>:
  lock            flock serialising installs, the race, promotion and pick_patch
  final.json      written once: the chosen patch is in /workspace (every tool then prints FINAL first)
  promote.json    journal of an unfinished write into /workspace (finished or rolled back on the next call)
  snap/<att>/{last,gate}/  patch.diff (cleaned), repro.py, meta.json of the latest / latest GATE check.py
Writes into /workspace never go through checkout + clean + apply: the new content of every file is staged
first, a journal is written, then each file is replaced with os.replace (atomic per file); the result is
verified against the target diff and rolled back on a mismatch.
"""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _ws  # noqa: E402

FINAL_LINE = "FINAL PATCH IS IN /workspace: call submit_patch now, then reply with one line"


def ddir():
    return _ws.swe_dir()


def _p(name):
    return os.path.join(ddir(), name)


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json(path, obj):
    tmp = "%s.tmp%d" % (path, os.getpid())
    with open(tmp, "w") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


class Lock:
    """Exclusive flock on D/lock (waits at most `wait` seconds, then raises TimeoutError)."""

    def __init__(self, wait=60.0):
        self.wait = wait
        self.fh = None

    def __enter__(self):
        self.fh = open(_p("lock"), "a+")
        end = time.time() + self.wait
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.time() > end:
                    self.fh.close()
                    raise TimeoutError("duo lock busy")
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()
        return False


def final_info():
    return read_json(_p("final.json"))


def repos():
    """{'a': /workspace, 'b': B's clone} (from the installer's config)."""
    c = _ws.cfg()
    out = {"a": _ws.real_workspace()}
    b = (c.get("repos") or {}).get("b")
    if b:
        out["b"] = b
    return out


# ---------------------------------------------------------------- diffs

def export_diff(repo, timeout=30):
    """`git add -N . && git diff --binary _swegemma_baseline` of repo, exactly what submit_patch captures,
    but through a private copy of the index, so the real .git/index (and its lock) is never touched."""
    idx = os.path.join(ddir(), "idx.%d.%s" % (os.getpid(), _ws._mark(repo)))
    try:
        shutil.copyfile(os.path.join(repo, ".git", "index"), idx)
    except OSError:
        pass
    env = dict(os.environ, GIT_INDEX_FILE=idx, GIT_OPTIONAL_LOCKS="0")
    try:
        _ws.sh(["git", "add", "-N", "--", "."], repo, timeout=timeout, env=env)
        code, out, _ = _ws.sh(["git", "diff", "--binary", "_swegemma_baseline"], repo, timeout=timeout, env=env)
        if code:
            code, out, _ = _ws.sh(["git", "diff", "--binary", "HEAD"], repo, timeout=timeout, env=env)
        return out if not code else None
    finally:
        for f in (idx, idx + ".lock"):
            try:
                os.remove(f)
            except OSError:
                pass


def sections(diff):
    out = []
    for part in re.split(r"(?m)^(?=diff --git )", diff or ""):
        if not part.startswith("diff --git "):
            continue
        first = part.split("\n", 1)[0]
        m = re.match(r'diff --git "?a/(.*?)"? "?b/(.*?)"?$', first)
        path = m.group(2) if m else first[len("diff --git "):]
        head = part.split("\n@@", 1)[0]
        if not part.endswith("\n"):
            part += "\n"
        out.append({"path": path, "text": part, "new": "\nnew file mode" in head,
                    "deleted": "\ndeleted file mode" in head})
    return out


STRAY_RE = re.compile(r"(repro|debug|scratch|tmp|probe|reproduce|test_fix)", re.I)


def is_scratch(path, new):
    """Changes that never help a patch: tests and test config, tool files, new scratch files."""
    base = os.path.basename(path)
    if path.startswith(".swetools") or base.startswith(".adk_exec_") or path.endswith(".swepromote"):
        return True
    if _ws.is_test_path(path) or base in ("pytest.ini", "setup.cfg", "tox.ini", "conftest.py"):
        return True
    if new and (path.count("/") == 0 or STRAY_RE.search(path)):
        return True
    return False


def clean(diff):
    return "".join(s["text"] for s in sections(diff) if not is_scratch(s["path"], s["new"]))


def src_py(diff):
    return [s["path"] for s in sections(diff) if s["path"].endswith(".py") and not is_scratch(s["path"], s["new"])]


def src_lines(diff):
    n = 0
    for line in (diff or "").splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line[:1] in "+-" and line[1:].strip():
            n += 1
    return n


def norm(diff):
    return "\n".join(l.rstrip() for l in (diff or "").splitlines() if not l.startswith("index "))


def digest(diff):
    return hashlib.sha1(norm(diff).encode("utf-8", "replace")).hexdigest()[:16]


# ---------------------------------------------------------------- write a patch into /workspace

def _baseline_blob(ws, path):
    for ref in ("_swegemma_baseline", "HEAD"):
        try:
            r = subprocess.run(["git", "cat-file", "blob", "%s:%s" % (ref, path)], cwd=ws, capture_output=True,
                               timeout=20, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode == 0:
            return r.stdout
        if b"exists on disk, but not in" in r.stderr or b"does not exist in" in r.stderr:
            return None
    return None


def materialize(diff, paths):
    """{path: (bytes, mode) or None}: each path's content after applying diff to the baseline commit.
    None for the whole result when the diff does not apply."""
    ws = _ws.real_workspace()
    allp = list(dict.fromkeys(list(paths) + [s["path"] for s in sections(diff)]))
    mat = tempfile.mkdtemp(prefix="mat.", dir=ddir())
    dfile = mat + ".diff"
    try:
        for p in allp:
            blob = _baseline_blob(ws, p)
            if blob is not None:
                dst = os.path.join(mat, p)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as fh:
                    fh.write(blob)
                try:
                    os.chmod(dst, os.stat(os.path.join(ws, p)).st_mode & 0o777)
                except OSError:
                    pass
        if diff.strip():
            with open(dfile, "w", encoding="utf-8", errors="surrogateescape") as fh:
                fh.write(diff)
            # outside any repository, git apply behaves like patch(1) on the files under cwd
            env = dict(os.environ, GIT_CEILING_DIRECTORIES=os.path.dirname(mat))
            env.pop("GIT_DIR", None)
            env.pop("GIT_INDEX_FILE", None)
            code, _, err = _ws.sh(["git", "apply", "--whitespace=nowarn", dfile], mat, timeout=30, env=env)
            if code:
                return None
        out = {}
        for p in allp:
            f = os.path.join(mat, p)
            if os.path.isfile(f) and not os.path.islink(f):
                with open(f, "rb") as fh:
                    out[p] = (fh.read(), os.stat(f).st_mode & 0o777)
            else:
                out[p] = None
        return out
    finally:
        shutil.rmtree(mat, ignore_errors=True)
        try:
            os.remove(dfile)
        except OSError:
            pass


def _apply_items(items, which):
    ws = _ws.real_workspace()
    pause = float(os.environ.get("SWE_PROMOTE_SLEEP", "0") or 0)  # test hook: widen the window for SIGKILL tests
    for it in items:
        dst = os.path.join(ws, it["path"])
        src = it[which]
        if src is None:
            if os.path.lexists(dst):
                os.remove(dst)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".swepromote"
            shutil.copyfile(src, tmp)
            shutil.copymode(src, tmp)
            os.replace(tmp, dst)
        if pause:
            time.sleep(pause)


def promote(target, tag):
    """Make /workspace's diff equal `target`. Returns (ok, why). Caller holds the Lock."""
    ws = _ws.real_workspace()
    cur = export_diff(ws)
    if cur is None:
        return False, "cannot read the /workspace diff"
    if norm(cur) == norm(target):
        return True, "already in /workspace"
    paths = list(dict.fromkeys([s["path"] for s in sections(cur)] + [s["path"] for s in sections(target)]))
    new = materialize(target, paths)
    if new is None:
        return False, "the patch does not apply to the original code"
    stage = tempfile.mkdtemp(prefix="promote.", dir=ddir())
    items = []
    for i, p in enumerate(paths):
        dst = os.path.join(ws, p)
        old = None
        if os.path.isfile(dst) and not os.path.islink(dst):
            old = os.path.join(stage, "o%d" % i)
            shutil.copyfile(dst, old)
            shutil.copymode(dst, old)
        nw = None
        if new.get(p) is not None:
            nw = os.path.join(stage, "n%d" % i)
            with open(nw, "wb") as fh:
                fh.write(new[p][0])
            os.chmod(nw, new[p][1] or 0o644)
        items.append({"path": p, "old": old, "new": nw})
    journal = {"status": "applying", "tag": tag, "target": digest(target), "before": digest(cur),
               "items": items, "stage": stage, "t": time.time()}
    write_json(_p("promote.json"), journal)
    _apply_items(items, "new")
    after = export_diff(ws)
    ok = after is not None and norm(after) == norm(target)
    if not ok:
        _apply_items(items, "old")
    try:
        os.remove(_p("promote.json"))
    except OSError:
        pass
    shutil.rmtree(stage, ignore_errors=True)
    return (True, "ok") if ok else (False, "verification failed, /workspace restored")


def recover():
    """Finish (or roll back) a write into /workspace that a kill interrupted."""
    j = read_json(_p("promote.json"))
    if not j:
        return None
    try:
        with Lock(wait=20):
            j = read_json(_p("promote.json"))
            if not j:
                return None
            items = j.get("items") or []
            have_new = all(it["new"] is None or os.path.isfile(it["new"]) for it in items)
            done = "rolled forward"
            if have_new:
                _apply_items(items, "new")
            after = export_diff(_ws.real_workspace())
            if after is None or digest(after) != j.get("target"):
                if all(it["old"] is None or os.path.isfile(it["old"]) for it in items):
                    _apply_items(items, "old")
                    done = "rolled back"
            ws = _ws.real_workspace()
            for it in items:
                try:
                    os.remove(os.path.join(ws, it["path"]) + ".swepromote")
                except OSError:
                    pass
            os.remove(_p("promote.json"))
            shutil.rmtree(j.get("stage") or "/nonexistent", ignore_errors=True)
            _log("recover: %s (%s)" % (done, j.get("tag")))
            return done
    except (TimeoutError, OSError):
        return None


def _log(msg):
    try:
        with open(_p("duo.log"), "a") as fh:
            e = _ws.elapsed()
            fh.write("[T+%s %s] %s\n" % ("?" if e is None else int(e), _ws.att() or "-", msg))
    except OSError:
        pass


# ---------------------------------------------------------------- snapshots, race, deadline

def save_snapshot(meta, repro):
    """Save this attempt's cleaned patch, repro and check.py result (pick_patch reads them)."""
    a = _ws.att() or "a"
    root = os.path.join(ddir(), "snap", a)
    raw = export_diff(_ws.workspace()) or ""
    diff = clean(raw)
    meta = dict(meta, digest=digest(diff), t=_ws.elapsed())
    for kind in (["last", "gate"] if meta.get("gate") else ["last"]):
        d = os.path.join(root, kind)
        tmp = d + ".new%d" % os.getpid()
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        with open(os.path.join(tmp, "patch.diff"), "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write(diff)
        if repro and os.path.isfile(repro):
            shutil.copyfile(repro, os.path.join(tmp, "repro.py"))
            meta["repro_path"] = repro
        write_json(os.path.join(tmp, "meta.json"), meta)
        shutil.rmtree(d, ignore_errors=True)
        os.rename(tmp, d)
    hist = read_json(os.path.join(root, "digests.json")) or {}
    hist[meta["digest"]] = {"ok": bool(meta.get("verdict_ok")), "gate": bool(meta.get("gate")),
                            "caused": meta.get("caused"), "tests_ran": bool(meta.get("tests_ran"))}
    write_json(os.path.join(root, "digests.json"), hist)


def write_final(info):
    info = dict(info, t=_ws.elapsed())
    write_json(_p("final.json"), info)
    _log("FINAL: %s" % info.get("summary", "")[:200].replace("\n", " | "))


def race_win():
    """check.py GATE passed: the first attempt to pass wins, and its patch goes into /workspace."""
    try:
        with Lock(wait=30):
            if final_info():
                if FINAL_LINE not in _ws.CONTROL:
                    _ws.CONTROL.insert(0, FINAL_LINE)
                print("GATE PASSED, but the attempts are already over: /workspace holds the chosen patch.")
                return True
            r = _ws.remaining()
            if r is not None and r < 20:
                return False  # too late to write into /workspace; the deadline pick decides
            a = _ws.att() or "a"
            if a == "b":
                diff = clean(export_diff(_ws.workspace()) or "")
                ok, why = promote(diff, "race-b")
            else:
                raw = export_diff(_ws.real_workspace()) or ""
                ok, why = (True, "") if norm(raw) == norm(clean(raw)) else promote(clean(raw), "race-a")
            if not ok:
                _log("race win by %s not promoted: %s" % (a, why))
                print("GATE PASSED, but copying your patch into /workspace failed (%s). Keep working; at T+%d the "
                      "tools pick the best patch." % (why, _ws.DEADLINE_S))
                return False
            write_final({"winner": a, "kind": "current", "how": "race",
                         "summary": "attempt %s passed the GATE first; its patch is in /workspace" % a.upper()})
            _ws.CONTROL.insert(0, FINAL_LINE)
            print("GATE PASSED: your verified patch is now in /workspace. The attempts are over.")
            return True
    except TimeoutError:
        return False


def before_tool(tool):
    """Runs before every tool in duo mode. True = do not run the tool (the attempts are over)."""
    recover()
    _tripwire_check()
    fin = final_info()
    if fin is None and tool != "pick_patch.py":
        e = _ws.elapsed()
        if e is not None and e >= _ws.DEADLINE_S:
            import pick_patch
            print("ATTEMPT TIME UP (T+%ds): picking the best patch of both attempts." % e)
            fin = pick_patch.pick("deadline")
            return True
    if fin is not None and tool != "pick_patch.py":
        if FINAL_LINE not in _ws.CONTROL:
            _ws.CONTROL.insert(0, FINAL_LINE)
        print("The attempts are over. " + (fin.get("summary") or ""))
        return True
    return False


def _wstate():
    ws = _ws.real_workspace()
    _, num, _ = _ws.sh(["git", "diff", "--numstat", "HEAD"], ws, timeout=20)
    _, new, _ = _ws.sh(["git", "ls-files", "--others", "--exclude-standard"], ws, timeout=20)
    return hashlib.sha1((num + "\0" + new).encode()).hexdigest()[:12], num, new


def _tripwire_check():
    """Log (for the lab) when /workspace changed between tool calls outside the tools (plain commands)."""
    try:
        prev = read_json(_p("wstate.json"))
        if not prev:
            return
        h, num, new = _wstate()
        if h != prev.get("h"):
            _log("tripwire: /workspace changed outside the tools since %s's last tool call: %s"
                 % (prev.get("by"), (num + new).replace("\n", " ")[:200]))
    except Exception:
        pass


def after_tool():
    try:
        h, _, _ = _wstate()
        write_json(_p("wstate.json"), {"h": h, "by": _ws.att()})
    except Exception:
        pass


def display(out):
    """Show model-facing paths (/tmp/..., /workspace) and this attempt's own tool paths."""
    c = _ws.cfg()
    reps = []
    real = _ws.real_workspace()
    tmp = tempfile.gettempdir()
    for src, dst in ((real, "/workspace"), (os.path.realpath(real), "/workspace"),
                     (tmp, "/tmp"), (os.path.realpath(tmp), "/tmp")):
        if src and src != dst and (src, dst) not in reps:
            reps.append((src, dst))
    for src, dst in sorted(reps, key=lambda x: -len(x[0])):
        out = out.replace(src + "/", dst + "/").replace(src + "\n", dst + "\n").replace(src + " ", dst + " ")
    if c.get("att") == "b":
        out = out.replace("python3 .swetools/", "python3 %s/" % c.get("tools_display", "/tmp/b/t"))
    sc = c.get("display_scratch")
    if sc:
        out = re.sub(r"(?<![\w./-])/tmp/repro\.py", sc + "/repro.py", out)
    return out
