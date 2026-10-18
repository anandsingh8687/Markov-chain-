"""merge.py OUT_DIR BUILD_DIR [BUILD_DIR...] [--manifest split_manifest.json] [--gh-retry]

Combines the evalset-v1 build shards into one data layout (what the lab attaches as a kernel source):
  tasks.jsonl            all valid tasks (8 competition fields)
  tasks_meta.jsonl       per-task metadata (split A/B, part, src, ps_source, dates, F2P/P2P, timings, ...)
  rejects.jsonl          dropped candidates with stage + reason
  split_manifest.json    seeded repo-level A/B split (+ which candidates survived)
  ids_all.txt ids_A.txt ids_B.txt ids_new_repos.txt (repo created >= 2025-01-01)
  snapshots/<id>.tgz  wheels_by_task/<id>/*.whl  graphs/<name>_<commit>.json  embeddings/<name>_<commit>.npz
  sandbox/setup.py  docker/  wheels/README.txt (harness needs a wheels/ dir; use wheels_by_task/<id> per task)
  summary.json
--gh-retry: retry the GitHub API for tasks whose problem_statement still comes from git/issue text and for repos
without an API creation date (another IP/time than the builds); updates tasks.jsonl + tasks_meta.jsonl in place.
"""
import collections, json, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
args = [x for x in sys.argv[1:] if not x.startswith('--')]
OUT, builds = Path(args[0]), [Path(p) for p in args[1:]]
man_path = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else None
if man_path:
    builds = [b for b in builds if str(b) != man_path]
OUT.mkdir(parents=True, exist_ok=True)
for d in ('snapshots', 'wheels_by_task', 'graphs', 'embeddings', 'sandbox', 'docker', 'wheels'):
    (OUT / d).mkdir(exist_ok=True)


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if p.exists() else []


tasks, metas, rejects, gh_cache, per_build = {}, {}, [], {}, {}
for b in builds:
    t = {r['instance_id']: r for r in jl(b / 'tasks.jsonl')}
    m = {r['instance_id']: r for r in jl(b / 'tasks_meta.jsonl')}
    ok = [i for i in t if i in m and (b / 'snapshots' / f'{i}.tgz').exists() and (b / 'wheels_by_task' / i).is_dir()]
    per_build[str(b)] = dict(valid=len(ok), rows=len(t), summary=json.loads((b / 'summary.json').read_text()) if (b / 'summary.json').exists() else None)
    for i in ok:
        if i in tasks:
            continue
        tasks[i], metas[i] = t[i], m[i]
        shutil.copy(b / 'snapshots' / f'{i}.tgz', OUT / 'snapshots' / f'{i}.tgz')
        shutil.copytree(b / 'wheels_by_task' / i, OUT / 'wheels_by_task' / i, dirs_exist_ok=True)
        key = m[i].get('graph_key')
        for sub, ext in (('graphs', '.json'), ('embeddings', '.npz')):
            if key and (b / sub / f'{key}{ext}').exists():
                shutil.copy(b / sub / f'{key}{ext}', OUT / sub / f'{key}{ext}')
    rejects += jl(b / 'rejects.jsonl')
    if (b / 'gh_cache.json').exists():
        gh_cache.update(json.loads((b / 'gh_cache.json').read_text()))
    for src, dst in (('sandbox/setup.py', 'sandbox/setup.py'),):
        if (b / src).exists():
            shutil.copy(b / src, OUT / dst)
    if (b / 'docker').is_dir():
        shutil.copytree(b / 'docker', OUT / 'docker', dirs_exist_ok=True)
(OUT / 'gh_cache.json').write_text(json.dumps(gh_cache))

if '--gh-retry' in sys.argv:
    import emit_tasks as EM
    from gh_meta import GH, pr_number
    gh = GH(OUT / 'gh_cache.json')
    fixed = 0
    for i, m in metas.items():
        if m['src'] != 'v2' and m['ps_source'] != 'gh_pr':
            got = gh.pr(m['repo'], pr_number(i))
            if got and got.get('title'):
                tasks[i]['problem_statement'] = EM.pr_text(got['title'], got.get('body'))
                m['ps_source'] = 'gh_pr'; fixed += 1
        if m.get('repo_created_source') != 'gh_api':
            rm = gh.repo(m['repo'])
            if rm and rm.get('created_at'):
                m.update(repo_created_at=EM._iso(rm['created_at']), repo_created_source='gh_api',
                         repo_created_after_2025_01=EM._iso(rm['created_at']) >= '2025-01-01',
                         repo_stars=rm.get('stargazers_count'), license=m.get('license') or rm.get('license'))
        if gh.blocked:
            break
    print(f'gh retry: {fixed} problem statements replaced, {gh.calls} calls, blocked={gh.blocked}')

order = sorted(tasks, key=lambda i: (metas[i]['repo'].lower(), i))
with open(OUT / 'tasks.jsonl', 'w') as f:
    for i in order: f.write(json.dumps(tasks[i]) + '\n')
with open(OUT / 'tasks_meta.jsonl', 'w') as f:
    for i in order: f.write(json.dumps(metas[i]) + '\n')
with open(OUT / 'rejects.jsonl', 'w') as f:
    for r in rejects:
        if r['instance_id'] not in tasks: f.write(json.dumps(r) + '\n')
man = json.loads(Path(man_path).read_text()) if man_path else {'tasks': {}}
for i, t in man.get('tasks', {}).items():
    t['valid'] = i in tasks
(OUT / 'split_manifest.json').write_text(json.dumps(man, indent=1, sort_keys=True))
(OUT / 'ids_all.txt').write_text(''.join(i + '\n' for i in order))
for s in ('A', 'B'):
    (OUT / f'ids_{s}.txt').write_text(''.join(i + '\n' for i in order if metas[i]['split'] == s))
(OUT / 'ids_new_repos.txt').write_text(''.join(i + '\n' for i in order if metas[i].get('repo_created_after_2025_01')))
(OUT / 'wheels' / 'README.txt').write_text('Per-task wheels live in wheels_by_task/<instance_id>/; point the harness wheels_dir there '
                                          'and give every task its own TMPDIR (swegemma caches unpacked wheels by a fixed name).\n')
C = collections.Counter
ms = [metas[i] for i in order]
dates = sorted(m['task_created_at'] for m in ms)
summary = dict(
    n_valid=len(order), n_repos=len({m['repo'].lower() for m in ms}), n_rejected=len(rejects) - 0,
    by_split=dict(C(m['split'] for m in ms)), by_part=dict(C(m['part'] for m in ms)), by_src=dict(C(m['src'] for m in ms)),
    by_ps_source=dict(C(m['ps_source'] for m in ms)), repo_created_after_2025_01=sum(bool(m.get('repo_created_after_2025_01')) for m in ms),
    task_created_range=[dates[0], dates[-1]] if dates else None,
    by_month=dict(sorted(C(d[:7] for d in dates).items())),
    reject_stages=dict(C(r['stage'] for r in rejects if r['instance_id'] not in tasks)),
    snapshots_gb=round(sum(f.stat().st_size for f in (OUT / 'snapshots').iterdir()) / 1e9, 2),
    wheels_gb=round(sum(f.stat().st_size for f in (OUT / 'wheels_by_task').rglob('*.whl')) / 1e9, 2),
    builds=per_build)
(OUT / 'summary.json').write_text(json.dumps(summary, indent=1))
print(json.dumps({k: v for k, v in summary.items() if k != 'builds'}, indent=1))
