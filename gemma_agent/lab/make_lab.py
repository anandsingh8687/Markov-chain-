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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles", nargs="+", required=True, help="name=path pairs")
    ap.add_argument("--tasks", nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--slug", default="gemma-agent-lab")
    ap.add_argument("--user", default="anandsingh8687")
    a = ap.parse_args()
    bundles = {}
    for spec in a.bundles:
        name, path = spec.split("=", 1)
        root = Path(path)
        bundles[name] = {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}
    code = KERNEL_TEMPLATE.replace("__BUNDLES__", repr(bundles)).replace("__TASK_IDS__", repr(a.tasks))
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
    print(f"wrote {a.out} with {len(bundles)} bundle(s) x {len(a.tasks)} task(s)")


if __name__ == "__main__":
    main()
