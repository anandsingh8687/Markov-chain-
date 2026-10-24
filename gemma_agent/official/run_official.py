"""Run agent bundles through the OFFICIAL swegemma harness, locally, against an external model endpoint.

This is the same pipeline the Kaggle scorer runs (Evaluator.evaluate_task: Container A agent loop,
patch extraction, Container B verification), built the same way as the host notebook / our lab
kernel (gemma_agent/lab/make_lab.py), except:
  * the model registry points at an external OpenAI-compatible endpoint (--api-base) instead of a
    VllmServer started in-process (VllmServer.create_model_registry is reused unchanged);
  * sandbox='subprocess' (no docker daemon here). By default (--sandbox-env docker-like) the
    SubprocessManager is swapped for a subclass that behaves like the swebench-sandbox container
    (python3.13, Dockerfile packages, setup.py fast path, git identity); see make_docker_like_manager.
    Test deps come from localeval's per-repo venvs (--deps replica, gold passes 36/42 of v17) or
    from the public wheels exactly as the harness streams them (--deps image, gold passes ~20/42);
  * tasks run N at a time in separate worker processes (--jobs), each with its own sandbox dirs.

Competition data (--data) must mirror the Kaggle layout: tasks.jsonl, snapshots/<id>.tgz,
wheels/*.whl, sandbox/setup.py, and optionally graphs/ + embeddings/ (their presence changes the
initial prompt: the harness appends a "Code Intelligence Tools" section when the task's graph and
embedding files exist, as they do on Kaggle).

Usage (needs the official wheels; use the venv they are installed in):
    python gemma_agent/official/run_official.py --bundle gemma_agent/bundle_v13 \
        --ids fastapi_14873 rich_3006 --results /tmp/off_v13 --jobs 4 \
        --api-base http://HOST:8000/v1 --api-key "$VLLM_API_KEY" --model gemma-4-31b-it-qat-w4a16-ct

    # Phase 2 only, no model: verify the gold patch (or an empty patch) with the real verifier
    python gemma_agent/official/run_official.py --phase2-only gold --ids rich_3063 --results /tmp/gold

Outputs in --results:
    results.jsonl            one row per task (lab format: resolved, status, patch, tool calls, ...)
    patches/<id>.patch       the extracted agent patch
    test_outputs/<id>.log    Phase 2 pytest output
    traces/trace_<id>.json   full SessionTrace written by the harness
    logs/<id>.log            harness transcript of the Phase 1 session
    worker_logs/<id>.log     python logging of the worker process (retries, harness warnings)
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
import traceback
from pathlib import Path

DEFAULT_DATA = Path(os.environ.get(
    "SWEGEMMA_DATA",
    "/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/compdata"))

# Same process environment as the host notebook / lab kernel.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, help="agent submission directory (agent.yaml, eval_config.yaml, ...)")
    ap.add_argument("--ids", nargs="+", required=True, help="task instance ids (or @file with ids)")
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=1, help="tasks evaluated in parallel (separate processes)")
    ap.add_argument("--api-base", default=os.environ.get("VLLM_API_BASE", "http://127.0.0.1:8000/v1"))
    ap.add_argument("--api-key", default=None,
                    help="endpoint key (default: $VLLM_API_KEY or EMPTY); never logged")
    ap.add_argument("--model", default="gemma-4-31b-it-qat-w4a16-ct",
                    help="model alias the bundle declares (registered in the ModelRegistry)")
    ap.add_argument("--served-model", default=None,
                    help="model name the endpoint serves (default: --model); LiteLlm gets openai/<served>")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA, help="competition data root (Kaggle layout)")
    ap.add_argument("--compaction-threshold", type=int, default=14336,
                    help="EventsCompactionConfig.token_threshold (host notebook 14336, README 32768)")
    ap.add_argument("--no-graphs", action="store_true",
                    help="do not pass graphs/embeddings dirs (drops the Code Intelligence prompt section)")
    ap.add_argument("--workdir", type=Path, default=None,
                    help="parent dir for the subprocess sandboxes (default: system temp dir)")
    ap.add_argument("--phase2-only", choices=["gold", "empty"], default=None,
                    help="skip the agent: verify the task's gold patch or an empty patch (no model needed)")
    ap.add_argument("--sandbox-env", choices=["docker-like", "subprocess"], default="docker-like",
                    help="docker-like (default): emulate the swebench-sandbox container (python3.13 + Dockerfile "
                         "packages + streamed wheels + setup.py + git identity); subprocess: the stock "
                         "SubprocessManager, exactly as a Kaggle notebook runs it (host site-packages leak in)")
    ap.add_argument("--deps", choices=["image", "replica"], default="replica",
                    help="docker-like test deps: 'image' = the official code path (Dockerfile packages + newest "
                         "public wheel of each package streamed in; gold fails on most fastapi/requests tasks); "
                         "'replica' = localeval's per-repo uv venv (pinned deps), no wheel streaming")
    ap.add_argument("--python313", default="/usr/bin/python3.13", help="interpreter for the docker-like sandbox")
    ap.add_argument("--extra-wheels", type=Path, default=None,
                    help="dir of additional wheels merged with <data>/wheels (the public wheels miss some test "
                         "deps the private scorer has, e.g. typing_inspection, pytest-httpbin, dirty-equals)")
    ap.add_argument("--max-time-minutes", type=float, default=None, help="override eval_config.yaml")
    a = ap.parse_args(argv)
    ids: list[str] = []
    for x in a.ids:
        ids += Path(x[1:]).read_text().split() if x.startswith("@") else [x]
    a.ids = list(dict.fromkeys(ids))
    if a.phase2_only is None and a.bundle is None:
        ap.error("--bundle is required unless --phase2-only is given")
    if a.api_key is None:
        a.api_key = os.environ.get("VLLM_API_KEY", "EMPTY")
    return a


# ---------------------------------------------------------------- docker-like sandbox

DOCKER_SP = "/usr/local/lib/python3.13/site-packages"
IMAGE_PIP = ["pytest", "pytest-timeout==2.1.0", "typer", "pdm-backend", "setuptools", "wheel", "poetry-core",
             "hatchling", "flit-core", "editables"]  # docker/Dockerfile.sandbox


def prepare_image(data: Path, python: str) -> Path:
    """Build the 'swebench-sandbox' image as a python3.13 venv (once): Dockerfile.sandbox's pip line + shims."""
    import subprocess
    image = data / "image313"
    marker = image / ".swegemma_image_ok"
    if marker.exists():
        return image
    subprocess.run([python, "-m", "venv", "--clear", str(image)], check=True)
    subprocess.run([str(image / "bin" / "python"), "-m", "pip", "install", "-q", "--no-cache-dir", *IMAGE_PIP],
                   check=True)
    sp = next(image.glob("lib/python3*/site-packages"))
    for shim in ("imp.py", "telnetlib.py"):
        src = data / "docker" / shim
        if src.exists():
            (sp / shim).write_text(src.read_text())
    marker.write_text("ok\n")
    return image


