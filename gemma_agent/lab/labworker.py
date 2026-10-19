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
    used only with tool_seconds=False (then no measured tool time is added). Opt-in (make_lab
    --vc-per-kuncached / --vc-per-compaction, off by default): timepred's prefill term per 1k uncached prompt
    tokens and a fixed charge per ADK compaction (prompt < 0.7 x the stream's previous prompt). For the
    timepred-calibrated clock pass --vc-per-call 0.115 --vc-per-token 0.02855 --vc-per-kuncached 0.335
    --vc-per-compaction 25.4.
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

Call log: every LLM call the harness counts and every function response (author, branch, prompt/completion
tokens, function-call ids, wall time) goes to <results_dir>/calls/<id>.jsonl. timepred.py prefers it to the
ATIF trace, which merges a nested agent's first call into its caller's step (agent_tool, ParallelAgent).

Optional job keys (make_lab --data-dir / --sandbox docker-like / --phase2-only / --grade-extra-patches; see
the "data dir, per-task wheels, docker-like sandbox" section): tmpdir, sandbox, py313, image_dir,
sandbox_dir, phase2_only, extra_patches, no_graphs. Jobs without them run exactly as before.
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
        # opt-in prefill / compaction terms (timepred's step model; 0 = off, the default clock is unchanged)
        self.per_kuncached, self.per_compaction = 0.0, 0.0
        self.prev_prompt: dict = {}  # stream (author) -> prompt tokens of its previous call
        self.compactions = 0
        self.mode, self.real_factor, self.wall_scale = "real", 1.0, 1.0
        self.committed = 0.0  # closed epochs and serial calls (LLM part only)
        self.epoch: dict = {}  # branch -> LLM seconds in the open parallel epoch
        self.last_call_wall: dict = {}  # branch -> time.time() of its latest model call
        self.branch_calls: dict = {}
        self.text_turns: list = []  # (branch, virtual s, before submit) of text-only model turns
        self.loads: list = []
        self.sandbox_tmp: dict = {}
        self.calllog: list = []  # per-event records for timepred (see _event_record), written to <results>/calls/

    def reset(self, ctx) -> None:
        self.ctx, self.tokens, self.calls, self.tool_s, self.v_at_submit = ctx, 0, 0, 0.0, None
        self.committed, self.epoch, self.last_call_wall, self.branch_calls = 0.0, {}, {}, {}
        self.text_turns, self.loads = [], []
        self.calllog = [{"k": "start", "t": round(time.time(), 3)}]
        self.prev_prompt, self.compactions = {}, 0
        self.seen.clear()

    def prompt_cost(self, stream: str, prompt_tokens: int) -> float:
        """per_kuncached x uncached prompt k-tokens (growth of this stream's prompt since its previous call; the
        first call pays its whole prompt) + per_compaction when the prompt drops below 0.7 x the previous one
        (an ADK history compaction), as in timepred.py. 0 unless --vc-per-kuncached / --vc-per-compaction."""
        if not (self.per_kuncached or self.per_compaction):
            return 0.0
        pt = max(0, int(prompt_tokens or 0))
        prev = self.prev_prompt.get(stream, 0)
        self.prev_prompt[stream] = pt
        if prev and pt < 0.7 * prev:
            self.compactions += 1
            return self.per_compaction
        return self.per_kuncached * max(0, pt - prev) / 1000.0

    def charge_call(self, branch: str, tokens: int, prompt_tokens: int = 0, stream: str | None = None) -> None:
        cost = self.per_call + self.per_token * max(0, int(tokens))
        cost += self.prompt_cost(branch if stream is None else stream, prompt_tokens)
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


def _event_record(event, counted: bool) -> dict | None:
    """Compact record of one ADK event for the call log: LLM calls the harness counted (author, branch, prompt
    and completion tokens, function calls) and function responses (tool results, agent-tool returns).

    The ATIF trace is lossy for nested agents (adk_eval_core's converter attaches an agent tool's first inner
    function call to the caller's step and drops that inner LLM call's usage), so timepred prefers this log.
    """
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    fc = [[getattr(p.function_call, "name", "") or "", getattr(p.function_call, "id", "") or ""]
          for p in parts if getattr(p, "function_call", None)]
    fr = [[getattr(p.function_response, "name", "") or "", getattr(p.function_response, "id", "") or ""]
          for p in parts if getattr(p, "function_response", None)]
    if not counted and not fr:
        return None
    rec = {"k": "llm" if counted else "resp", "t": round(time.time(), 3), "a": getattr(event, "author", "") or "",
           "b": getattr(event, "branch", None) or ""}
    if counted:
        usage = getattr(event, "usage_metadata", None)
        rec["pt"] = int(getattr(usage, "prompt_token_count", 0) or 0) if usage is not None else 0
        rec["ct"] = int(getattr(usage, "candidates_token_count", 0) or 0) if usage is not None else 0
        if fc:
            rec["fc"] = fc
    if fr:
        rec["fr"] = fr
    return rec


def _is_text_turn(event) -> bool:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    if any(getattr(p, "function_call", None) or getattr(p, "function_response", None) for p in parts):
        return False
    return any((getattr(p, "text", None) or "").strip() and not getattr(p, "thought", False) for p in parts)


def install_clock(mode: str = "virtual", per_call: float | None = None, per_token: float | None = None,
                  real_factor: float = 3.0, wall_scale: float = 1.0, tool_seconds: bool = True,
                  per_kuncached: float | None = None, per_compaction: float | None = None) -> _ClockState:
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
    st.per_kuncached, st.per_compaction = float(per_kuncached or 0.0), float(per_compaction or 0.0)
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
            counted = event is not None and st.active and getattr(self, "llm_calls_used", 0) > before
            if event is not None and st.active:
                ekey = ("log", getattr(event, "id", None) or id(event))
                if ekey not in st.seen:
                    rec = _event_record(event, counted)
                    if rec is not None:
                        st.seen.add(ekey)
                        st.calllog.append(rec)
            # an LLM call exactly when the harness counted one (context.py handle_adk_event, step 2)
            if counted:
                key = getattr(event, "id", None) or id(event)
                if key not in st.seen:
                    st.seen.add(key)
                    usage = getattr(event, "usage_metadata", None)
                    toks = int(getattr(usage, "candidates_token_count", 0) or 0) if usage is not None else 0
                    ptoks = int(getattr(usage, "prompt_token_count", 0) or 0) if usage is not None else 0
                    branch = getattr(event, "branch", None) or ""
                    st.charge_call(branch, toks, ptoks, (getattr(event, "author", "") or "") + "|" + branch)
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


# ------------------------------------------------------------------ data dir, per-task wheels, docker-like sandbox
#
# Used only when make_lab.py gets --data-dir / --sandbox docker-like / --phase2-only / --grade-extra-patches
# (job keys 'tmpdir', 'sandbox', 'py313', 'image_dir', 'sandbox_dir', 'phase2_only', 'extra_patches'). Jobs
# without these keys run exactly as before.
#
# Why (swegemma 0.2.11):
#  * the stock SubprocessManager skips install_editable_package and install_test_dependencies (both return
#    early on type(docker).__name__ == 'SubprocessManager', harness/container_setup.py:506-531), so no wheel is
#    injected and setup.py never runs; the sandbox venv is the host interpreter (py3.12 on the pinned Kaggle
#    image) with the host site-packages visible. Fine for fastapi/rich (the host has their deps), wrong for
#    eval-set repos. 'docker-like' gives each sandbox a python3.13 venv layered on an image venv (the
#    Dockerfile.sandbox pip line) and maps /usr/local/lib/python3.13/site-packages onto it, so the harness
#    streams the unpacked wheels in and runs <data>/sandbox/setup.py like the scorer's container.
#  * the harness caches unpacked wheels as $TMPDIR/swegemma_sp_cache_v8/sp_base.tar (and sp_whl_<pkg>.tar) BY A
#    FIXED NAME, whatever the wheel set (container_setup.py:233-246, 341). Per-task wheel sets therefore get
#    their own TMPDIR keyed by the wheel set's content (tasks with identical sets share one cache); the pool
#    deletes it when no pending or running job uses it.

DOCKER_SP = "/usr/local/lib/python3.13/site-packages"
IMAGE_PIP = ["pytest", "pytest-timeout==2.1.0", "typer", "pdm-backend", "setuptools", "wheel", "poetry-core",
             "hatchling", "flit-core", "editables"]  # docker/Dockerfile.sandbox
PY313_TARBALLS = ("python313.tar.gz", "python313.tgz", "tools/python313.tar.gz")
IMAGE_WHEEL_DIRS = ("image_wheels", "wheels_pool", "wheels")


def resolve_data_dir(spec: str | None, default: Path | None = None, roots: tuple = ("/kaggle/input",)) -> Path:
    """A competition-format data dir (has tasks.jsonl) from a path, a glob, or a bare name searched under roots.

    Kaggle mounts kernel outputs and datasets at varying depths (/kaggle/input/<slug>/...,
    /kaggle/input/notebooks/<user>/<slug>/...), so a name that does not exist is looked up as a directory
    name (or as a path suffix) under /kaggle/input, at most 5 levels deep.
    """
    import glob as _glob
    if not spec:
        if default is None:
            raise FileNotFoundError("no data dir given")
        return Path(default)
    cands = [Path(p) for p in sorted(_glob.glob(spec))] if any(c in spec for c in "*?[") else [Path(spec)]
    for c in cands:
        if (c / "tasks.jsonl").is_file():
            return c
    suffix = spec.strip("/").split("/")
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth >= 5:
                dirnames[:] = []
            if "tasks.jsonl" in filenames and dirpath.rstrip("/").split("/")[-len(suffix):] == suffix:
                return Path(dirpath)
    raise FileNotFoundError(f"data dir {spec!r}: no tasks.jsonl found (also searched {roots})")


def wheel_set_key(wheels_dir: Path) -> str:
    import hashlib
    names = sorted(p.name for p in Path(wheels_dir).glob("*.whl"))
    return hashlib.sha1("\n".join(names).encode()).hexdigest()[:12]


def resolve_task_wheels(data_dir: Path, task_id: str, link_root: Path) -> tuple[Path, bool]:
    """(wheels dir for this task, per_task). Layouts, first match wins:
      <data>/wheels_by_task/<id>/*.whl
      <data>/wheels_manifest/<id>.txt (one wheel file name per line) + <data>/wheels_pool/ -> symlink dir
      <data>/wheels (shared; per_task False)."""
    data_dir = Path(data_dir)
    d = data_dir / "wheels_by_task" / task_id
    if d.is_dir() and any(d.glob("*.whl")):
        return d, True
    man = data_dir / "wheels_manifest" / f"{task_id}.txt"
    if man.is_file():
        pool = data_dir / "wheels_pool"
        out = Path(link_root) / task_id
        out.mkdir(parents=True, exist_ok=True)
        for name in man.read_text().split():
            name = os.path.basename(name)
            src = pool / name
            dst = out / name
            if src.is_file() and not (dst.is_symlink() and os.readlink(dst) == str(src.resolve())):
                if os.path.lexists(dst):
                    dst.unlink()
                dst.symlink_to(src.resolve())
        return out, True
    return data_dir / "wheels", False


def find_python313(data_dir: Path | None = None, explicit: str | None = None,
                   extract_to: Path = Path("/tmp/lab_py313")) -> str | None:
    """python3.13 for the docker-like sandbox: explicit path, <data>/python313/bin/python3.13, a
    python-build-standalone tarball in the data dir (uv python install output, relocatable), or PATH."""
    import shutil
    import tarfile
    if explicit:
        return explicit if os.path.exists(explicit) else None
    if data_dir is not None:
        p = Path(data_dir) / "python313" / "bin" / "python3.13"
        if p.exists():
            return str(p)
        for rel in PY313_TARBALLS:
            tb = Path(data_dir) / rel
            if tb.is_file():
                hit = sorted(Path(extract_to).glob("**/bin/python3.13"))
                if not hit:
                    extract_to.mkdir(parents=True, exist_ok=True)
                    with tarfile.open(tb) as tf:
                        tf.extractall(extract_to, filter="fully_trusted")
                    hit = sorted(Path(extract_to).glob("**/bin/python3.13"))
                if hit:
                    return str(hit[0])
    for c in (shutil.which("python3.13"), "/usr/bin/python3.13", "/usr/local/bin/python3.13"):
        if c and os.path.exists(c):
            return c
    return None


def install_python313_online(log=print) -> str | None:
    """Kernel with internet: pip install uv; uv python install 3.13 (python-build-standalone)."""
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=True)
        import shutil
        uv = shutil.which("uv") or str(Path(sys.executable).parent / "uv")
        subprocess.run([uv, "python", "install", "3.13"], check=True)
        py = subprocess.run([uv, "python", "find", "3.13"], capture_output=True, text=True).stdout.strip()
        return py or None
    except Exception as exc:  # noqa: BLE001
        log("uv python install 3.13 failed:", exc)
        return None


