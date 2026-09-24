"""Workspace and Python environment preparation, mirroring swegemma's container bootstrap.

A task workspace is the repository at ``base_commit`` with no history, the
harness's pytest.ini/conftest.py written in, and a single ``baseline`` commit,
exactly like Container A/B in HARNESS_README section 4.2. Instead of Docker we
use one directory per task and a uv-managed Python 3.13 venv per distinct set
of dependency files, shared across tasks.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

LO_UP = Path(__file__).with_name("lo_up.py")
CACHE = Path(os.environ.get("LOCALEVAL_CACHE", Path.home() / ".cache" / "localeval"))
MIRRORS = CACHE / "mirrors"
VENVS = CACHE / "venvs"
PYTHON = os.environ.get("LOCALEVAL_PYTHON", "3.13")

EXCLUDE_RULES = "__pycache__/\n*.pyc\n.pytest_cache/\n*.egg-info/\nbuild/\ndist/\n.coverage\n"
PYTEST_ADDOPTS = "--import-mode=importlib -p no:anyio"
NORECURSE = ".* build dist venv"
CONFTEST_HEADER = "# Standard test discovery hook for SWE-gemma public benchmark\n"
DEP_FILES = (
    "pyproject.toml", "setup.py", "setup.cfg",
    "requirements.txt", "requirements-dev.txt", "requirements-tests.txt",
    "requirements-docs-tests.txt", "requirements/tests.txt", "requirements/dev.txt",
)
BASE_TEST_DEPS = ["pytest", "pytest-timeout==2.1.0", "typer"]
# Test-only imports some commits need but do not declare in any file we install from.
REPO_TEST_DEPS = {
    "fastapi/fastapi": ["httpx", "python-multipart", "dirty-equals", "inline-snapshot", "sqlmodel", "pyyaml"],
    "Textualize/rich": ["attrs"],
    "psf/requests": ["pytest-httpbin", "pytest-mock", "trustme"],
    "encode/httpx": ["trustme", "uvicorn", "chardet"],
}


def sh(cmd: str, cwd: Path | None = None, timeout: int = 1800, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)


def run_sandboxed(cmd: str, cwd: Path, env: dict, timeout: int) -> subprocess.CompletedProcess:
    """Run like the harness container: offline (own network namespace), own process group."""
    proc = subprocess.Popen(
        ["unshare", "-n", "bash", "-c", f"/usr/bin/python3 {LO_UP} 2>/dev/null; " + cmd], cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, 9)
        out, err = proc.communicate()
        raise TimeoutError(f"command exceeded {timeout}s") from None
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path.with_suffix(".lock"), "w")
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


def mirror(repo: str) -> Path:
    """A bare clone of the upstream repository, fetched once."""
    dest = MIRRORS / (repo.replace("/", "__") + ".git")
    with _locked(dest):
        if not dest.exists():
            r = sh(f"git clone --bare --quiet https://github.com/{repo}.git {dest}", timeout=3600)
            if r.returncode:
                raise RuntimeError(f"clone {repo}: {r.stderr[-2000:]}")
    return dest


def ensure_commit(repo: str, commit: str) -> Path:
    m = mirror(repo)
    if sh(f"git cat-file -e {commit}^{{commit}}", cwd=m).returncode:
        with _locked(m):
            sh(f"git fetch --quiet origin {commit}", cwd=m, timeout=1800)
    return m


def configure_pytest_ini(ws: Path) -> None:
    ini = ws / "pytest.ini"
    existing = ini.read_text(errors="replace") if ini.exists() else ""
    if "[pytest]" in existing:
        lines, has_addopts, has_norecurse = [], False, False
        for line in existing.splitlines():
            if line.strip().startswith("addopts"):
                has_addopts = True
                cur = line.split("=", 1)[1] if "=" in line else ""
                for opt in PYTEST_ADDOPTS.split():
                    if opt not in cur:
                        line = line.rstrip() + " " + opt
            elif line.strip().startswith("norecursedirs"):
                has_norecurse = True
                for d in NORECURSE.split():
                    if d not in line:
                        line = line.rstrip() + " " + d
            lines.append(line)
        if not has_addopts:
            lines.append(f"addopts = {PYTEST_ADDOPTS}")
        if not has_norecurse:
            lines.append(f"norecursedirs = {NORECURSE}")
        content = "\n".join(lines) + "\n"
    else:
        content = (
            f"[pytest]\naddopts = {PYTEST_ADDOPTS}\nnorecursedirs = {NORECURSE}\n"
            "python_classes = Test* *Test\npython_files = test_*.py *_test.py\n"
            "filterwarnings =\n    ignore::DeprecationWarning\n    ignore::UserWarning\n"
        ) + (("\n" + existing) if existing.strip() else "")
    ini.write_text(content)


def configure_conftest(ws: Path) -> None:
    path = ws / "conftest.py"
    existing = path.read_text(errors="replace") if path.exists() else ""
    if CONFTEST_HEADER.strip() not in existing:
        path.write_text(CONFTEST_HEADER + (existing + "\n" if existing else ""))


def make_workspace(task: dict, dest: Path) -> Path:
    """Extract the repo at base_commit into ``dest`` with a single baseline commit."""
    m = ensure_commit(task["repo"], task["base_commit"])
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    r = sh(f"git archive {task['base_commit']} | tar -x -C {dest}", cwd=m)
    if r.returncode:
        raise RuntimeError(f"archive {task['instance_id']}: {r.stderr[-2000:]}")
    sh("git init -q -b main && git config user.email agent@eval && git config user.name Agent", cwd=dest)
    (dest / ".git" / "info").mkdir(parents=True, exist_ok=True)
    with open(dest / ".git" / "info" / "exclude", "a") as fh:
        fh.write(EXCLUDE_RULES)
    configure_pytest_ini(dest)
    configure_conftest(dest)
    r = sh('git add -A && git commit -q -m "baseline" --allow-empty', cwd=dest)
    if r.returncode:
        raise RuntimeError(f"baseline commit: {r.stderr[-2000:]}")
    return dest


def _dep_fingerprint(ws: Path) -> str:
    h = hashlib.sha256()
    for name in DEP_FILES:
        p = ws / name
        if p.is_file():
            h.update(name.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:16]


def _requirement_args(ws: Path) -> str:
    reqs = []
    for name in ("requirements-tests.txt", "requirements-dev.txt", "requirements/tests.txt",
                 "requirements/dev.txt", "requirements.txt"):
        if (ws / name).is_file():
            reqs.append(name)
    return " ".join(f"-r {r}" for r in reqs)


def _test_groups(ws: Path) -> str:
    """PEP 735 dependency groups holding test requirements (newer fastapi uses these)."""
    py = ws / "pyproject.toml"
    if not py.is_file():
        return ""
    try:
        import tomllib
        groups = tomllib.loads(py.read_text()).get("dependency-groups", {})
    except Exception:  # noqa: BLE001
        return ""
    return " ".join(f"--group {g}" for g in ("tests", "test", "testing") if g in groups)


def venv_for(task: dict, ws: Path) -> Path:
    """A shared venv matching this workspace's dependency files."""
    key = f"{task['repo'].replace('/', '__')}-v3-{_dep_fingerprint(ws)}"
    venv = VENVS / key
    with _locked(venv):
        if (venv / ".ready").exists():
            return venv
        if venv.exists():
            shutil.rmtree(venv)
        r = sh(f"uv venv -q -p {PYTHON} {venv}", timeout=900)
        if r.returncode:
            raise RuntimeError(f"venv: {r.stderr[-2000:]}")
        py = venv / "bin" / "python"
        base = " ".join(f"'{d}'" for d in BASE_TEST_DEPS + REPO_TEST_DEPS.get(task["repo"], []))
        reqs = _requirement_args(ws)
        groups = _test_groups(ws)
        # Requirement files often reference "-e ." or relative files, so install from the workspace.
        attempts = [f"uv pip install -q -p {py} {base} {groups} {reqs} -e ."] if groups else []
        attempts += [
            f"uv pip install -q -p {py} {base} {reqs} -e .",
            f"uv pip install -q -p {py} {base} -e '.[test,tests,dev,testing]'",
            f"uv pip install -q -p {py} {base} -e .",
        ]
        log = []
        for cmd in attempts:
            r = sh(cmd, cwd=ws, timeout=1800)
            log.append(f"$ {cmd}\n{r.stdout[-1500:]}{r.stderr[-3000:]}")
            if r.returncode == 0:
                break
        else:
            raise RuntimeError("venv install failed:\n" + "\n".join(log))
        _strip_editable(venv, ws)
        (venv / "install.log").write_text("\n".join(log))
        (venv / ".ready").write_text("ok")
    return venv


