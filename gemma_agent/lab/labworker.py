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
    -> LLM seconds + measured sandbox exec seconds (see _ClockState). LLM seconds are charged per
    model call the harness counts (llm_calls_used, context.py:283-298): per_call + per_token x
    completion tokens (usage_metadata.candidates_token_count). Calls are charged per ADK branch:
    the branches of a ParallelAgent overlap, so a parallel epoch costs max over branches (x1.15
    while two streams decode at once), not their sum. elapsed_seconds and remaining_time_seconds
    (context.py:452-463) read it via self, so the harness loop checks `context.elapsed_seconds >
    timeout_sec` (agent_runner.py:583, 641), the run_command timeout cap (tools/execution.py:29)
    and get_status (execution.py:120-122) all see virtual time. The loop then stops at the virtual
    limit and the normal git-diff fallback runs.
  * constants: by default 0.164 s/call + 0.0221 s/token, refit WITHOUT tool time on the sequential
    Kaggle logs, plus the measured tool seconds (tool_seconds=True). The older 0.95 s/call +
    0.0287 s/token was fitted on total task time and already holds the average tool time, so it is
    used only with tool_seconds=False (then no measured tool time is added).
  * tool seconds: swegemma.sandbox.subprocess.SubprocessManager.exec (subprocess.py:418)
    is wrapped (re-entrancy safe); counted only between start_agent_session and
    stop_agent_session (context.py:183-193), which are wrapped too. Rows report vc_tool_seconds
    and load1 (contention inflates tool seconds when N tasks share the CPUs).
  * the helper tools' clock: before every sandbox exec the worker writes <sandbox tmp>/.swe_vclock
    = {"v": agent_elapsed_seconds, "wall": time.time(), "rate": clock s per real s}; the bundle
    tools (skill_src/swe_tools/tools/_ws.py vclock/elapsed/cap) prefer it over their own wall clock
    anchored on the _swegemma_baseline commit, so their LOW TIME / deadline / timeout caps follow the
    same clock as the harness. The real harness never writes the file.
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

# Token clock. Default: LLM time only (refit WITHOUT tool time on the 76 lab5/6/7a/7b sequential Kaggle tasks
# that ended before 285 s: T - measured tool seconds = 0.164 s/call + 0.0221 s/completion token, R^2 0.82 on T)
# plus the measured sandbox seconds. The older 0.95 s/call + 0.0287 s/token was fitted on TOTAL task time, so it
# already holds the average tool time: it is only used with tool_seconds=False (no measured tool time added).
PER_CALL_S = 0.164
PER_TOKEN_S = 0.0221
TOKEN_ONLY_PER_CALL_S = 0.95
TOKEN_ONLY_PER_TOKEN_S = 0.0287
# Two model streams at once (ParallelAgent branches) decode in one vLLM batch: each call is ~15% slower than
# alone (research:lab-throughput / design: serial + max(branch clocks) x 1.15).
PARALLEL_SLOWDOWN = 1.15
PARALLEL_WINDOW_S = 30.0  # another branch counts as running if it made a model call within this many real s
VCLOCK_FILE = ".swe_vclock"  # <sandbox tmp>/.swe_vclock: the helper tools read the clock from here (_ws.vclock)


def virtual_seconds(llm_calls: int, completion_tokens: int, tool_seconds: float,
                    per_call: float = PER_CALL_S, per_token: float = PER_TOKEN_S) -> float:
    """Sequential-Kaggle-equivalent agent time of ONE model stream (token clock + measured tool time)."""
    return per_call * max(0, int(llm_calls)) + per_token * max(0, int(completion_tokens)) + max(0.0, float(tool_seconds))


# ------------------------------------------------------------------ clock patches (worker process)