def prepare_image(python: str, image_dir: Path, wheel_dirs: list, shims_dir: Path | None = None, log=print,
                  online: bool = False) -> dict:
    """Build the 'swebench-sandbox' image as a python3.13 venv once (offline: pip --no-index --find-links).

    Returns {'image_dir', 'missing': [packages that could not be installed]}. A missing build backend only
    breaks `pip install -e /workspace` for repos that use it (the repo is still on sys.path via setup.py).
    """
    image_dir = Path(image_dir)
    marker = image_dir / ".swegemma_image_ok"
    if marker.exists():
        try:  # run_official.py writes "ok"; this function writes the JSON list of missing packages
            missing = json.loads(marker.read_text() or "[]")
        except ValueError:
            missing = []
        return {"image_dir": str(image_dir), "missing": missing if isinstance(missing, list) else []}
    subprocess.run([python, "-m", "venv", "--clear", str(image_dir)], check=True)
    vpy = str(image_dir / "bin" / "python")
    links = []
    for d in wheel_dirs:
        if d and Path(d).is_dir() and any(Path(d).glob("*.whl")):
            links += ["--find-links", str(d)]
    base = [vpy, "-m", "pip", "install", "-q", "--no-cache-dir", *([] if online else ["--no-index"]), *links]
    missing: list = []
    if subprocess.run(base + IMAGE_PIP).returncode != 0:
        for pkg in IMAGE_PIP:
            if subprocess.run(base + [pkg]).returncode != 0:
                missing.append(pkg)
    sp = next(image_dir.glob("lib/python3*/site-packages"))
    for shim in ("imp.py", "telnetlib.py"):
        src = Path(shims_dir) / shim if shims_dir else None
        if src is not None and src.is_file():
            (sp / shim).write_text(src.read_text())
    marker.write_text(json.dumps(missing))
    if missing:
        log("image313: could not install", missing, "(no wheel in", [str(d) for d in wheel_dirs], ")")
    return {"image_dir": str(image_dir), "missing": missing}


