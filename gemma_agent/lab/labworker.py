"""Concurrent lab runner: one OS process per task-run against a single vLLM server.

make_lab.py --concurrency N embeds this file into the Kaggle kernel as
/kaggle/working/labworker.py. The kernel imports it and calls run_pool(); run_pool
starts `python labworker.py <job.json>` N at a time (subprocess.Popen), and each
worker evaluates exactly one (bundle, replicate, task) with Evaluator.evaluate_task,
exactly as the sequential kernel does, but in a fresh interpreter.

Why processes: harness tools are synchronous and run on the asyncio event loop
(swegemma/tools/execution.py:42 -> SubprocessManager.exec), so concurrent tasks in one
process freeze each other while their clocks keep running (research:lab-throughput).

Virtual clock (job['clock'] == 'virtual'). Patched in the worker process only, the
submission and the prompt are untouched (eval_config time_minutes stays nominal):
  * swegemma.context.SwegemmaContext.agent_elapsed_seconds (property, context.py:435-445)
    -> per_call * llm_calls_used + per_token * completion tokens + sandbox exec seconds
    measured while the agent session is active. elapsed_seconds and
    remaining_time_seconds (context.py:452-463) read it via self, so the harness loop
    checks `context.elapsed_seconds > timeout_sec` (agent_runner.py:583, 641), the
    run_command timeout cap (tools/execution.py:29) and get_status (execution.py:120-122)
    all see virtual time. The loop then stops at the virtual limit and the normal
    git-diff fallback runs.
  * completion tokens: SwegemmaContext.handle_adk_event is wrapped (context.py:210);
    usage_metadata.candidates_token_count (= vLLM completion_tokens incl. reasoning,
    google/adk/models/lite_llm.py:1686) of non-partial model events, de-duplicated by
    (event id, partial) like the harness does (context.py:215-221).
  * tool seconds: swegemma.sandbox.subprocess.SubprocessManager.exec (subprocess.py:418)
    is wrapped (re-entrancy safe); counted only between start_agent_session and
    stop_agent_session (context.py:183-193), which are wrapped too.
  * real safety cap: swegemma.harness.agent_runner.asyncio is replaced by a proxy whose
    timeout(d) returns asyncio.timeout(d * real_factor) (agent_runner.py:439-441; the
    only asyncio.timeout in the agent loop). Everything else is delegated to asyncio.
  * skill-script executor: adk_eval_core.sandbox.base.AdkSandboxCodeExecutor.execute_code
    compares REAL perf_counter time to max_time_minutes (base.py:188-190); its
    max_time_minutes is scaled by real_factor for the duration of the call.
Clock 'scaled' is the documented fallback (real cap = nominal x measured slowdown):
agent_elapsed_seconds = real elapsed / wall_scale and asyncio.timeout(d * wall_scale).
Clock 'real' changes nothing (virtual seconds are still measured and reported).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

PER_CALL_S = 0.95
PER_TOKEN_S = 0.0287


def virtual_seconds(llm_calls: int, completion_tokens: int, tool_seconds: float,
                    per_call: float = PER_CALL_S, per_token: float = PER_TOKEN_S) -> float:
    """Sequential-Kaggle-equivalent agent time (token clock + measured tool time)."""
    return per_call * max(0, int(llm_calls)) + per_token * max(0, int(completion_tokens)) + max(0.0, float(tool_seconds))


# ------------------------------------------------------------------ clock patches (worker process)

class _ClockState:
    def __init__(self) -> None:
        self.ctx = None
        self.tokens = 0
        self.tool_s = 0.0
        self.active = False
        self.seen: set = set()
        self.v_at_submit = None
        self.local = threading.local()


class _AsyncioProxy:
    """Stand-in for the `asyncio` module inside swegemma.harness.agent_runner."""

    def __init__(self, factor: float) -> None:
        self._factor = float(factor)

    def timeout(self, delay):
        return asyncio.timeout(None if delay is None else delay * self._factor)

    def __getattr__(self, name):
        return getattr(asyncio, name)


def install_clock(mode: str = "virtual", per_call: float = PER_CALL_S, per_token: float = PER_TOKEN_S,
                  real_factor: float = 3.0, wall_scale: float = 1.0) -> _ClockState:
    """Patch the harness in THIS process. mode: 'virtual' | 'scaled' | 'real' (measure only)."""
    from adk_eval_core.sandbox import base as core_base
    from swegemma import context as ctxmod
    from swegemma.harness import agent_runner
    from swegemma.sandbox.subprocess import SubprocessManager

    st = _ClockState()
    C = ctxmod.SwegemmaContext
    orig_start, orig_stop, orig_handle = C.start_agent_session, C.stop_agent_session, C.handle_adk_event
    orig_elapsed = C.__dict__["agent_elapsed_seconds"]
    orig_exec = SubprocessManager.exec

    def vnow(ctx) -> float:
        return virtual_seconds(getattr(ctx, "llm_calls_used", 0), st.tokens, st.tool_s, per_call, per_token)

    def start_agent_session(self):
        st.ctx, st.tokens, st.tool_s, st.v_at_submit = self, 0, 0.0, None
        st.seen.clear()
        orig_start(self)
        st.active = True

    def stop_agent_session(self):
        st.active = False
        orig_stop(self)

    def handle_adk_event(self, event, agent_name=None):
        try:
            if event is not None and st.active and not getattr(event, "partial", False):
                key = getattr(event, "id", None) or id(event)
                content = getattr(event, "content", None)
                author = getattr(event, "author", None)
                role = getattr(content, "role", None) if content is not None else None
                usage = getattr(event, "usage_metadata", None)
                if (key not in st.seen and usage is not None and author not in (None, "user", "harness", "system", "tool")
                        and role not in ("user", "tool")):
                    st.seen.add(key)
                    st.tokens += int(getattr(usage, "candidates_token_count", 0) or 0)
        except Exception:  # noqa: BLE001 - the clock must never break the run
            pass
        orig_handle(self, event, agent_name=agent_name)
        try:
            if st.v_at_submit is None and getattr(self, "patch_submitted", False):
                st.v_at_submit = round(vnow(self), 1)
        except Exception:  # noqa: BLE001
            pass

    def exec_timed(self, *args, **kwargs):
        depth = getattr(st.local, "depth", 0)
        st.local.depth = depth + 1
        t0 = time.perf_counter()
        try:
            return orig_exec(self, *args, **kwargs)
        finally:
            st.local.depth = depth
            if depth == 0 and st.active:
                st.tool_s += time.perf_counter() - t0

    C.start_agent_session = start_agent_session
    C.stop_agent_session = stop_agent_session
    C.handle_adk_event = handle_adk_event
    SubprocessManager.exec = exec_timed

    if mode == "virtual":
        def agent_elapsed_seconds(self):
            if self.agent_start_time is None:
                return 0.0
            return vnow(self)
        C.agent_elapsed_seconds = property(agent_elapsed_seconds)
        factor = real_factor
    elif mode == "scaled":
        def agent_elapsed_seconds(self):
            return orig_elapsed.fget(self) / wall_scale
        C.agent_elapsed_seconds = property(agent_elapsed_seconds)
        factor = wall_scale
    else:
        factor = 1.0

    if factor != 1.0:
        agent_runner.asyncio = _AsyncioProxy(factor)
        Exe = core_base.AdkSandboxCodeExecutor
        orig_execute = Exe.execute_code

        def execute_code(self, invocation_context, code_execution_input):
            nominal = self.max_time_minutes
            if nominal is None:
                return orig_execute(self, invocation_context, code_execution_input)
            self.max_time_minutes = nominal * factor
            try:
                return orig_execute(self, invocation_context, code_execution_input)
            finally:
                self.max_time_minutes = nominal
        Exe.execute_code = execute_code
    st.mode, st.real_factor = mode, factor
    return st


# ------------------------------------------------------------------ one task-run (worker process)

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


def build_registry(api_base: str, served_model: str, alias: str, bundle: Path):
    """VllmServer.create_model_registry pointed at the already-running server (as run_official.py)."""
    from adk_submission import VllmConfig, VllmServer, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS
    base = api_base.rstrip("/")

    class ExternalVllm(VllmServer):
        @property
        def base_url(self) -> str:
            return base

    manifest = discover_adapters(str(bundle), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
    server = ExternalVllm(VllmConfig(model=served_model, enable_lora=True), adapter_manifest=manifest)
    server.effective_model_path = served_model
    return server.create_model_registry(aliases=[alias], model_prefix="openai/", api_key="EMPTY")


def run_job(job: dict) -> dict:
    """Evaluate one task-run; returns the results.jsonl row (existing kernel format + extras)."""
    t1 = time.time()
    res_dir = Path(job["results_dir"])
    tid = job["task_id"]
    base = {"bundle": job["bundle"], "id": tid, "replicate": job.get("replicate", 0)}
    _setup_logging(res_dir / "worker_logs" / f"{tid}.log")
    st = None
    try:
        st = install_clock(job.get("clock", "real"), job.get("per_call", PER_CALL_S), job.get("per_token", PER_TOKEN_S),
                           job.get("real_factor", 3.0), job.get("wall_scale", 1.0))
        import litellm
        import yaml
        from google.adk.agents.context_cache_config import ContextCacheConfig
        from google.adk.apps._configs import EventsCompactionConfig
        from swegemma.config import EvalConfig, build_submission_limits
        from swegemma.evaluate import Evaluator
        from swegemma.models import load_tasks
        litellm.drop_params = True

        data = Path(job["data_dir"])
        agent_dir = Path(job["bundle_dir"])
        ev = (yaml.safe_load((agent_dir / "eval_config.yaml").read_text()) or {}).get("evaluation", {}) \
            if (agent_dir / "eval_config.yaml").exists() else {}
        ev = ev or {}
        models = build_registry(job["api_base"], job["served_model"], job.get("alias", "gemma-4-31b-it-qat-w4a16-ct"), agent_dir)
        limits, gen_constraints = build_submission_limits()
        cfg = EvalConfig(
            tasks_path=data / "tasks.jsonl", snapshots_dir=data / "snapshots", results_dir=res_dir,
            submission_dir=agent_dir, models=models, sandbox="subprocess",
            timeout_seconds=int(ev.get("timeout_seconds", 300)), max_time_minutes=ev.get("max_time_minutes"),
            max_tool_calls=ev.get("max_tool_calls"), max_turns=ev.get("max_turns"),
            limits=limits, generation_constraints=gen_constraints,
            context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
            events_compaction_config=EventsCompactionConfig(compaction_interval=15, overlap_size=2,
                                                            token_threshold=14336, event_retention_size=5),
            graph_dir=str(data / "graphs"), embeddings_dir=str(data / "embeddings"),
            wheels_dir=Path(job.get("wheels_dir") or data / "wheels"), verbose=False, display_mode="quiet")
        task = {t.instance_id: t for t in load_tasks(cfg.tasks_path)}[tid]
        evaluator = Evaluator(cfg)
        r = asyncio.run(evaluator.evaluate_task(task=task, task_index=job.get("task_index", 1),
                                                total_tasks=job.get("total_tasks", 1)))
        row = dict(base, **{
            "resolved_kaggle_env": bool(r.resolved), "status": r.status,
            "patch_chars": len(r.agent_patch or ""), "tool_calls": r.tool_calls,
            "llm_calls": r.total_llm_calls, "tokens": r.total_tokens,
            "task_seconds": round(r.duration_seconds or 0, 1), "wall_seconds": round(time.time() - t1, 1),
            "error": str(r.error_message or "")[:800], "test_tail": (r.test_output or "")[-1500:],
            "patch": r.agent_patch or ""})
    except BaseException:  # noqa: BLE001 - a crashed task is a row
        row = dict(base, error="CRASH " + traceback.format_exc()[-1500:], patch="",
                   wall_seconds=round(time.time() - t1, 1))
    if st is not None:
        ctx = st.ctx
        calls = getattr(ctx, "llm_calls_used", 0) if ctx is not None else 0
        row.update({
            "virtual_seconds": round(virtual_seconds(calls, st.tokens, st.tool_s, job.get("per_call", PER_CALL_S),
                                                     job.get("per_token", PER_TOKEN_S)), 1) if ctx is not None else None,
            "virtual_at_submit": st.v_at_submit, "clock": st.mode, "real_cap_factor": st.real_factor,
            "vc_llm_calls": calls, "vc_completion_tokens": st.tokens, "vc_tool_seconds": round(st.tool_s, 1),
            "real_agent_seconds": round((ctx.agent_end_time or time.perf_counter()) - ctx.agent_start_time, 1)
            if ctx is not None and getattr(ctx, "agent_start_time", None) is not None else None,
        })
    else:
        row.setdefault("virtual_seconds", None)
    return row


def worker_main(job_path: str) -> int:
    job = json.loads(Path(job_path).read_text())
    row = run_job(job)
    tmp = Path(job["row_path"] + ".tmp")
    tmp.write_text(json.dumps(row))
    os.replace(tmp, job["row_path"])
    return 0


# ------------------------------------------------------------------ orchestrator (kernel process)

def plan_jobs(bundle_names: list[str], task_ids: list[str], replicates: int = 1, seed: int = 0) -> list[tuple]:
    """(task, replicate, bundle) task-major; bundle order shuffled per (task, replicate) for equal load."""
    rng = random.Random(seed)
    out = []
    for tid in task_ids:
        for rep in range(replicates):
            order = list(bundle_names)
            rng.shuffle(order)
            out += [(tid, rep, b) for b in order]
    return out


def parse_metrics(text: str) -> dict:
    """Pick the scheduler/KV gauges out of a Prometheus /metrics page (sums over label sets)."""
    want = {"vllm:num_requests_running": "running", "vllm:num_requests_waiting": "waiting",
            "vllm:gpu_cache_usage_perc": "kv_usage_old", "vllm:kv_cache_usage_perc": "kv_usage",
            "vllm:num_preemptions_total": "preemptions", "vllm:generation_tokens_total": "gen_tokens",
            "vllm:prompt_tokens_total": "prompt_tokens"}
    out: dict = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name = line.split("{", 1)[0].split(" ", 1)[0]
        key = want.get(name)
        if key is None:
            continue
        try:
            out[key] = out.get(key, 0.0) + float(line.rsplit(" ", 1)[1])
        except ValueError:
            pass
    if "kv_usage_old" in out:  # older vLLM name; some versions export both during deprecation
        out["kv_usage"] = max(out.pop("kv_usage_old"), out.get("kv_usage", 0.0))
    return out


class MetricsLogger(threading.Thread):
    def __init__(self, url: str, path: Path, log, interval: float = 30.0, active_fn=None) -> None:
        super().__init__(daemon=True)
        self.url, self.path, self.log, self.interval, self.active_fn = url, path, log, interval, active_fn
        self.stop_event = threading.Event()

    def run(self) -> None:
        import urllib.request
        while not self.stop_event.is_set():
            rec = {"t": round(time.time(), 1)}
            try:
                with urllib.request.urlopen(self.url, timeout=10) as resp:
                    rec.update(parse_metrics(resp.read().decode("utf-8", "replace")))
            except Exception as exc:  # noqa: BLE001
                rec["error"] = str(exc)[:200]
            try:
                rec["load1"] = os.getloadavg()[0]
            except OSError:
                pass
            if self.active_fn is not None:
                rec["active_jobs"] = self.active_fn()
            with self.path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            self.log("metrics", " ".join(f"{k}={v:.3g}" if isinstance(v, float) else f"{k}={v}"
                                         for k, v in rec.items() if k != "t"))
            self.stop_event.wait(self.interval)


def run_pool(jobs: list[dict], concurrency: int, out: Path, log, python: str = sys.executable,
             worker_path: str | None = None, metrics_url: str | None = None, metrics_interval: float = 30.0,
             kill_after: float = 3600.0, poll: float = 1.0) -> list[dict]:
    """Run job dicts N at a time as `python labworker.py job.json`; append rows to out/results.jsonl."""
    worker_path = worker_path or os.path.abspath(__file__)
    jobs_dir = out / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    pending = list(jobs)
    running: list[tuple] = []
    rows: list[dict] = []
    mlog = None
    if metrics_url:
        mlog = MetricsLogger(metrics_url, out / "metrics.jsonl", log, metrics_interval, lambda: len(running))
        mlog.start()
    try:
        while pending or running:
            while pending and len(running) < max(1, concurrency):
                job = pending.pop(0)
                stem = f"{job['bundle']}__r{job.get('replicate', 0)}__{job['task_id']}"
                job["row_path"] = str(jobs_dir / f"{stem}.row.json")
                jp = jobs_dir / f"{stem}.job.json"
                jp.write_text(json.dumps(job))
                lf = (jobs_dir / f"{stem}.out").open("w")
                p = subprocess.Popen([python, worker_path, str(jp)], stdout=lf, stderr=subprocess.STDOUT,
                                     start_new_session=True)
                running.append((p, job, lf, time.time(), stem))
                log("start", stem, "active", len(running), "left", len(pending))
            time.sleep(poll)
            still = []
            for p, job, lf, t0, stem in running:
                rc = p.poll()
                if rc is None and time.time() - t0 > kill_after:
                    try:
                        os.killpg(p.pid, 9)
                    except OSError:
                        p.kill()
                    rc = p.wait()
                    rc = f"killed after {kill_after:.0f}s"
                if rc is None:
                    still.append((p, job, lf, t0, stem))
                    continue
                lf.close()
                rp = Path(job["row_path"])
                try:
                    row = json.loads(rp.read_text())
                except Exception:  # noqa: BLE001
                    tail = ""
                    try:
                        tail = (jobs_dir / f"{stem}.out").read_text(errors="replace")[-1500:]
                    except OSError:
                        pass
                    row = {"bundle": job["bundle"], "id": job["task_id"], "replicate": job.get("replicate", 0),
                           "error": f"CRASH worker rc={rc} no row\n{tail}", "patch": "", "virtual_seconds": None,
                           "wall_seconds": round(time.time() - t0, 1)}
                rows.append(row)
                with (out / "results.jsonl").open("a") as f:
                    f.write(json.dumps(row) + "\n")
                log(row["bundle"], "r%s" % row.get("replicate", 0), row["id"],
                    "patch" if row.get("patch") else "NO-PATCH", "calls", row.get("tool_calls"),
                    "llm", row.get("llm_calls"), "task_s", row.get("task_seconds"), "virt_s", row.get("virtual_seconds"),
                    "wall_s", row.get("wall_seconds"), str(row.get("error", ""))[:120])
            running = still
    finally:
        if mlog is not None:
            mlog.stop_event.set()
        for p, *_ in running:
            try:
                p.kill()
            except OSError:
                pass
    return rows


if __name__ == "__main__":
    sys.exit(worker_main(sys.argv[1]))