class _ClockState:
    """Branch-aware virtual clock.

    Model calls are charged per ADK branch (Event.branch: '' for agents outside a ParallelAgent, e.g.
    'attempts.attempt_a_loop' inside one). Calls of parallel branches overlap in time, so a run of branch
    events (an epoch) costs max over branches, each call x PARALLEL_SLOWDOWN while another branch is active;
    a serial (no-branch) model event closes the epoch. Tools run synchronously on the one event loop and block
    every branch, so measured tool seconds are added once, in full.
    """

    def __init__(self) -> None:
        self.ctx = None
        self.tokens = 0
        self.calls = 0
        self.tool_s = 0.0
        self.active = False
        self.seen: set = set()
        self.v_at_submit = None
        self.local = threading.local()
        self.per_call, self.per_token, self.count_tools = PER_CALL_S, PER_TOKEN_S, True
        self.mode, self.real_factor, self.wall_scale = "real", 1.0, 1.0
        self.committed = 0.0  # closed epochs and serial calls (LLM part only)
        self.epoch: dict = {}  # branch -> LLM seconds in the open parallel epoch
        self.last_call_wall: dict = {}  # branch -> time.time() of its latest model call
        self.branch_calls: dict = {}
        self.text_turns: list = []  # (branch, virtual s, before submit) of text-only model turns
        self.loads: list = []
        self.sandbox_tmp: dict = {}

    def reset(self, ctx) -> None:
        self.ctx, self.tokens, self.calls, self.tool_s, self.v_at_submit = ctx, 0, 0, 0.0, None
        self.committed, self.epoch, self.last_call_wall, self.branch_calls = 0.0, {}, {}, {}
        self.text_turns, self.loads = [], []
        self.seen.clear()

    def charge_call(self, branch: str, tokens: int) -> None:
        cost = self.per_call + self.per_token * max(0, int(tokens))
        now = time.time()
        self.calls += 1
        self.tokens += max(0, int(tokens))
        self.branch_calls[branch] = self.branch_calls.get(branch, 0) + 1
        if not branch:
            if self.epoch:
                self.committed += max(self.epoch.values())
                self.epoch = {}
            self.committed += cost
        else:
            others = [b for b, t in self.last_call_wall.items() if b and b != branch and now - t <= PARALLEL_WINDOW_S]
            self.epoch[branch] = self.epoch.get(branch, 0.0) + cost * (PARALLEL_SLOWDOWN if others else 1.0)
        self.last_call_wall[branch] = now

    def llm_seconds(self) -> float:
        return self.committed + (max(self.epoch.values()) if self.epoch else 0.0)

    def vnow(self) -> float:
        return self.llm_seconds() + (self.tool_s if self.count_tools else 0.0)


class _AsyncioProxy:
    """Stand-in for the `asyncio` module inside swegemma.harness.agent_runner."""

    def __init__(self, factor: float) -> None:
        self._factor = float(factor)

    def timeout(self, delay):
        return asyncio.timeout(None if delay is None else delay * self._factor)

    def __getattr__(self, name):
        return getattr(asyncio, name)


def _is_text_turn(event) -> bool:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    if any(getattr(p, "function_call", None) or getattr(p, "function_response", None) for p in parts):
        return False
    return any((getattr(p, "text", None) or "").strip() and not getattr(p, "thought", False) for p in parts)