def prepare_sandbox_env(data_dir: Path, opts: dict, log=print, competition_dir: Path | None = None) -> dict:
    """Orchestrator side, once per kernel: python3.13 + image venv for 'docker-like', setup.py fallback."""
    env: dict = {}
    data_dir = Path(data_dir)
    if not (data_dir / "sandbox" / "setup.py").is_file() and competition_dir is not None \
            and (Path(competition_dir) / "sandbox" / "setup.py").is_file():
        env["sandbox_dir"] = str(Path(competition_dir) / "sandbox")  # -> KAGGLE_SANDBOX_DIR in the worker
    if opts.get("sandbox") == "docker-like":
        py = find_python313(data_dir, opts.get("py313"))
        if py is None and opts.get("internet"):
            py = install_python313_online(log)
        if py is None:
            raise RuntimeError("docker-like sandbox needs python3.13: ship <data>/python313.tar.gz "
                               "(uv python install 3.13; tar the cpython-3.13.* dir), pass --py313, or use --internet")
        image = Path(opts.get("image_dir") or "/tmp/lab_image313")
        shims = data_dir / "docker"
        if not shims.is_dir() and competition_dir is not None:
            shims = Path(competition_dir) / "docker"
        wheel_dirs = [data_dir / d for d in IMAGE_WHEEL_DIRS] + [Path(p) for p in opts.get("image_wheel_dirs", [])]
        img = prepare_image(py, image, wheel_dirs, shims, log, online=bool(opts.get("internet")))
        env.update(py313=py, image_dir=img["image_dir"], image_missing=img["missing"])
        log("docker-like sandbox: python", py, "image", img["image_dir"], "missing", img["missing"])
    return env