def make_docker_like_manager(image: Path, python: str, timeout_seconds: int, base_dir: Path | None,
                             wheels_dir: Path | None = None, inject_wheels: bool = True):
    """A SubprocessManager that behaves like the docker backend's container.

    The stock subprocess backend skips install_test_dependencies (no wheels are injected, setup.py
    never runs), runs the sandbox on the harness's own interpreter with the host site-packages
    visible, and has no git identity (HOME is the sandbox tmp dir), so the 'baseline' commit fails.
    This subclass (its class name is deliberately not 'SubprocessManager', so the harness treats it
    like a container) gives each sandbox a python3.13 venv layered on the image venv, maps
    /usr/local/lib/python3.13/site-packages to that venv's site-packages (where the harness streams
    the unpacked base wheels), and writes the Dockerfile's git config into HOME.

    With inject_wheels=False (--deps replica) `image` is localeval's per-repo venv instead, and the
    harness's wheel streaming is disabled (it would shadow the pinned deps with the newest public
    wheels, e.g. starlette 1.6 for every fastapi commit); setup.py --fast-path still runs.
    """
    import shutil
    import subprocess
    import tarfile
    import tempfile
    import uuid

    from swegemma.sandbox import SubprocessManager

    image_sp = next(image.glob("lib/python3*/site-packages"))

    class DockerLikeSandbox(SubprocessManager):
        def start(self) -> str:
            sid = str(uuid.uuid4())[:12]
            root = Path(tempfile.mkdtemp(prefix=f"swegemma_sandbox_{sid}_", dir=str(self.base_dir) if self.base_dir else None))
            for d in ("workspace", "tmp", "wheels"):
                (root / d).mkdir(parents=True, exist_ok=True)
            if wheels_dir is not None:  # the image has COPY wheels/ /wheels/
                for w in wheels_dir.glob("*.whl"):
                    (root / "wheels" / w.name).symlink_to(w.resolve())
            venv_dir = root / "venv"
            subprocess.run([python, "-m", "venv", "--without-pip", str(venv_dir)], check=True)
            sp = next(venv_dir.glob("lib/python3*/site-packages"))
            (sp / "_image.pth").write_text(str(image_sp) + "\n")
            vpy = venv_dir / "bin" / "python3"
            for script in (image / "bin").iterdir():  # console scripts (pip, pytest, ...) bound to this venv
                if script.name.startswith(("python", "activate", "Activate")) or not script.is_file():
                    continue
                lines = script.read_text(errors="replace").splitlines(True)
                if lines and lines[0].startswith("#!"):
                    dst = venv_dir / "bin" / script.name
                    dst.write_text(f"#!{vpy}\n" + "".join(lines[1:]))
                    dst.chmod(0o755)
            (root / "tmp" / ".gitconfig").write_text(
                "[user]\n\temail = agent@eval\n\tname = Agent\n[init]\n\tdefaultBranch = main\n")
            with self._lock:
                self._sandboxes[sid] = {"root": root, "workspace": root / "workspace", "tmp": root / "tmp",
                                        "wheels": root / "wheels", "venv": venv_dir, "sp": sp}
                if self._default_sandbox_id is None:
                    self._default_sandbox_id = sid
            return sid

        def _sp(self, sid: str) -> Path:
            with self._lock:
                return self._sandboxes[sid]["sp"]

        def exec(self, sandbox_id: str, command: str, *, timeout: int | None = None):
            if DOCKER_SP in command:
                command = command.replace(DOCKER_SP, str(self._sp(sandbox_id)))
            return super().exec(sandbox_id, command, timeout=timeout)

    class DockerLikeSandboxWheels(DockerLikeSandbox):
        def _stream_tar_via_exec_socket(self, sandbox_id: str, fileobj, dest: str) -> bool:
            target = self._sp(sandbox_id) if dest.rstrip("/") == DOCKER_SP else Path(dest)
            with tarfile.open(fileobj=fileobj, mode="r|") as tf:
                tf.extractall(target, filter="fully_trusted")
            return True

        def extract_archive_to_container(self, sandbox_id: str, archive_path, dst_dir: str = "/workspace") -> bool:
            # Its presence is what makes the harness stream wheels; returning False keeps the stock
            # copy + tar fallback for snapshots.
            return False

    cls = DockerLikeSandboxWheels if inject_wheels else DockerLikeSandbox
    return cls(timeout_seconds=timeout_seconds, base_dir=base_dir, system_site_packages=False)


