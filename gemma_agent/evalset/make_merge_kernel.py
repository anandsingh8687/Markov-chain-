"""make_merge_kernel.py --out DIR [--builds evalset-v1-build-part1,...] [--slug evalset-v1-merge]

Private CPU kernel (internet ON for the GitHub retry, no GPU/TPU) that reads the build kernels' outputs as kernel
sources and writes the combined evalset-v1 layout to /kaggle/working/evalset (see merge.py).
Lab: attach kernel source <user>/evalset-v1-merge and use DATA=/kaggle/input/evalset-v1-merge/evalset (or the
/kaggle/input/notebooks/<user>/evalset-v1-merge/evalset mount; glob for evalset/tasks_meta.jsonl).
"""
import argparse, json
from pathlib import Path

KERNEL = r'''
import glob, subprocess, sys
from pathlib import Path
BUILDS = __BUILDS__
INP = Path(next(p for pat in ['/kaggle/input/*/evalset_inputs_marker.txt', '/kaggle/input/datasets/*/*/evalset_inputs_marker.txt']
                for p in glob.glob(pat))).parent
dirs = []
for slug in BUILDS:
    hits = [p for pat in (f'/kaggle/input/{slug}/evalset/tasks_meta.jsonl', f'/kaggle/input/notebooks/*/{slug}/evalset/tasks_meta.jsonl',
                          f'/kaggle/input/*/{slug}/evalset/tasks_meta.jsonl', f'/kaggle/input/{slug}/**/tasks_meta.jsonl')
            for p in glob.glob(pat, recursive=True)]
    print(slug, '->', hits[:1], flush=True)
    if hits: dirs.append(str(Path(hits[0]).parent))
subprocess.run(['bash', '-c', 'df -h /kaggle/working; ls /kaggle/input'])
r = subprocess.run([sys.executable, '-I', str(INP / 'merge.py'), '/kaggle/working/evalset', *dirs,
                    '--manifest', str(INP / 'split_manifest.json'), '--gh-retry'])
subprocess.run(['bash', '-c', 'du -sh /kaggle/working/evalset; ls /kaggle/working/evalset'])
sys.exit(r.returncode)
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True); ap.add_argument('--user', default='anandsingh8687')
    ap.add_argument('--builds', default=','.join(f'evalset-v1-build-part{k}' for k in range(1, 5)))
    ap.add_argument('--slug', default='evalset-v1-merge'); ap.add_argument('--inputs', default='evalset-build-inputs')
    a = ap.parse_args()
    builds = a.builds.split(',')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'merge_kernel.py').write_text(KERNEL.replace('__BUILDS__', repr(builds)))
    meta = {
        'id': f'{a.user}/{a.slug}', 'title': a.slug.replace('-', ' ').title(), 'code_file': 'merge_kernel.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': False, 'enable_tpu': False, 'enable_internet': True, 'keywords': [],
        'dataset_sources': [f'{a.user}/{a.inputs}'], 'competition_sources': [],
        'kernel_sources': [f'{a.user}/{b}' for b in builds], 'model_sources': [],
    }
    (a.out / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
    print('wrote', a.out, meta['id'], 'sources', meta['kernel_sources'])


if __name__ == '__main__':
    main()