def job_extras(data_dir: Path, task_id: str, opts: dict, env: dict) -> dict:
    """Extra job keys for one task-run (new modes only): data dir, per-task wheels + TMPDIR, sandbox env."""
    data_dir = Path(data_dir)
    work = Path(opts.get("work_root") or "/tmp/lab_work")
    ex: dict = {"data_dir": str(data_dir)}
    wdir, per_task = resolve_task_wheels(data_dir, task_id, work / "wheels")
    ex["wheels_dir"] = str(wdir)
    if per_task and opts.get("per_task_wheels", True):
        key = wheel_set_key(wdir)
        ex["tmpdir"] = str(work / "tmp" / key)
        ex["wheels_key"] = key
        ex["cleanup_tmpdir"] = not opts.get("keep_tmp", False)
    for k in ("sandbox", "phase2_only", "extra_patches"):
        if opts.get(k):
            ex[k] = opts[k]
    for k in ("py313", "image_dir", "sandbox_dir"):
        if env.get(k):
            ex[k] = env[k]
    if opts.get("no_graphs"):
        ex["no_graphs"] = True
    return ex


def make_docker_like_manager(image: Path, python: str, timeout_seconds: int, base_dir: Path | None = None,
                             wheels_dir: Path | None = None, inject_wheels: bool = True):
    """A SubprocessManager that behaves like the scorer's docker container (port of
    gemma_agent/official/run_official.py:make_docker_like_manager, --deps image).

    Its class name is deliberately not 'SubprocessManager', so the harness runs install_editable_package,
    streams the unpacked wheels (<16 MB, plus the large ones the repo imports) into
    /usr/local/lib/python3.13/site-packages (mapped to the sandbox venv) and runs sandbox/setup.py --fast-path.
    Each sandbox: python3.13 venv layered on `image` (Dockerfile.sandbox packages), /wheels = symlinks to the
    task's wheels, git identity in HOME (= sandbox tmp), as the Dockerfile sets it.
    """
    import shutil  # noqa: F401
    import tarfile
    import tempfile
    import uuid

    from swegemma.sandbox import SubprocessManager

    image = Path(image)
    image_sp = next(image.glob("lib/python3*/site-packages"))

    class DockerLikeSandbox(SubprocessManager):
        def start(self) -> str:
            sid = str(uuid.uuid4())[:12]
            root = Path(tempfile.mkdtemp(prefix=f"swegemma_sandbox_{sid}_",
                                         dir=str(self.base_dir) if self.base_dir else None))
            for d in ("workspace", "tmp", "wheels"):
                (root / d).mkdir(parents=True, exist_ok=True)
            if wheels_dir is not None:
                for w in Path(wheels_dir).glob("*.whl"):
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
            return False  # its presence makes the harness stream wheels; False keeps copy+tar for snapshots

    cls = DockerLikeSandboxWheels if inject_wheels else DockerLikeSandbox
    return cls(timeout_seconds=timeout_seconds, base_dir=base_dir, system_site_packages=False)


