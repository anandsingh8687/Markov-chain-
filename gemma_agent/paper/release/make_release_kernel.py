"""make_release_kernel.py --out DIR [--user anandsingh8687] [--slug sealedgate-161]

Private CPU kernel (no internet, no GPU) that turns the evalset-v1-merge output into the public SealedGate-161
layout. It copies only what may be redistributed:
  tasks.jsonl, tasks_meta.jsonl (+ snapshot_included), split/id files, summary.json, rejects.jsonl
  snapshots/<id>.tgz            only for repositories with an OSI licence (MIT, Apache-2.0, BSD, MPL, ...)
  wheels/pool/*.whl             every task's cp313 wheels, de-duplicated by filename (PyPI packages, own licences)
  wheels/by_task/<id>.txt       the wheel filenames of each task (+ <id>.requirements.txt when present)
  graphs/, embeddings/          our make_graph.py code graphs for the snapshot tasks
It never copies the merge output's sandbox/ or docker/ directories (competition data).
"""
import argparse
import json
from pathlib import Path

KERNEL = r'''
import glob, json, os, shutil, subprocess
from pathlib import Path
hits = [p for pat in ('/kaggle/input/*/evalset/tasks_meta.jsonl', '/kaggle/input/notebooks/*/*/evalset/tasks_meta.jsonl',
                      '/kaggle/input/**/evalset/tasks_meta.jsonl') for p in glob.glob(pat, recursive=True)]
SRC = Path(hits[0]).parent
OUT = Path('/kaggle/working/sealedgate-161')
OUT.mkdir(parents=True, exist_ok=True)
OSI = {'MIT', 'MIT-0', 'Apache-2.0', 'BSD-3-Clause', 'BSD-2-Clause', 'Unlicense', 'MPL-2.0', 'ISC', '0BSD'}
meta = [json.loads(l) for l in open(SRC / 'tasks_meta.jsonl')]
keep = {m['instance_id'] for m in meta if m.get('license') in OSI}
with open(OUT / 'tasks_meta.jsonl', 'w') as f:
    for m in meta:
        m['snapshot_included'] = m['instance_id'] in keep
        m['repo_url'] = 'https://github.com/' + m['repo']
        f.write(json.dumps(m) + '\n')
for name in ('tasks.jsonl', 'rejects.jsonl', 'split_manifest.json', 'summary.json', 'ids_all.txt', 'ids_A.txt',
             'ids_B.txt', 'ids_new_repos.txt'):
    if (SRC / name).exists():
        shutil.copy(SRC / name, OUT / name)
(OUT / 'snapshots').mkdir(exist_ok=True)
n_snap = 0
for tid in sorted(keep):
    s = SRC / 'snapshots' / f'{tid}.tgz'
    if s.exists():
        shutil.copy(s, OUT / 'snapshots' / s.name); n_snap += 1
# code graphs + embeddings (our approximation of the hosts' graph, make_graph.py): their presence adds the
# harness's "Code Intelligence Tools" prompt section, as on the scorer
n_graph = 0
for sub, ext in (('graphs', '.json'), ('embeddings', '.npz')):
    (OUT / sub).mkdir(exist_ok=True)
    for m in meta:
        g = m.get('graph_key')
        if m['instance_id'] in keep and g and (SRC / sub / f'{g}{ext}').exists() and not (OUT / sub / f'{g}{ext}').exists():
            shutil.copy(SRC / sub / f'{g}{ext}', OUT / sub / f'{g}{ext}'); n_graph += 1
pool = OUT / 'wheels' / 'pool'; pool.mkdir(parents=True, exist_ok=True)
bt = OUT / 'wheels' / 'by_task'; bt.mkdir(parents=True, exist_ok=True)
n_whl = 0
for m in meta:
    tid = m['instance_id']; d = SRC / 'wheels_by_task' / tid
    if not d.is_dir():
        continue
    names = []
    for w in sorted(d.iterdir()):
        if w.suffix == '.whl':
            names.append(w.name)
            if not (pool / w.name).exists():
                shutil.copy(w, pool / w.name); n_whl += 1
        elif w.name == 'requirements.txt':
            shutil.copy(w, bt / f'{tid}.requirements.txt')
    (bt / f'{tid}.txt').write_text('\n'.join(names) + '\n')
(OUT / 'LICENSES.md').write_text("""# Licences
- Task metadata and problem statements derive from the SWE-rebench datasets (nebius), CC BY 4.0.
- snapshots/<id>.tgz are source snapshots of public GitHub repositories at the task's base commit, included only
  when the repository declares an OSI licence (tasks_meta.jsonl: license, snapshot_included). Each snapshot keeps
  its repository's licence file and remains under that licence.
- wheels/pool holds unmodified Python wheels downloaded from PyPI, each under its own package licence.
- graphs/ and embeddings/ are derived from the included snapshots by make_graph.py (same licences).
- Tasks with snapshot_included = false are released as metadata plus repo_url and base_commit only.
- Nothing from the competition's own data (harness, sandbox setup, docker shims) is included.
""")
print('tasks', len(meta), 'snapshots', n_snap, 'graph files', n_graph, 'unique wheels', n_whl, flush=True)
subprocess.run(['bash', '-c', f'du -sh {OUT} {OUT}/snapshots {OUT}/wheels; ls {OUT}'])
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--user', default='anandsingh8687')
    ap.add_argument('--slug', default='sealedgate-161')
    ap.add_argument('--source', default='evalset-v1-merge')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'release_kernel.py').write_text(KERNEL)
    meta = {
        'id': f'{a.user}/{a.slug}', 'title': 'SealedGate-161', 'code_file': 'release_kernel.py',
        'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': False, 'enable_tpu': False, 'enable_internet': False, 'keywords': [],
        'dataset_sources': [], 'competition_sources': [], 'kernel_sources': [f'{a.user}/{a.source}'],
        'model_sources': [],
    }
    (a.out / 'kernel-metadata.json').write_text(json.dumps(meta, indent=2))
    print('wrote', a.out, meta['id'])


if __name__ == '__main__':
    main()
