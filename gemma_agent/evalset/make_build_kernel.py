"""make_build_kernel.py --part part1|pilot|... --out DIR [--slug evalset-v1-build-p1] [--jobs 4] [--deadline-hours 9.5]

Writes a private CPU Kaggle kernel (internet ON, no GPU/TPU) that builds one candidate shard of evalset-v1:
  uv + python3.13 -> harness venv (swegemma 0.2.11 & co from the competition wheelhouse, --no-deps, pinned deps
  from harness_reqs.txt) -> image313 (Dockerfile.sandbox's pip line + shims) -> pipeline.py on the shard.
Inputs: dataset <user>/evalset-build-inputs (stage_inputs.py), the competition (attached) and its wheelhouse dataset.
Output: /kaggle/working/evalset (see pipeline.py for the layout). Push with: kaggle kernels push -p DIR
"""
import argparse, json
from pathlib import Path

KERNEL = r'''
import glob, json, os, shutil, subprocess, sys, time
from pathlib import Path
PART = __PART__
JOBS = __JOBS__
DEADLINE_H = __DEADLINE__
T0 = time.time()

def sh(cmd, check=True, **kw):
    print('$', cmd, flush=True)
    r = subprocess.run(['bash', '-c', cmd], **kw)
    if check and r.returncode:
        raise SystemExit(f'command failed rc={r.returncode}: {cmd}')
    return r

def find(pattern_list):
    for pat in pattern_list:
        hits = glob.glob(pat)
        if hits:
            return Path(hits[0])
    raise SystemExit(f'not found: {pattern_list}')

INP = find(['/kaggle/input/*/evalset_inputs_marker.txt', '/kaggle/input/datasets/*/*/evalset_inputs_marker.txt']).parent
WH = find(['/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse', '/kaggle/input/gemma-4-developer-agent-wheelhouse',
           '/kaggle/input/*/gemma-4-developer-agent-wheelhouse'])
print('inputs', INP, 'wheelhouse', WH, 'python', sys.version, flush=True)
sh('nproc; free -g; df -h /kaggle/working /tmp', check=False)
WORK = Path('/tmp/eb'); WORK.mkdir(parents=True, exist_ok=True)
OUT = Path('/kaggle/working/evalset'); OUT.mkdir(parents=True, exist_ok=True)
SCR = WORK / 'scripts'; SCR.mkdir(exist_ok=True)
for f in INP.iterdir():
    if f.suffix in ('.py', '.txt', '.json'):
        shutil.copy(f, SCR / f.name)
CD = WORK / 'compdata'
(CD / 'docker').mkdir(parents=True, exist_ok=True); (CD / 'sandbox').mkdir(parents=True, exist_ok=True)
for f in ('imp.py', 'telnetlib.py', 'Dockerfile.sandbox'):
    shutil.copy(INP / f'compdata_docker_{f}', CD / 'docker' / f)
shutil.copy(INP / 'compdata_sandbox_setup.py', CD / 'sandbox' / 'setup.py')

# --- tools: uv, python 3.13 (sandbox + build venvs), harness venv (python 3.12, swegemma from the wheelhouse)
sh(f'{sys.executable} -m pip install -q uv')
UV = shutil.which('uv') or str(Path(sys.executable).parent / 'uv')
sh(f'{UV} python install 3.13 3.12')
PY313 = subprocess.run([UV, 'python', 'find', '3.13'], capture_output=True, text=True).stdout.strip()
print('python3.13 =', PY313, flush=True)
HV = WORK / 'hv'
sh(f'{UV} venv -q -p 3.12 {HV}')
whl = ' '.join(str(next(WH.glob(p))) for p in ('swegemma-0.2.11-*.whl', 'adk_submission-0.2.13-*.whl',
                                                'adk_eval_core-0.1.0-*.whl', 'google_adk-1.36.1-*.whl'))
sh(f'{UV} pip install -q -p {HV}/bin/python --no-deps -r {SCR}/harness_reqs.txt {whl}')
sh(f'{HV}/bin/python -I -c "import swegemma, adk_submission, google.adk; from swegemma.evaluate import Evaluator; print(\'harness ok\')"')
IMG = WORK / 'img'; IMG.mkdir(exist_ok=True)
if not (IMG / 'docker').exists():
    (IMG / 'docker').symlink_to(CD / 'docker')
sh(f'cd {SCR} && {HV}/bin/python -I -c "import sys; sys.path.insert(0, \'{SCR}\'); from pathlib import Path; '
   f'import run_official as r; print(r.prepare_image(Path(\'{IMG}\'), \'{PY313}\'))"')
sh(f'{IMG}/image313/bin/python -c "import pytest, sys; print(sys.version, pytest.__version__)"')
print(f'setup done in {time.time() - T0:.0f}s', flush=True)

# --- the build
parq = ','.join(str(INP / f) for f in ('lb_sub.parquet', 'v2_sub.parquet', 'rb_sub.parquet'))
hours_left = DEADLINE_H - (time.time() - T0) / 3600
r = sh(f'{sys.executable} -I {SCR}/pipeline.py --cands {SCR}/{PART}.json --manifest {SCR}/split_manifest.json '
       f'--parquets {parq} --out {OUT} --work {WORK} --hpy {HV}/bin/python --official {SCR}/run_official.py '
       f'--py313 {PY313} --image {IMG} --compdata {CD} --jobs {JOBS} --deadline-hours {hours_left:.2f} --max-out-gb 16',
       check=False)
shutil.copy(SCR / 'split_manifest.json', OUT / 'split_manifest.json')
(OUT / 'sandbox').mkdir(exist_ok=True); shutil.copy(CD / 'sandbox' / 'setup.py', OUT / 'sandbox' / 'setup.py')
shutil.copytree(CD / 'docker', OUT / 'docker', dirs_exist_ok=True)
(OUT / 'BUILD_INFO.json').write_text(json.dumps(dict(part=PART, pipeline_rc=r.returncode, hours=round((time.time() - T0) / 3600, 2),
                                                     python313=PY313), indent=1))
sh(f'du -sh {OUT}; ls {OUT}; cat {OUT}/summary.json', check=False)
shutil.rmtree(WORK, ignore_errors=True)
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--part', required=True); ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--slug', default=None); ap.add_argument('--user', default='anandsingh8687')
    ap.add_argument('--jobs', type=int, default=4); ap.add_argument('--deadline-hours', type=float, default=9.5)
    ap.add_argument('--inputs', default='evalset-build-inputs')
    a = ap.parse_args()
    slug = a.slug or f'evalset-v1-build-{a.part}'
    code = KERNEL.replace('__PART__', repr(a.part)).replace('__JOBS__', str(a.jobs)).replace('__DEADLINE__', str(a.deadline_hours))
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'build_kernel.py').write_text(code)
    meta = {
        'id': f'{a.user}/{slug}', 'title': slug.replace('-', ' ').title(), 'code_file': 'build_kernel.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': False, 'enable_tpu': False, 'enable_internet': True, 'keywords': [],
        'dataset_sources': [f'{a.user}/{a.inputs}', 'metric/gemma-4-developer-agent-wheelhouse'],
        'competition_sources': ['gemma-4-developer-agent'], 'kernel_sources': [], 'model_sources': [],
    }
    (a.out / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
    print('wrote', a.out, meta['id'])


if __name__ == '__main__':
    main()
