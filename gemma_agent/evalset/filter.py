import sys, json, re, collections, pandas as pd
df = pd.concat([pd.read_parquet(p) for p in sys.argv[1].split(',')])
out = sys.argv[2]
CUTOFF = sys.argv[3] if len(sys.argv) > 3 else '2025-02-01'
import glob
FAMOUS = set()  # filled later by stars
rows = []
reasons = collections.Counter()
for _, r in df.iterrows():
    ic = r.install_config if isinstance(r.install_config, dict) else {}
    py = str(ic.get('python') or '')
    pre = ic.get('pre_install'); pre = list(pre) if pre is not None else []
    inst = str(ic.get('install') or '')
    tcmd = str(ic.get('test_cmd') or '')
    files = re.findall(r'^\+\+\+ b/(\S+)', r.patch, re.M)
    tfiles = re.findall(r'^\+\+\+ b/(\S+)', r.test_patch, re.M)
    code_files = [f for f in files if f.endswith('.py')]
    nonpy = [f for f in files if not f.endswith('.py') and not re.search(r'(CHANGELOG|CHANGES|HISTORY|NEWS|changelog|\.md$|\.rst$|\.txt$)', f)]
    added = sum(1 for l in r.patch.splitlines() if l.startswith(('+', '-')) and not l.startswith(('+++', '---')))
    d = str(r.created_at)[:10]
    why = None
    if d < CUTOFF: why = 'pre-cutoff'
    elif py not in ('3.10', '3.11', '3.12', '3.13', '3.13.1'): why = 'py<3.10'
    elif pre: why = 'pre_install(apt etc)'
    elif re.search(r'conda|apt|cargo|maturin|make |npm|uv sync|poetry install', inst + tcmd): why = 'complex install'
    elif not code_files: why = 'no .py change'
    elif nonpy: why = 'non-py src change'
    elif len(code_files) > 3: why = '>3 py files'
    elif added > 150: why = 'gold >150 lines'
    elif not tfiles or not all(f.endswith('.py') for f in tfiles): why = 'non-py test files'
    elif len(r.FAIL_TO_PASS) == 0: why = 'no F2P'
    if why:
        reasons[why] += 1; continue
    rows.append(dict(instance_id=r.instance_id, repo=r.repo, created_at=d, python=py, install=inst[:300],
                     n_files=len(code_files), gold_lines=added, n_test_files=len(tfiles),
                     f2p=len(r.FAIL_TO_PASS), p2p=len(r.PASS_TO_PASS), ps_len=len(r.problem_statement)))
print('total', len(df), 'kept', len(rows), dict(reasons))
k = pd.DataFrame(rows)
print('repos kept', k.repo.nunique())
print(k.repo.value_counts().head(25).to_dict())
print('python', k.python.value_counts().to_dict())
print('gold lines median', k.gold_lines.median(), 'ps median', k.ps_len.median(), 'files', k.n_files.value_counts().to_dict())
k.to_json(out, orient='records', lines=True)