def install_patch_capture(paths: list) -> dict:
    """Copy sandbox files (e.g. /tmp/a.diff, /tmp/b.diff of a two-attempt bundle) when the agent session stops.

    Wraps SwegemmaContext.stop_agent_session (after the clock's wrapper): the agent sandbox still exists then
    (it is stopped later in run_agent_sandbox's finally). Returns {sandbox path: text or None}.
    """
    from swegemma import context as ctxmod
    C = ctxmod.SwegemmaContext
    captured: dict = {}
    inner = C.stop_agent_session

    def stop_agent_session(self):
        inner(self)
        for p in paths:
            if p in captured:
                continue
            try:
                res = self.docker.exec(self.container_id, f"cat {p} 2>/dev/null", timeout=60)
                captured[p] = (res.stdout or "") if res.exit_code == 0 else None
            except Exception:  # noqa: BLE001
                captured[p] = None

    C.stop_agent_session = stop_agent_session
    return captured


def patch_files(patch: str) -> list:
    """Files a unified diff touches: 'diff --git a/X b/Y' headers, else '+++ b/Y' (or '--- a/X' when deleted)."""
    import re
    out = [m.group(2) for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)", patch or "", re.M)]
    if not out:
        minus = None
        for line in (patch or "").splitlines():
            if line.startswith("--- "):
                minus = line[4:].split("\t")[0].strip()
            elif line.startswith("+++ "):
                plus = line[4:].split("\t")[0].strip()
                f = plus if plus != "/dev/null" else (minus or "")
                f = f[2:] if f.startswith(("a/", "b/")) else f
                if f and f != "/dev/null":
                    out.append(f)
    return list(dict.fromkeys(out))


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


