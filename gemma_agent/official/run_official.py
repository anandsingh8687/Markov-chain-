"""Run agent bundles through the OFFICIAL swegemma harness, locally, against an external model endpoint.

This is the same pipeline the Kaggle scorer runs (Evaluator.evaluate_task: Container A agent loop,
patch extraction, Container B verification), built the same way as the host notebook / our lab
kernel (gemma_agent/lab/make_lab.py), except:
  * the model registry points at an external OpenAI-compatible endpoint (--api-base) instead of a
    VllmServer started in-process (VllmServer.create_model_registry is reused unchanged);
  * sandbox='subprocess' (no docker daemon here);
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
        wheels_dir=data / "wheels", verbose=False, display_mode="quiet", **graph_kw)


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
        if a.workdir is not None:
            a.workdir.mkdir(parents=True, exist_ok=True)
            evaluator.sandbox = evaluator.docker = SubprocessManager(
                timeout_seconds=cfg.harness.command_timeout_seconds or 300, base_dir=a.workdir)

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