# ---------------------------------------------------------------- worker side

def build_registry(a: argparse.Namespace, bundle: Path | None):
    """VllmServer.create_model_registry, pointed at an external endpoint (no server is started)."""
    from adk_submission import VllmConfig, VllmServer, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS

    api_base = a.api_base.rstrip("/")

    class ExternalVllm(VllmServer):
        @property
        def base_url(self) -> str:  # the registry's LiteLlm api_base
            return api_base

    manifest = None
    if bundle is not None:
        manifest = discover_adapters(str(bundle), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
    served = a.served_model or a.model
    server = ExternalVllm(VllmConfig(model=served, enable_lora=True), adapter_manifest=manifest)
    server.effective_model_path = served
    return server.create_model_registry(aliases=[a.model], model_prefix="openai/", api_key=a.api_key)


def build_config(a: argparse.Namespace, bundle: Path | None, models):
    import yaml
    from google.adk.agents.context_cache_config import ContextCacheConfig
    from google.adk.apps._configs import EventsCompactionConfig
    from swegemma.config import EvalConfig, build_submission_limits

    ev: dict = {}
    if bundle is not None and (bundle / "eval_config.yaml").exists():
        ev = (yaml.safe_load((bundle / "eval_config.yaml").read_text()) or {}).get("evaluation", {}) or {}
    limits, gen_constraints = build_submission_limits()
    data = a.data
    graph_kw = {}
    if not a.no_graphs:
        graph_kw = dict(graph_dir=str(data / "graphs"), embeddings_dir=str(data / "embeddings"))
    else:
        graph_kw = dict(graph_dir=str(a.results / "_no_graphs"), embeddings_dir=str(a.results / "_no_graphs"))
    return EvalConfig(
        tasks_path=data / "tasks.jsonl", snapshots_dir=data / "snapshots", results_dir=a.results,
        submission_dir=bundle if bundle is not None else a.results, models=models, sandbox="subprocess",
        timeout_seconds=int(ev.get("timeout_seconds", 300)),
        max_time_minutes=a.max_time_minutes if a.max_time_minutes is not None else ev.get("max_time_minutes"),
        max_tool_calls=ev.get("max_tool_calls"), max_turns=ev.get("max_turns"),
        limits=limits, generation_constraints=gen_constraints,
        context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
        events_compaction_config=EventsCompactionConfig(
            compaction_interval=15, overlap_size=2, token_threshold=a.compaction_threshold, event_retention_size=5),
        wheels_dir=wheels_dir(a), verbose=False, display_mode="quiet", **graph_kw)


def wheels_dir(a: argparse.Namespace) -> Path:
    return a.data / "wheels_merged" if a.extra_wheels else a.data / "wheels"


def merge_wheels(a: argparse.Namespace) -> None:
    """<data>/wheels_merged = symlinks to <data>/wheels + --extra-wheels (public versions win on name clashes)."""
    import re
    import shutil
    merged = a.data / "wheels_merged"
    shutil.rmtree(merged, ignore_errors=True)
    merged.mkdir()
    norm = lambda n: re.sub(r"[-_.]+", "_", n.split("-", 1)[0]).lower()  # noqa: E731
    public = sorted((a.data / "wheels").glob("*.whl"))
    have = {norm(w.name) for w in public}
    for w in public + [w for w in sorted(a.extra_wheels.glob("*.whl")) if norm(w.name) not in have]:
        (merged / w.name).symlink_to(w.resolve())


def reset_wheel_cache(wdir: Path) -> None:
    """The harness caches unpacked wheels in $TMPDIR/swegemma_sp_cache_v8 by a fixed name (not by content)."""
    import hashlib
    import shutil
    import tempfile
    cache = Path(tempfile.gettempdir()) / "swegemma_sp_cache_v8"
    fp = hashlib.sha1("\n".join(sorted(p.name for p in wdir.glob("*.whl"))).encode()).hexdigest()
    stamp = cache / ".wheelset"
    if not stamp.exists() or stamp.read_text() != fp:
        shutil.rmtree(cache, ignore_errors=True)
        cache.mkdir(parents=True, exist_ok=True)
        stamp.write_text(fp)


def replica_venv(task, data: Path) -> Path:
    """localeval's shared per-repo venv for this task's dependency files (built with uv if missing)."""
    import tarfile
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from localeval import env as lenv

    with tempfile.TemporaryDirectory() as td:
        wanted = set(lenv.DEP_FILES)
        with tarfile.open(data / "snapshots" / f"{task.instance_id}.tgz", "r|gz") as tf:
            for m in tf:
                name = m.name[2:] if m.name.startswith("./") else m.name
                if m.isfile() and name in wanted:
                    dst = Path(td) / name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(tf.extractfile(m).read())
        return lenv.venv_for({"repo": task.repo, "instance_id": task.instance_id}, Path(td))


def _setup_logging(path: Path) -> None:
    import logging
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.FileHandler(path, mode="w", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(h)
    root.setLevel(logging.INFO)
    for noisy in ("httpx", "httpcore", "LiteLLM", "litellm", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def run_one(job: tuple) -> dict:
    """Evaluate one task in this (fresh) worker process. Returns the lab-format row."""
    a, tid, index, total = job
    import asyncio

    _setup_logging(a.results / "worker_logs" / f"{tid}.log")
    t0 = time.time()
    try:
        import litellm
        from adk_eval_core.tracing import SessionTrace
        from swegemma.evaluate import Evaluator
        from swegemma.models import load_tasks
        from swegemma.sandbox import SubprocessManager

        litellm.drop_params = True
        bundle = a.bundle.resolve() if a.bundle is not None else None
        models = build_registry(a, bundle)
        cfg = build_config(a, bundle, models)
        tasks = {t.instance_id: t for t in load_tasks(cfg.tasks_path)}
        task = tasks[tid]

        if a.phase2_only:
            patch_text = task.patch if a.phase2_only == "gold" else ""

            class Phase2Evaluator(Evaluator):
                async def _run_agent_sandbox(self, task, snapshot_path, task_index, total_tasks, **kw):
                    return patch_text, None, SessionTrace()

            evaluator = Phase2Evaluator(cfg)
        else:
            evaluator = Evaluator(cfg)
        cmd_timeout = cfg.harness.command_timeout_seconds or 300
        if a.sandbox_env == "docker-like":
            if a.deps == "replica":
                layer = replica_venv(task, a.data)
                python = str((layer / "bin" / "python").resolve())
            else:
                layer, python = a.data / "image313", a.python313
            evaluator.sandbox = evaluator.docker = make_docker_like_manager(
                layer, python, cmd_timeout, a.workdir, cfg.wheels_dir, inject_wheels=a.deps == "image")
        elif a.workdir is not None:
            evaluator.sandbox = evaluator.docker = SubprocessManager(timeout_seconds=cmd_timeout, base_dir=a.workdir)

        r = asyncio.run(evaluator.evaluate_task(task=task, task_index=index, total_tasks=total))
        row = {
            "bundle": str(a.bundle) if a.bundle else f"phase2:{a.phase2_only}", "id": tid,
            "resolved": bool(r.resolved), "status": getattr(r, "status", None),
            "patch_chars": len(r.agent_patch or ""), "tool_calls": r.tool_calls,
            "llm_calls": getattr(r, "total_llm_calls", None), "tokens": getattr(r, "total_tokens", None),
            "task_seconds": round(r.duration_seconds or 0, 1), "wall_seconds": round(time.time() - t0, 1),
            "error": str(getattr(r, "error_message", None) or "")[:2000],
            "test_exit_code": r.test_exit_code, "test_tail": (r.test_output or "")[-1500:],
            "trace": getattr(r, "trace_path", None), "patch": r.agent_patch or "",
        }
        (a.results / "patches").mkdir(parents=True, exist_ok=True)
        (a.results / "patches" / f"{tid}.patch").write_text(r.agent_patch or "")
        (a.results / "test_outputs").mkdir(parents=True, exist_ok=True)
        (a.results / "test_outputs" / f"{tid}.log").write_text(r.test_output or "")
    except BaseException:  # noqa: BLE001 - a crashed task is a row, not a crashed run
        row = {"bundle": str(a.bundle), "id": tid, "resolved": False, "status": "crash",
               "error": "CRASH " + traceback.format_exc()[-3000:], "patch": "",
               "wall_seconds": round(time.time() - t0, 1)}
    return row


# ---------------------------------------------------------------- driver

def main(argv=None) -> None:
    a = parse_args(argv)
    a.results = a.results.resolve()
    a.data = a.data.resolve()
    a.results.mkdir(parents=True, exist_ok=True)
    for need in ("tasks.jsonl", "snapshots", "wheels", "sandbox/setup.py"):
        if not (a.data / need).exists():
            sys.exit(f"missing {a.data / need}")
    missing = [t for t in a.ids if not (a.data / "snapshots" / f"{t}.tgz").exists()]
    if missing:
        sys.exit(f"missing snapshots for: {' '.join(missing)}")

    if a.workdir is not None:
        a.workdir = a.workdir.resolve()
        a.workdir.mkdir(parents=True, exist_ok=True)
    if a.sandbox_env == "docker-like":
        prepare_image(a.data, a.python313)
    if a.extra_wheels:
        a.extra_wheels = a.extra_wheels.resolve()
        merge_wheels(a)

    reset_wheel_cache(wheels_dir(a))

    out = a.results / "results.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(l)["id"] for l in out.read_text().splitlines() if l.strip()}
    todo = [t for t in a.ids if t not in done]
    print(f"{len(todo)} task(s) to run ({len(done)} already in {out}), jobs={a.jobs}, "
          f"endpoint={a.api_base if not a.phase2_only else 'none (phase2-only ' + a.phase2_only + ')'}", flush=True)
    jobs = [(a, tid, i, len(a.ids)) for i, tid in enumerate(todo, 1)]
    ctx = mp.get_context("spawn")
    resolved = 0
    t0 = time.time()
    # maxtasksperchild=1: every task gets a fresh interpreter (no shared ADK/litellm state).
    with ctx.Pool(processes=max(1, a.jobs), maxtasksperchild=1) as pool:
        for row in pool.imap_unordered(run_one, jobs):
            with out.open("a") as f:
                f.write(json.dumps(row) + "\n")
            resolved += bool(row.get("resolved"))
            print(f"{time.strftime('%H:%M:%S')} {row['id']:<16} resolved={row.get('resolved')!s:<5} "
                  f"patch={row.get('patch_chars', 0):>6} tools={row.get('tool_calls')} llm={row.get('llm_calls')} "
                  f"s={row.get('task_seconds', row.get('wall_seconds'))} {str(row.get('error', ''))[:140]!r}",
                  flush=True)
    print(f"done: {resolved}/{len(todo)} resolved in {time.time() - t0:.0f}s -> {out}", flush=True)


if __name__ == "__main__":
    main()