def install_clock(mode: str = "virtual", per_call: float | None = None, per_token: float | None = None,
                  real_factor: float = 3.0, wall_scale: float = 1.0, tool_seconds: bool = True) -> _ClockState:
    """Patch the harness in THIS process. mode: 'virtual' | 'scaled' | 'real' (measure only).

    tool_seconds=True: LLM-only constants (PER_CALL_S / PER_TOKEN_S) + measured sandbox seconds.
    tool_seconds=False: the total-time token clock (0.95 s/call + 0.0287 s/token), no measured tool time.
    """
    from adk_eval_core.sandbox import base as core_base
    from swegemma import context as ctxmod
    from swegemma.harness import agent_runner
    from swegemma.sandbox.subprocess import SubprocessManager

    st = _ClockState()
    st.count_tools = bool(tool_seconds)
    st.per_call = per_call if per_call is not None else (PER_CALL_S if tool_seconds else TOKEN_ONLY_PER_CALL_S)
    st.per_token = per_token if per_token is not None else (PER_TOKEN_S if tool_seconds else TOKEN_ONLY_PER_TOKEN_S)
    C = ctxmod.SwegemmaContext
    orig_start, orig_stop, orig_handle = C.start_agent_session, C.stop_agent_session, C.handle_adk_event
    orig_elapsed = C.__dict__["agent_elapsed_seconds"]
    orig_exec = SubprocessManager.exec

    def start_agent_session(self):
        st.reset(self)
        orig_start(self)
        st.active = True

    def stop_agent_session(self):
        st.active = False
        orig_stop(self)

    def handle_adk_event(self, event, agent_name=None):
        before = getattr(self, "llm_calls_used", 0)
        orig_handle(self, event, agent_name=agent_name)
        try:
            # an LLM call exactly when the harness counted one (context.py handle_adk_event, step 2)
            if event is not None and st.active and getattr(self, "llm_calls_used", 0) > before:
                key = getattr(event, "id", None) or id(event)
                if key not in st.seen:
                    st.seen.add(key)
                    usage = getattr(event, "usage_metadata", None)
                    toks = int(getattr(usage, "candidates_token_count", 0) or 0) if usage is not None else 0
                    branch = getattr(event, "branch", None) or ""
                    st.charge_call(branch, toks)
                    if _is_text_turn(event):
                        st.text_turns.append((branch, round(st.vnow(), 1), not getattr(self, "patch_submitted", False)))
            if st.v_at_submit is None and getattr(self, "patch_submitted", False):
                st.v_at_submit = round(st.vnow(), 1)
        except Exception:  # noqa: BLE001 - the clock must never break the run
            pass

    def _publish(self, sandbox_id) -> None:
        """Write the harness clock for the helper tools into the sandbox's tmp dir (read by _ws.vclock)."""
        if st.mode == "real" or not st.active or st.ctx is None:
            return
        try:
            tmp = st.sandbox_tmp.get(sandbox_id)
            if tmp is None:
                with self._lock:
                    tmp = str(self._sandboxes[sandbox_id]["tmp"])
                st.sandbox_tmp[sandbox_id] = tmp
            v = st.ctx.agent_elapsed_seconds
            rate = 1.0 if st.mode == "virtual" else 1.0 / st.wall_scale
            path = os.path.join(tmp, VCLOCK_FILE)
            with open(path + ".tmp", "w") as fh:
                json.dump({"v": round(float(v), 3), "wall": time.time(), "rate": rate}, fh)
            os.replace(path + ".tmp", path)
        except Exception:  # noqa: BLE001
            pass

    def exec_timed(self, *args, **kwargs):
        depth = getattr(st.local, "depth", 0)
        st.local.depth = depth + 1
        if depth == 0:
            _publish(self, args[0] if args else kwargs.get("sandbox_id"))
            if st.active:
                try:
                    st.loads.append(os.getloadavg()[0])
                except OSError:
                    pass
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
            return st.vnow()
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
    st.mode, st.real_factor, st.wall_scale = mode, factor, wall_scale
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
        st = install_clock(job.get("clock", "real"), job.get("per_call"), job.get("per_token"),
                           job.get("real_factor", 3.0), job.get("wall_scale", 1.0), job.get("tool_seconds", True))
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
        before_submit = [t for t in st.text_turns if t[2]]
        row.update({
            "virtual_seconds": round(st.vnow(), 1) if ctx is not None else None,
            "virtual_at_submit": st.v_at_submit, "clock": st.mode, "real_cap_factor": st.real_factor,
            "vc_per_call": st.per_call, "vc_per_token": st.per_token, "vc_tool_seconds_counted": st.count_tools,
            "vc_llm_calls": st.calls, "vc_completion_tokens": st.tokens, "vc_tool_seconds": round(st.tool_s, 1),
            "vc_llm_seconds": round(st.llm_seconds(), 1), "vc_branch_calls": st.branch_calls,
            # text-only model turns before submit_patch (inside a ParallelAgent each ends that branch's run)
            "vc_text_turns_before_submit": len(before_submit),
            "vc_text_turns": [list(t) for t in st.text_turns][:20],
            "load1_mean": round(sum(st.loads) / len(st.loads), 2) if st.loads else None,
            "load1_max": round(max(st.loads), 2) if st.loads else None, "cpu_count": os.cpu_count(),
            "real_agent_seconds": round((ctx.agent_end_time or time.perf_counter()) - ctx.agent_start_time, 1)
            if ctx is not None and getattr(ctx, "agent_start_time", None) is not None else None,
        })
        if row.get("real_agent_seconds") and row.get("virtual_seconds"):
            row["real_per_virtual"] = round(row["real_agent_seconds"] / max(1.0, row["virtual_seconds"]), 2)
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
