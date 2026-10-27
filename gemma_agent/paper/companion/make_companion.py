"""make_companion.py --out DIR: the paper's companion notebook (CPU, internet on for the vLLM wheel).

Attaches the dataset <user>/sealedgate-161-runs and the release kernel <user>/sealedgate-161, then
regenerates every table of the paper and reproduces the vLLM 0.19.1 gemma4 tool-parser hang.
"""
import argparse
import json
from pathlib import Path

CELLS = [
    ("markdown", """# SealedGate-161: reproduce the paper's tables

Companion to *Sealed and Calibrated: a Fresh-Repository Gate for Changing a 12-Hour Gemma 4 Coding Agent*.

Inputs:
- `sealedgate-161-runs` (dataset): per-run outcomes, leaderboard draws, trajectories, bundles and code;
- `sealedgate-161` (notebook output): the 161 tasks, metadata, snapshots, wheels and code graphs.

Everything below uses only the Python standard library, except the last section, which downloads the public
vLLM 0.19.1 wheel to show the tool-parser hang."""),
    ("code", """import glob, json, subprocess, sys, tarfile, collections
from pathlib import Path
RUNS = Path(glob.glob('/kaggle/input/**/sealedgate-161-runs/outcomes.csv', recursive=True)[0]).parent
REL = Path(glob.glob('/kaggle/input/**/sealedgate-161/tasks_meta.jsonl', recursive=True)[0]).parent
print(RUNS, REL)
print(open(RUNS / 'README.md').read()[:1500])"""),
    ("markdown", "## The task set"),
    ("code", """meta = [json.loads(l) for l in open(REL / 'tasks_meta.jsonl')]
print(len(meta), 'tasks from', len({m['repo'] for m in meta}), 'repositories')
print('splits', collections.Counter(m['split'] for m in meta))
print('snapshots included', sum(m['snapshot_included'] for m in meta))
print('licences', collections.Counter(m['license'] for m in meta).most_common())
print(open(REL / 'LICENSES.md').read())"""),
    ("markdown", "## Paper tables (gates, outcome mix, calibration, power, profile, compaction, malformed calls)"),
    ("code", """# trajectories: Kaggle unpacks traces.tar.gz in the dataset; the tables only need outcomes.csv
traces = [p for p in RUNS.rglob('*.json') if '/traces' in str(p) or 'traces.tar.gz' in str(p)]
print('released trajectories found:', len(traces))
r = subprocess.run([sys.executable, str(RUNS / 'code/paper/analysis.py'), '--meta', str(REL / 'tasks_meta.jsonl'),
                    '--data', str(RUNS)], capture_output=True, text=True)
print(r.stdout); print(r.stderr[-2000:])
exp = (RUNS / 'expected_tables.md').read_text()
print('ALL TABLES MATCH THE PAPER' if r.stdout.strip() == exp.strip() else 'TABLES DIFFER FROM expected_tables.md')"""),
    ("markdown", "## Overlap with other competition task sets"),
    ("code", """import csv
cw = list(csv.DictReader(open(RUNS / 'crosswalk.csv')))
z = [r for r in cw if r['zysbnd1_runs'] not in ('', '0') and r['sg_31b_runs'] not in ('', '0')]
import statistics
x = [int(r['sg_31b_solved']) / int(r['sg_31b_runs']) for r in z]; y = [int(r['zysbnd1_solved']) / int(r['zysbnd1_runs']) for r in z]
mx, my = statistics.mean(x), statistics.mean(y)
r_ = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
print('tasks shared with zysbnd1:', len(z), 'per-task solve-rate correlation r =', round(r_, 2))
print('tasks in toasterson held-out list:', sum(1 for r in cw if r['toasterson_id']))
print('tasks in sslasme lists:', sum(1 for r in cw if r['sslasme_lists']))"""),
    ("markdown", """## Scorer-time model

`code/lab/timepred.py` fits the per-step cost model on real-clock runs and predicts the scorer's sequential time
for concurrent lab runs. The fitted constants used for every eval-set lab are 0.115 s per LLM call, 28.55 ms per
completion token, 0.335 s per 1k uncached prompt tokens and 25.4 s per history compaction (plus measured tool
time). Predicted vs measured mean task seconds on the real-clock kernels: v28 -0.6%, v29 +0.2% / +0.4%,
v29 with 36 calls 0.0%, held-out v31a +1.6%."""),
    ("markdown", """## The vLLM 0.19.1 gemma4 tool-parser hang

The scorer serves the model with vLLM 0.19.1 and `--tool-call-parser gemma4`. Its argument parser
(`_parse_gemma4_array`) never advances on a bare value that starts at an unmatched `]`, so some malformed tool
calls spin the API server forever. Fixed upstream from vLLM 0.21.0."""),
    ("code", """subprocess.run([sys.executable, '-m', 'pip', 'download', 'vllm==0.19.1', '--no-deps', '-d', '/kaggle/working/vllm', '-q'], check=True)
whl = next(Path('/kaggle/working/vllm').glob('vllm-0.19.1*.whl'))
subprocess.run(['unzip', '-o', '-q', str(whl), 'vllm/tool_parsers/gemma4_tool_parser.py', '-d', '/kaggle/working/vx'], check=True)
r = subprocess.run([sys.executable, str(RUNS / 'code/lab/parser_hang/repro.py'), '/kaggle/working/vx'], capture_output=True, text=True)
print(r.stdout, r.stderr[-1500:])"""),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--user', default='anandsingh8687')
    ap.add_argument('--slug', default='sealedgate-161-companion')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
          "cells": [{"cell_type": t, "metadata": {}, "source": src, **({"outputs": [], "execution_count": None} if t == "code" else {})}
                    for t, src in CELLS]}
    (a.out / 'companion.ipynb').write_text(json.dumps(nb, indent=1))
    meta = {'id': f'{a.user}/{a.slug}', 'title': 'SealedGate-161 Companion', 'code_file': 'companion.ipynb',
            'language': 'python', 'kernel_type': 'notebook', 'is_private': True, 'enable_gpu': False,
            'enable_tpu': False, 'enable_internet': True, 'keywords': [],
            'dataset_sources': [f'{a.user}/sealedgate-161-runs'], 'competition_sources': [],
            'kernel_sources': [f'{a.user}/sealedgate-161'], 'model_sources': []}
    (a.out / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
    print('wrote', a.out)


if __name__ == '__main__':
    main()