def build_registry(api_base: str, served_model: str, alias: str, bundle: Path | None):
    """VllmServer.create_model_registry pointed at the already-running server (as run_official.py).
    bundle None (phase2-only): no adapter manifest; no request is ever made."""
    from adk_submission import VllmConfig, VllmServer, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS
    base = (api_base or "http://127.0.0.1:9/v1").rstrip("/")

    class ExternalVllm(VllmServer):
        @property
        def base_url(self) -> str:
            return base

    manifest = discover_adapters(str(bundle), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS) \
        if bundle is not None else None
    server = ExternalVllm(VllmConfig(model=served_model, enable_lora=True), adapter_manifest=manifest)
    server.effective_model_path = served_model
    return server.create_model_registry(aliases=[alias], model_prefix="openai/", api_key="EMPTY")


def run_job(job: dict) -> dict:
    """Evaluate one task-run; returns the results.jsonl row (existing kernel format + extras).

    Optional job keys (new modes; absent = unchanged behaviour): tmpdir (per wheel set TMPDIR), sandbox
    ('docker-like' + py313 + image_dir), sandbox_dir (KAGGLE_SANDBOX_DIR for setup.py), phase2_only ('gold' |
    'empty': no model, verify that patch), extra_patches (sandbox paths graded after the run), no_graphs.
    """
    t1 = time.time()
    res_dir = Path(job["results_dir"])
    tid = job["task_id"]
    base = {"bundle": job["bundle"], "id": tid, "replicate": job.get("replicate", 0)}
    if job.get("tmpdir"):  # before anything calls tempfile.gettempdir() (the sp_base cache lives there)
        import tempfile
        Path(job["tmpdir"]).mkdir(parents=True, exist_ok=True)
        os.environ["TMPDIR"] = job["tmpdir"]
        tempfile.tempdir = job["tmpdir"]
    if job.get("sandbox_dir"):
        os.environ["KAGGLE_SANDBOX_DIR"] = job["sandbox_dir"]
    _setup_logging(res_dir / "worker_logs" / f"{tid}.log")
    st = None
    extra: dict = {}
    try:
        st = install_clock(job.get("clock", "real"), job.get("per_call"), job.get("per_token"),
                           job.get("real_factor", 3.0), job.get("wall_scale", 1.0), job.get("tool_seconds", True),
                           job.get("per_kuncached"), job.get("per_compaction"))
        captured = install_patch_capture(job["extra_patches"]) if job.get("extra_patches") else None
        import litellm
        import yaml
        from google.adk.agents.context_cache_config import ContextCacheConfig
        from google.adk.apps._configs import EventsCompactionConfig
        from swegemma.config import EvalConfig, build_submission_limits
        from swegemma.evaluate import Evaluator
        from swegemma.models import load_tasks
        litellm.drop_params = True

        data = Path(job["data_dir"])
        phase2 = job.get("phase2_only")
        agent_dir = Path(job["bundle_dir"]) if job.get("bundle_dir") else None
        ev = (yaml.safe_load((agent_dir / "eval_config.yaml").read_text()) or {}).get("evaluation", {}) \
            if agent_dir is not None and (agent_dir / "eval_config.yaml").exists() else {}
        ev = ev or {}
        models = build_registry(job["api_base"], job["served_model"], job.get("alias", "gemma-4-31b-it-qat-w4a16-ct"), agent_dir)
        limits, gen_constraints = build_submission_limits()
        graph_root = (res_dir / "_no_graphs") if job.get("no_graphs") else data
        wheels = Path(job.get("wheels_dir") or data / "wheels")

        def make_cfg(results_dir: Path):
            return EvalConfig(
                tasks_path=data / "tasks.jsonl", snapshots_dir=data / "snapshots", results_dir=results_dir,
                submission_dir=agent_dir if agent_dir is not None else results_dir, models=models, sandbox="subprocess",
                timeout_seconds=int(ev.get("timeout_seconds", 300)), max_time_minutes=ev.get("max_time_minutes"),
                max_tool_calls=ev.get("max_tool_calls"), max_turns=ev.get("max_turns"),
                limits=limits, generation_constraints=gen_constraints,
                context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
                events_compaction_config=EventsCompactionConfig(compaction_interval=15, overlap_size=2,
                                                                token_threshold=14336, event_retention_size=5),
                graph_dir=str(graph_root / "graphs"), embeddings_dir=str(graph_root / "embeddings"),
                wheels_dir=wheels, verbose=False, display_mode="quiet")

        def make_evaluator(cfg, patch_text=None):
            if patch_text is None:
                evaluator = Evaluator(cfg)
            else:
                from adk_eval_core.tracing import SessionTrace

                class Phase2Evaluator(Evaluator):
                    async def _run_agent_sandbox(self, task, snapshot_path, task_index, total_tasks, **kw):
                        return patch_text, None, SessionTrace()
                evaluator = Phase2Evaluator(cfg)
            if job.get("sandbox") == "docker-like":
                cmd_timeout = cfg.harness.command_timeout_seconds or 300
                evaluator.sandbox = evaluator.docker = make_docker_like_manager(
                    Path(job["image_dir"]), job["py313"], cmd_timeout, None, wheels)
            return evaluator

        cfg = make_cfg(res_dir)
        task = {t.instance_id: t for t in load_tasks(cfg.tasks_path)}[tid]
        patch_text = None
        if phase2:
            patch_text = task.patch if phase2 == "gold" else ""
        evaluator = make_evaluator(cfg, patch_text)
        r = asyncio.run(evaluator.evaluate_task(task=task, task_index=job.get("task_index", 1),
                                                total_tasks=job.get("total_tasks", 1)))
        row = dict(base, **{
            "resolved_kaggle_env": bool(r.resolved), "status": r.status,
            "patch_chars": len(r.agent_patch or ""), "tool_calls": r.tool_calls,
            "llm_calls": r.total_llm_calls, "tokens": r.total_tokens,
            "task_seconds": round(r.duration_seconds or 0, 1), "wall_seconds": round(time.time() - t1, 1),
            "error": str(r.error_message or "")[:800], "test_tail": (r.test_output or "")[-1500:],
            "patch": r.agent_patch or ""})
        if captured is not None:  # grade the extra patches (e.g. attempt A / B of a two-attempt bundle)
            for path in job["extra_patches"]:
                name = Path(path).stem
                text = captured.get(path)
                info = {"path": path, "chars": len(text or ""), "files": patch_files(text or ""), "resolved": False}
                if text and text.strip():
                    t2 = time.time()
                    try:
                        sub = make_cfg(res_dir / "extra" / name)
                        rr = asyncio.run(make_evaluator(sub, text).evaluate_task(task=task))
                        info.update(resolved=bool(rr.resolved), status=rr.status, seconds=round(time.time() - t2, 1),
                                    test_tail=(rr.test_output or "")[-300:])
                    except Exception:  # noqa: BLE001
                        info["error"] = traceback.format_exc()[-600:]
                extra[name] = info
    except BaseException:  # noqa: BLE001 - a crashed task is a row
        row = dict(base, error="CRASH " + traceback.format_exc()[-1500:], patch="",
                   wall_seconds=round(time.time() - t1, 1))
    if extra or job.get("extra_patches"):
        row["extra_patches"] = extra
    for k in ("phase2_only", "sandbox", "wheels_key"):
        if job.get(k):
            row[k] = job[k]
    if job.get("tmpdir") or job.get("sandbox") or job.get("phase2_only"):
        row["data_dir"] = job.get("data_dir")
    if st is not None and len(st.calllog) > 1:
        try:
            cdir = res_dir / "calls"
            cdir.mkdir(parents=True, exist_ok=True)
            (cdir / f"{tid.replace('/', '__')}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in st.calllog))
        except OSError:
            pass
    if st is not None:
        ctx = st.ctx
        before_submit = [t for t in st.text_turns if t[2]]
        row.update({
            "virtual_seconds": round(st.vnow(), 1) if ctx is not None else None,
            "virtual_at_submit": st.v_at_submit, "clock": st.mode, "real_cap_factor": st.real_factor,
            "vc_per_call": st.per_call, "vc_per_token": st.per_token, "vc_tool_seconds_counted": st.count_tools,
            **({"vc_per_kuncached": st.per_kuncached, "vc_per_compaction": st.per_compaction,
                "vc_compactions": st.compactions} if (st.per_kuncached or st.per_compaction) else {}),
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
            finished = []
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
                finished.append(job)
            running = still
            for job in finished:  # per wheel set TMPDIR (sp_base cache, leftover sandboxes): drop when unused
                td = job.get("tmpdir")
                if td and job.get("cleanup_tmpdir") and not any(
                        j.get("tmpdir") == td for j in pending + [r[1] for r in running]):
                    import shutil
                    shutil.rmtree(td, ignore_errors=True)
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
