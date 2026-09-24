"""Phase 2 verification, mirroring swegemma's ``verify_task`` (HARNESS_README section 8.2)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from . import env


def _with_newline(patch: str) -> str:
    return patch if patch.endswith("\n") else patch + "\n"


def test_files(test_patch: str) -> list[str]:
    return re.findall(r"^\+\+\+ b/(\S+)", test_patch, re.M)


def apply_patch(ws: Path, patch_file: Path) -> tuple[bool, str]:
    passes = [
        f"git apply --unsafe-paths -p1 {patch_file}",
        f"git apply --unsafe-paths -3 {patch_file}",
        f"git apply --unsafe-paths --ignore-space-change --ignore-whitespace {patch_file}",
        f"git apply --unsafe-paths --recount {patch_file}",
        f"git apply --unsafe-paths -p0 {patch_file}",
        f"patch --batch --forward -p1 --dry-run < {patch_file} && patch --batch --forward -p1 < {patch_file}",
        f"patch --batch --forward -l -p1 --dry-run < {patch_file} && patch --batch --forward -l -p1 < {patch_file}",
    ]
    errors = []
    for cmd in passes:
        r = env.sh(cmd, cwd=ws, timeout=120)
        if r.returncode == 0:
            return True, cmd
        errors.append(f"{cmd}: {r.stderr.strip()[-400:]}")
    return False, "\n".join(errors)


def verify(task: dict, agent_patch: str, workdir: Path | None = None, timeout: int = 900) -> dict:
    """Apply ``agent_patch`` to a fresh workspace, then the hidden tests, and run pytest."""
    root = Path(workdir or tempfile.mkdtemp(prefix="verify_"))
    ws = env.make_workspace(task, root / "workspace")
    tmp = root / "tmp"
    tmp.mkdir(exist_ok=True)
    venv = env.task_venv(env.venv_for(task, ws), ws, root / "venv")
    result = {"instance_id": task["instance_id"], "resolved": False}

    if agent_patch.strip():
        pf = root / "agent.patch"
        pf.write_text(_with_newline(agent_patch))
        ok, how = apply_patch(ws, pf)
        if not ok:
            result["error"] = "Failed to apply agent_patch: " + how[-1500:]
            return result

    files = test_files(task["test_patch"])
    quoted = " ".join(f"'{f}'" for f in files)
    env.sh(f"git checkout HEAD -- {quoted} 2>/dev/null || true; git clean -f -- {quoted} 2>/dev/null || true", cwd=ws)
    tpf = root / "test.patch"
    tpf.write_text(_with_newline(task["test_patch"]))
    ok, how = apply_patch(ws, tpf)
    if not ok:
        result["error"] = "Failed to apply test_patch: " + how[-1500:]
        return result
    env.configure_pytest_ini(ws)
    env.configure_conftest(ws)

    targets = [f for f in files if f.endswith(".py") and (ws / f).exists()]
    cmd = (
        "PYTHONSAFEPATH=1 python3 -m pytest " + " ".join(f"'{t}'" for t in targets) +
        ' -p no:anyio -o timeout=0 -o norecursedirs=".* build dist venv"'
        ' -o python_classes="Test* *Test" -q -rfE -p no:cacheprovider 2>&1'
    )
    try:
        r = env.run_sandboxed(cmd, cwd=ws, env=env.command_env(venv, tmp), timeout=timeout)
        result["exit_code"] = r.returncode
        result["output"] = r.stdout[-6000:]
        result["failed"] = sorted(set(re.findall(r"^(?:FAILED|ERROR) (\S+)", r.stdout, re.M)))
        result["resolved"] = r.returncode == 0
    except Exception as exc:  # noqa: BLE001 - timeouts count as failures
        result["error"] = f"pytest: {exc}"
    return result


def resolved_given_env(result: dict, gold_failed: list[str] | None) -> bool:
    """Resolved, allowing only the failures the gold patch also has in this environment.

    Our sandbox is not byte-identical to the harness container (for example,
    connect-timeout tests fail fast without a network), so a test that fails
    even with the reference fix says nothing about the agent's patch.
    """
    if result.get("resolved"):
        return True
    if gold_failed is None or result.get("error") or "exit_code" not in result:
        return False
    if result["exit_code"] != 1 or not result.get("failed"):
        return False
    return set(result["failed"]) <= set(gold_failed)
