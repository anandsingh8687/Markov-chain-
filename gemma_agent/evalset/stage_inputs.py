"""stage_inputs.py OUT_DIR --dl DL_DIR --compdata COMPDATA_DIR [--slug evalset-build-inputs] [--user anandsingh8687]

Writes a FLAT directory for `kaggle datasets create -p OUT_DIR` (private by default): the eval-set scripts, the
candidate shards + split manifest, run_official.py, the compdata docker shims + sandbox/setup.py, and parquet subsets
holding only the candidate rows of each SWE-rebench source (schema preserved; ~10 MB instead of ~225 MB).
image313 is not shipped: the build kernel creates it with python3.13 (run_official.prepare_image), because the local
venv's interpreter symlinks do not exist on Kaggle.
"""
import argparse, json, shutil
from pathlib import Path
import pyarrow.compute as pc, pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument('out'); ap.add_argument('--dl', required=True); ap.add_argument('--compdata', required=True)
ap.add_argument('--slug', default='evalset-build-inputs'); ap.add_argument('--user', default='anandsingh8687')
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
for f in ('build.py', 'emit_tasks.py', 'goldcheck.py', 'gh_meta.py', 'pipeline.py', 'make_graph.py', 'merge.py',
          'harness_reqs.txt', 'candidates_v1.json'):
    shutil.copy(HERE / f, out / f)
for f in sorted((HERE / 'splits').glob('*.json')):
    shutil.copy(f, out / f.name)
shutil.copy(HERE.parent / 'official' / 'run_official.py', out / 'run_official.py')
cd = Path(a.compdata)
for f in ('imp.py', 'telnetlib.py', 'Dockerfile.sandbox'):
    shutil.copy(cd / 'docker' / f, out / f'compdata_docker_{f}')
shutil.copy(cd / 'sandbox' / 'setup.py', out / 'compdata_sandbox_setup.py')
cands = json.load(open(HERE / 'candidates_v1.json'))
want = {src: [c['instance_id'] for c in cands if c['src'] == src] for src in ('lb', 'v2', 'rb')}
dl = Path(a.dl)
sources = {'lb': [dl / 'lb_test.parquet'], 'v2': [dl / 'v2_py_post.parquet'],
           'rb': sorted(dl.glob('rebench_test_*.parquet'))}
for src, files in sources.items():
    tabs = []
    for f in files:
        t = pq.read_table(f)
        t = t.filter(pc.is_in(t.column('instance_id'), value_set=__import__('pyarrow').array(want[src])))
        if t.num_rows: tabs.append(t)
    t = tabs[0] if len(tabs) == 1 else __import__('pyarrow').concat_tables(tabs)
    pq.write_table(t, out / f'{src}_sub.parquet')
    print(src, t.num_rows, 'of', len(want[src]))
    assert t.num_rows >= len(set(want[src])), f'{src}: missing rows'
(out / 'evalset_inputs_marker.txt').write_text('evalset-v1 build inputs\n')
(out / 'dataset-metadata.json').write_text(json.dumps(
    {'title': a.slug.replace('-', ' ').title(), 'id': f'{a.user}/{a.slug}', 'licenses': [{'name': 'CC-BY-4.0'}]}, indent=1))
print('staged', out, sum(f.stat().st_size for f in out.iterdir()) / 1e6, 'MB')
