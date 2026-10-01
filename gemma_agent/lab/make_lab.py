"""Build a Kaggle GPU kernel that runs agent bundles with the official harness.

The kernel reuses the host's Getting Started setup (wheelhouse install, vLLM on
the competition's Gemma 4 31B QAT weights, swegemma Evaluator with the
subprocess sandbox) and runs each bundle on the same task sample, saving
patches, per-task timings, tool-call counts and the harness logs/traces to
/kaggle/working. Phase 2 verification in a Kaggle notebook lacks some test
dependencies, so patches are re-verified with localeval afterwards.

Usage:
    python gemma_agent/lab/make_lab.py --bundles v3=gemma_agent/bundle_v3 \
        --tasks fastapi_14873 rich_3006 ... --out /tmp/lab_kernel --slug gemma-agent-lab
    kaggle kernels push -p /tmp/lab_kernel

Concurrent mode (--concurrency N > 1, or --replicates R > 1, or a non-real clock): the
kernel writes /kaggle/working/labworker.py (gemma_agent/lab/labworker.py) and runs each
(task, replicate, bundle) as its own OS process against the single vLLM server,
N at a time, task-major with the bundle order shuffled per (task, replicate) so every
variant sees the same load. Results dirs are lab/<bundle>/r<rep>; results.jsonl rows
keep the sequential format plus 'replicate', 'virtual_seconds' (and vc_* details).
vLLM /metrics (running/waiting requests, KV usage) is logged every --metrics-interval s
to progress.log and lab/metrics.jsonl; the vLLM server log is copied to lab/vllm_server.log.

    python gemma_agent/lab/make_lab.py --bundles v22=gemma_agent/bundle_v22 ... \
        --tasks @scratchpad/broad48_K1.txt --concurrency 6 --virtual-clock --out /tmp/k1

--virtual-clock: agent time = 0.164 s/LLM call + 0.0221 s/completion token (LLM time, refit without
tool time) + measured sandbox exec seconds, charged per ADK branch (parallel branches: max, x1.15);
--vc-no-tool-seconds uses 0.95/0.0287 (fitted on total time) and no measured tool time. The real
asyncio cap is --real-factor (3) x nominal (see labworker.py for the patched attributes). The helper
tools of v23/v24 read the same clock from <sandbox tmp>/.swe_vclock. --wall-scale F is the fallback
without a token clock: real cap and the agent's elapsed time are both scaled by F (the measured slowdown).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

KERNEL_TEMPLATE = r'''
import glob, importlib, json, os, shutil, subprocess, sys, time, traceback
from pathlib import Path

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
os.environ['TRANSFORMERS_NO_TF'] = '1'
os.environ['VLLM_WORKER_MULTIPROC_METHOD'] = 'spawn'
os.environ['VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS'] = '1'
os.environ['VLLM_ENGINE_READY_TIMEOUT_S'] = '1200'
os.environ['VLLM_NO_USAGE_STATS'] = '1'
os.environ['OTEL_SDK_DISABLED'] = 'true'
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'

BUNDLES = __BUNDLES__
TASK_IDS = __TASK_IDS__
OUT = Path('/kaggle/working/lab')
OUT.mkdir(parents=True, exist_ok=True)
LOG = open(OUT / 'progress.log', 'a', buffering=1)
def log(*a):
    msg = time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a)
    print(msg, flush=True); LOG.write(msg + '\n')

WHEELHOUSE_DIR = next(p for p in [Path('/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse'),
                                  Path('/kaggle/input/gemma-4-developer-agent-wheelhouse')] if p.exists())
for pat in ('/usr/local/lib/python*/dist-packages/*cutlass*.pth', '/usr/local/lib/python*/site-packages/*cutlass*.pth'):
    for pth in glob.glob(pat):
        try: os.unlink(pth)
        except OSError: pass
tmp_whl = Path('/tmp/wheelhouse'); tmp_whl.mkdir(parents=True, exist_ok=True)
for w in WHEELHOUSE_DIR.glob('*.whl'):
    if 'cutlass' in w.name.lower(): continue
    name = w.name.replace('cu128', '+cu128') if ('cu128' in w.name and '+' not in w.name) else w.name
    if not (tmp_whl / name).exists(): os.symlink(w, tmp_whl / name)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', '--force-reinstall',
                *sorted(str(w) for w in tmp_whl.glob('*.whl'))], check=True)
importlib.invalidate_caches()
log('wheelhouse installed')

from swegemma.models import load_tasks
DATA_DIR = next(p for p in [Path('/kaggle/input/competitions/gemma-4-developer-agent'),
                            Path('/kaggle/input/gemma-4-developer-agent')] if p.exists())
tasks = {t.instance_id: t for t in load_tasks(DATA_DIR / 'tasks.jsonl')}

import litellm, torch, yaml
from adk_submission import VllmConfig, VllmServer, discover_adapters
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, EvalConfig, build_submission_limits
from swegemma.evaluate import Evaluator
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps._configs import EventsCompactionConfig
litellm.drop_params = True

MODEL_PATH = next(Path(p) for p in glob.glob('/kaggle/input/models/google/gemma-4/*/gemma-4-31b-it-qat-w4a16-ct/*')
                  + glob.glob('/kaggle/input/gemma-4/*/gemma-4-31b-it-qat-w4a16-ct/*'))
gpu_count = torch.cuda.device_count()
log('gpus', gpu_count, [torch.cuda.get_device_name(i) for i in range(gpu_count)])
tp = 4 if gpu_count >= 4 else (2 if gpu_count >= 2 else 1)

def write_bundle(name, files):
    d = Path('/kaggle/working/bundles') / name
    if d.exists(): shutil.rmtree(d)
    for rel, text in files.items():
        p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    return d

first = write_bundle(*next(iter(BUNDLES.items())))
server = VllmServer(VllmConfig(
    model=str(MODEL_PATH), port=8000, host='127.0.0.1', tool_call_parser='gemma4', reasoning_parser='gemma4',
    default_chat_template_kwargs={'enable_thinking': True}, max_model_len=32768,
    dtype='bfloat16' if torch.cuda.is_bf16_supported() else 'auto', gpu_memory_utilization=0.90,
    enable_auto_tool_choice=True, enable_lora=True, max_loras=8, max_lora_rank=128,
    tensor_parallel_size=tp, startup_timeout=60 * 20), adapter_manifest=discover_adapters(str(first), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS))
t0 = time.time(); server.start(); log('vllm up in', round(time.time() - t0), 's')
models = server.create_model_registry(aliases=['gemma-4-31b-it-qat-w4a16-ct'], model_prefix='openai/', api_key='EMPTY')

import asyncio
limits, gen_constraints = build_submission_limits()
summary = []
for name, files in BUNDLES.items():
    agent_dir = write_bundle(name, files)
    ev = (yaml.safe_load((agent_dir / 'eval_config.yaml').read_text()) or {}).get('evaluation', {}) if (agent_dir / 'eval_config.yaml').exists() else {}
    res_dir = OUT / name
    cfg = EvalConfig(
        tasks_path=DATA_DIR / 'tasks.jsonl', snapshots_dir=DATA_DIR / 'snapshots', results_dir=res_dir,
        submission_dir=agent_dir, models=models, sandbox='subprocess',
        timeout_seconds=int(ev.get('timeout_seconds', 300)), max_time_minutes=ev.get('max_time_minutes'),
        max_tool_calls=ev.get('max_tool_calls'), max_turns=ev.get('max_turns'),
        limits=limits, generation_constraints=gen_constraints,
        context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
        events_compaction_config=EventsCompactionConfig(compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5),
        graph_dir=str(DATA_DIR / 'graphs'), embeddings_dir=str(DATA_DIR / 'embeddings'),
        wheels_dir=DATA_DIR / 'wheels', verbose=False, display_mode='quiet')
    evaluator = Evaluator(cfg)
    for i, tid in enumerate(TASK_IDS, 1):
        task = tasks[tid]
        t1 = time.time()
        try:
            r = asyncio.run(evaluator.evaluate_task(task=task, task_index=i, total_tasks=len(TASK_IDS)))
            row = {'bundle': name, 'id': tid, 'resolved_kaggle_env': bool(r.resolved), 'status': r.status,
                   'patch_chars': len(r.agent_patch or ''), 'tool_calls': r.tool_calls,
                   'llm_calls': r.total_llm_calls, 'tokens': r.total_tokens,
                   'task_seconds': round(r.duration_seconds or 0, 1), 'wall_seconds': round(time.time() - t1, 1),
                   'error': str(r.error_message or '')[:800], 'test_tail': (r.test_output or '')[-1500:],
                   'patch': r.agent_patch or ''}
        except Exception as exc:
            row = {'bundle': name, 'id': tid, 'error': 'CRASH ' + traceback.format_exc()[-1500:], 'patch': '',
                   'wall_seconds': round(time.time() - t1, 1)}
        summary.append(row)
        (OUT / 'results.jsonl').open('a').write(json.dumps(row) + '\n')
        log(name, tid, 'patch' if row.get('patch') else 'NO-PATCH', 'calls', row.get('tool_calls'),
            'llm', row.get('llm_calls'), 'task_s', row.get('task_seconds'), 'wall_s', row.get('wall_seconds'), row.get('error', '')[:120])
server.stop() if hasattr(server, 'stop') else None
log('done', len(summary), 'rows')
'''


CONCURRENT_TAIL = r'''
import random
LABWORKER_SRC = __LABWORKER__
CONCURRENCY = __CONCURRENCY__
REPLICATES = __REPLICATES__
CLOCK = __CLOCK__
CLOCK_ARGS = __CLOCK_ARGS__
SEED = __SEED__
METRICS_INTERVAL = __METRICS_INTERVAL__
Path('/kaggle/working/labworker.py').write_text(LABWORKER_SRC)
sys.path.insert(0, '/kaggle/working')
import labworker

log('cpu_count', os.cpu_count(), 'loadavg', os.getloadavg())
try:
    log('meminfo', ' '.join(l.replace(' ', '') for l in open('/proc/meminfo').read().splitlines()[:3]))
except OSError:
    pass
def server_log_lines(pats=('KV cache', 'Maximum concurrency', 'num_gpu_blocks', 'max_num_seqs', 'max_num_batched_tokens')):
    try:
        return [l.rstrip() for l in open(server.log_path, errors='replace') if any(p in l for p in pats)]
    except Exception as exc:
        return ['server log unreadable: %s' % exc]
for l in server_log_lines()[-12:]:
    log('vllm', l[-300:])

bundle_dirs = {name: write_bundle(name, files) for name, files in BUNDLES.items()}
def nominal_minutes(d):
    try:
        ev = (yaml.safe_load((d / 'eval_config.yaml').read_text()) or {}).get('evaluation', {}) or {}
        return float(ev.get('max_time_minutes') or 5)
    except Exception:
        return 5.0
cap_factor = CLOCK_ARGS['real_factor'] if CLOCK == 'virtual' else (CLOCK_ARGS['wall_scale'] if CLOCK == 'scaled' else 1.0)
KILL_AFTER = max(nominal_minutes(d) for d in bundle_dirs.values()) * 60 * cap_factor + 900
served = getattr(server, 'effective_model_path', None) or str(MODEL_PATH)
plan = labworker.plan_jobs(list(BUNDLES), TASK_IDS, REPLICATES, SEED)
jobs = []
for tid, rep, name in plan:
    jobs.append(dict(bundle=name, replicate=rep, task_id=tid, bundle_dir=str(bundle_dirs[name]),
                     results_dir=str(OUT / name / ('r%d' % rep)), data_dir=str(DATA_DIR), wheels_dir=str(DATA_DIR / 'wheels'),
                     api_base='http://127.0.0.1:8000/v1', served_model=served, alias='gemma-4-31b-it-qat-w4a16-ct',
                     clock=CLOCK, task_index=TASK_IDS.index(tid) + 1, total_tasks=len(TASK_IDS), **CLOCK_ARGS))
log('concurrent plan', len(jobs), 'task-runs', 'N', CONCURRENCY, 'replicates', REPLICATES, 'clock', CLOCK, CLOCK_ARGS,
    'kill_after_s', round(KILL_AFTER))
t0 = time.time()
summary = labworker.run_pool(jobs, CONCURRENCY, OUT, log, metrics_url='http://127.0.0.1:8000/metrics',
                             metrics_interval=METRICS_INTERVAL, kill_after=KILL_AFTER)
log('pool done in', round(time.time() - t0), 's')
for l in server_log_lines(('KV cache', 'Maximum concurrency', 'preempt', 'Avg prompt throughput'))[-20:]:
    log('vllm', l[-300:])
try:
    shutil.copy(server.log_path, OUT / 'vllm_server.log')
except Exception as exc:
    log('could not copy server log', exc)
server.stop() if hasattr(server, 'stop') else None
log('done', len(summary), 'rows')
'''

SEQUENTIAL_SPLIT = "import asyncio\nlimits, gen_constraints"


def build_kernel(bundles: dict, tasks: list[str], concurrency: int = 1, replicates: int = 1, clock: str = "real",
                 clock_args: dict | None = None, seed: int = 0, metrics_interval: float = 30.0) -> str:
    """Kernel source. concurrency 1 / replicates 1 / real clock -> the unchanged sequential kernel."""
    code = KERNEL_TEMPLATE.replace("__BUNDLES__", repr(bundles)).replace("__TASK_IDS__", repr(tasks))
    if concurrency <= 1 and replicates <= 1 and clock == "real":
        return code
    head = code[:code.index(SEQUENTIAL_SPLIT)]
    worker_src = (Path(__file__).resolve().parent / "labworker.py").read_text()
    tail = (CONCURRENT_TAIL.replace("__LABWORKER__", repr(worker_src)).replace("__CONCURRENCY__", repr(concurrency))
            .replace("__REPLICATES__", repr(replicates)).replace("__CLOCK__", repr(clock))
            .replace("__CLOCK_ARGS__", repr(clock_args or {})).replace("__SEED__", repr(seed))
            .replace("__METRICS_INTERVAL__", repr(metrics_interval)))
    return head + tail


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles", nargs="+", required=True, help="name=path pairs")
    ap.add_argument("--tasks", nargs="+", required=True, help="task ids, or @file with ids")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--slug", default="gemma-agent-lab")
    ap.add_argument("--user", default="anandsingh8687")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="task-runs evaluated at once as separate OS processes (1 = sequential kernel, unchanged)")
    ap.add_argument("--replicates", type=int, default=1, help="run each bundle R times per task")
    ap.add_argument("--virtual-clock", action="store_true",
                    help="token clock: agent time = per-call + per-token + measured tool seconds (use with N>1)")
    ap.add_argument("--vc-per-call", type=float, default=None,
                    help="s per LLM call (default 0.164 with measured tool seconds, 0.95 with --vc-no-tool-seconds)")
    ap.add_argument("--vc-per-token", type=float, default=None,
                    help="s per completion token (default 0.0221, or 0.0287 with --vc-no-tool-seconds)")
    ap.add_argument("--vc-no-tool-seconds", action="store_true",
                    help="token clock fitted on total task time (0.95/0.0287) without measured tool seconds")
    ap.add_argument("--real-factor", type=float, default=3.0, help="real asyncio cap = factor x nominal (virtual clock)")
    ap.add_argument("--wall-scale", type=float, default=1.0,
                    help="fallback without --virtual-clock: real cap and agent elapsed scaled by this slowdown")
    ap.add_argument("--seed", type=int, default=0, help="bundle-order shuffle seed")
    ap.add_argument("--metrics-interval", type=float, default=30.0, help="seconds between vLLM /metrics scrapes")
    a = ap.parse_args()
    tasks: list[str] = []
    for x in a.tasks:
        tasks += Path(x[1:]).read_text().split() if x.startswith("@") else [x]
    tasks = list(dict.fromkeys(tasks))
    bundles = {}
    for spec in a.bundles:
        name, path = spec.split("=", 1)
        root = Path(path)
        bundles[name] = {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}
    clock = "virtual" if a.virtual_clock else ("scaled" if a.wall_scale != 1.0 else "real")
    if clock != "real" and a.concurrency <= 1:
        print("warning: a virtual/scaled clock is only meaningful with --concurrency > 1")
    clock_args = {"per_call": a.vc_per_call, "per_token": a.vc_per_token, "real_factor": a.real_factor,
                  "wall_scale": a.wall_scale, "tool_seconds": not a.vc_no_tool_seconds}
    code = build_kernel(bundles, tasks, a.concurrency, a.replicates, clock, clock_args, a.seed, a.metrics_interval)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "lab.py").write_text(code)
    meta = {
        "id": f"{a.user}/{a.slug}", "title": a.slug.replace("-", " ").title(), "code_file": "lab.py",
        "language": "python", "kernel_type": "script", "is_private": True, "enable_gpu": True,
        "enable_tpu": False, "enable_internet": False, "keywords": [],
        "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"], "kernel_sources": [],
        "competition_sources": ["gemma-4-developer-agent"],
        "model_sources": ["google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2"],
        "machine_shape": "NvidiaL4",
    }
    (a.out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    runs = len(bundles) * len(tasks) * a.replicates
    print(f"wrote {a.out} with {len(bundles)} bundle(s) x {len(tasks)} task(s) x {a.replicates} replicate(s) "
          f"= {runs} task-runs, concurrency {a.concurrency}, clock {clock}")

if __name__ == "__main__":
    main()