def _strip_editable(venv: Path, ws: Path) -> None:
    """The venv is shared, so drop the editable link to the workspace it was built from.

    Each command instead gets its own workspace on PYTHONPATH (see command_env),
    which is what the harness's fast path does with workspace_paths.pth.
    """
    site = next((venv / "lib").glob("python3*/site-packages"))
    for f in set(site.glob("*.pth")) | set(site.glob("__editable__*")):
        if f.is_dir():
            continue
        text = f.read_text(errors="replace") if f.suffix == ".pth" else ""
        if f.name.startswith("__editable__") or str(ws) in text:
            f.unlink(missing_ok=True)


def workspace_paths(ws: Path) -> list[str]:
    return [str(ws)] + [str(p) for p in sorted(ws.iterdir()) if p.is_dir() and not p.name.startswith(".")]


def task_venv(shared: Path, ws: Path, dest: Path) -> Path:
    """A tiny per-task venv layered on the shared one.

    sys.path order matches the harness container: stdlib, then installed
    dependencies, then the workspace paths from workspace_paths.pth, so
    packages like rich/traceback.py never shadow the stdlib.
    """
    if not (dest / "bin" / "python").exists():
        r = sh(f"uv venv -q -p {shared / 'bin' / 'python'} {dest}", timeout=300)
        if r.returncode:
            raise RuntimeError(f"task venv: {r.stderr[-2000:]}")
    site = next((dest / "lib").glob("python3*/site-packages"))
    shared_site = next((shared / "lib").glob("python3*/site-packages"))
    (site / "a_shared_deps.pth").write_text(f"{shared_site}\n")
    (site / "workspace_paths.pth").write_text("\n".join(workspace_paths(ws)) + "\n")
    for script in ("pytest", "py.test"):
        f = dest / "bin" / script
        f.write_text('#!/bin/sh\nexec python3 -m pytest "$@"\n')
        f.chmod(0o755)
    return dest


def command_env(venv: Path, tmp: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENROUTER", "KAGGLE", "PYTHON", "VIRTUAL_ENV"))}
    env.update(
        PATH=f"{venv / 'bin'}:/usr/local/bin:/usr/bin:/bin",
        VIRTUAL_ENV=str(venv),
        TMPDIR=str(tmp), TEST_TMPDIR=str(tmp),
        HOME=str(tmp), PYTHONDONTWRITEBYTECODE="1",
    )
    return env
