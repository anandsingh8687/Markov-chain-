"""In-kernel eval-set build for one shard: build -> gold/empty check x2 -> keep or delete -> graph -> metadata.

python -I pipeline.py --cands part1.json --parquets a.parquet,b.parquet --out /kaggle/working/evalset \
    --work /tmp/eb --hpy /tmp/hv/bin/python --official run_official.py --py313 /path/python3.13 \
    --image /tmp/eb/img --compdata /tmp/eb/compdata --jobs 4 --deadline-hours 9.5 --max-out-gb 16

Output (OUT):
  tasks.jsonl          valid tasks only, the 8 competition fields, PR-style problem_statement, hints_text ""
  tasks_meta.jsonl     one row per valid task (source, licence, split, part, F2P/P2P, dates, ps_source, timings...)
  rejects.jsonl        one row per dropped candidate with the stage and reason
  snapshots/<id>.tgz   repo at base_commit with history, branch main (hosts' format)
  wheels_by_task/<id>/ py3.13 wheels (+ requirements.txt) for that task; use as the harness wheels_dir
  graphs/<name>_<commit>.json, embeddings/<name>_<commit>.npz   approximate code graphs (make_graph.py)
  build_log/<id>.log   build / check transcript per candidate
  gh_cache.json        GitHub API responses (PRs, repos)   progress.log, status.json
Candidates of one repo run in the same worker one after another, then the repo's mirror is deleted.
"""
import argparse, collections, json, os, re, shutil, subprocess, sys, tarfile, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402
import emit_tasks as EM  # noqa: E402
import goldcheck as GC  # noqa: E402
from gh_meta import GH  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--cands', required=True); ap.add_argument('--parquets', required=True)
ap.add_argument('--out', required=True); ap.add_argument('--work', required=True)
ap.add_argument('--hpy', required=True); ap.add_argument('--official', required=True)
ap.add_argument('--py313', required=True); ap.add_argument('--image', required=True)
ap.add_argument('--compdata', required=True); ap.add_argument('--manifest', default=None)
ap.add_argument('--jobs', type=int, default=4); ap.add_argument('--rounds', type=int, default=2)
ap.add_argument('--deadline-hours', type=float, default=9.5); ap.add_argument('--max-out-gb', type=float, default=16)
ap.add_argument('--check-timeout', type=int, default=1200)
a = ap.parse_args()
T0 = time.time()
OUT, WORK = Path(a.out), Path(a.work)
for d in ('snapshots', 'wheels_by_task', 'build_log', 'graphs', 'embeddings'):
    (OUT / d).mkdir(parents=True, exist_ok=True)
for d in ('mirrors', 'build', 'check', 'graph', 'uvcache'):
    (WORK / d).mkdir(parents=True, exist_ok=True)
LOCK = threading.Lock()
PLOG = open(OUT / 'progress.log', 'a', buffering=1)


def log(*x):
    msg = time.strftime('%H:%M:%S ') + f'[{(time.time() - T0) / 3600:.2f}h] ' + ' '.join(str(v) for v in x)
    with LOCK:
        print(msg, flush=True); PLOG.write(msg + '\n')


def append(name, row):
    with LOCK, open(OUT / name, 'a') as fh:
        fh.write(json.dumps(row, default=str) + '\n')


def du_gb(p):
    return sum(f.stat().st_size for f in Path(p).rglob('*') if f.is_file() and not f.is_symlink()) / 1e9


cands = json.load(open(a.cands))
man = json.load(open(a.manifest))['tasks'] if a.manifest else {}
df = B.load_rows(a.parquets.split(','))
gh = GH(OUT / 'gh_cache.json')
cfg = dict(hpy=a.hpy, official=a.official, py313=a.py313, image=a.image, compdata=a.compdata)
done = set()
for name in ('tasks_meta.jsonl', 'rejects.jsonl'):  # resumable
    if (OUT / name).exists():
        done |= {json.loads(l)['instance_id'] for l in open(OUT / name) if l.strip()}
groups = collections.OrderedDict()
for c in cands:
    if c['instance_id'] not in done:
        groups.setdefault(c['repo'].lower(), []).append(c)
stats = collections.Counter()
stop = {'reason': None}


def to_list(x):
    try:
        return [str(v) for v in list(x)]
    except TypeError:
        return []


def meta_row(c, r, info, chk, src_ps):
    m = r.get('meta') if hasattr(r, 'get') else None
    llm = {}
    if isinstance(m, dict):
        llm = m.get('llm_metadata') or m.get('llm_score') or {}
        llm = llm if isinstance(llm, dict) else {}
    repo_meta = gh.repo(r['repo']) or {}
    repo_created = repo_meta.get('created_at') or info.get('first_commit_date')
    repo_created = EM._iso(repo_created) if repo_created else None
    lic = r.get('license') if hasattr(r, 'get') else None
    mm = man.get(c['instance_id'], {})
    return dict(
        instance_id=c['instance_id'], repo=r['repo'], src=c['src'],
        dataset={'lb': 'nebius/SWE-rebench-leaderboard', 'v2': 'nebius/SWE-rebench-V2', 'rb': 'nebius/SWE-rebench'}[c['src']],
        split=mm.get('split', c.get('split')), part=mm.get('part', c.get('part')),
        task_created_at=EM._iso(r['created_at']),
        repo_created_at=repo_created, repo_created_source='gh_api' if repo_meta.get('created_at') else ('git_first_commit' if repo_created else None),
        repo_first_commit=EM._iso(info['first_commit_date']) if info.get('first_commit_date') else None,
        repo_created_after_2025_01=bool(repo_created and str(repo_created) >= '2025-01-01'),
        repo_stars=repo_meta.get('stargazers_count'),
        ps_source=src_ps, license=lic if isinstance(lic, str) else repo_meta.get('license'),
        FAIL_TO_PASS=to_list(r['FAIL_TO_PASS']), PASS_TO_PASS=to_list(r['PASS_TO_PASS']),
        difficulty=llm.get('difficulty'), llm_code=llm.get('code'),
        gold_lines=c.get('gold_lines'), n_files=c.get('n_files'), python_orig=c.get('python'),
        async_frac=info.get('async_frac'), snapshot_mb=info.get('snapshot_mb'), wheels_mb=info.get('wheels_mb'),
        n_wheels=info.get('n_wheels'), missing_wheels=info.get('missing_wheels'), deps_fallback=info.get('deps_fallback', False),
        build_seconds=info.get('build_seconds'),
        check=[{k: x[k] for k in ('mode', 'round', 'resolved', 'seconds', 'test_exit_code')} for x in chk['runs']],
        gold_seconds_max=max([x['seconds'] for x in chk['runs'] if x['mode'] == 'gold'] or [None]),
        graph_key=f"{r['repo'].rsplit('/', 1)[-1]}_{r['base_commit']}", graph_nodes=info.get('graph_nodes'))


def make_graph(iid, r, info):
    key = f"{r['repo'].rsplit('/', 1)[-1]}_{r['base_commit']}"
    ws = WORK / 'graph' / iid
    shutil.rmtree(ws, ignore_errors=True); ws.mkdir(parents=True)
    try:
        with tarfile.open(OUT / 'snapshots' / f'{iid}.tgz') as tf:
            mem = [m for m in tf.getmembers() if not (m.name.startswith(('./.git/', '.git/')) or m.name in ('./.git', '.git'))
                   and (m.isdir() or m.isfile())]
            tf.extractall(ws, members=mem, **({'filter': 'data'} if sys.version_info >= (3, 12) else {}))
        x = subprocess.run([sys.executable, '-I', str(HERE / 'make_graph.py'), str(ws), key,
                            str(OUT / 'graphs' / f'{key}.json'), str(OUT / 'embeddings' / f'{key}.npz')],
                           capture_output=True, text=True, timeout=1800)
        if x.returncode:
            raise RuntimeError(x.stderr[-800:])
        m = re.match(r'(\d+) nodes (\d+) edges', x.stdout.strip().splitlines()[-1])
        info.update(graph_nodes=int(m.group(1)) if m else None)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def one(c, wid):
    iid = c['instance_id']
    blog, stage = [], 'build'
    env = dict(os.environ, UV_CACHE_DIR=str(WORK / 'uvcache' / f'w{wid}'), PIP_NO_CACHE_DIR='1')
    try:
        r = df.loc[iid]
        mirror = WORK / 'mirrors' / (r['repo'].replace('/', '__') + '.git')
        info = B.build_task(r, OUT, WORK / 'build', mirror, os.environ.get('EVALSET_PIP', 'pip'), env, blog)
        stage = 'emit'
        row, src_ps = EM.task_row(r, c['src'], info, None)  # GitHub only for tasks that survive the check
        stage = 'check'
        chk = GC.check(row, OUT / 'snapshots' / f'{iid}.tgz', OUT / 'wheels_by_task' / iid, WORK / 'check', cfg,
                       rounds=a.rounds, timeout=a.check_timeout)
        blog.append('check: ' + json.dumps({k: v for k, v in chk.items() if k != 'runs'}) + '\n' +
                    '\n'.join(f"  {x['mode']}{x['round']} resolved={x['resolved']} {x['seconds']}s exit={x['test_exit_code']} "
                              f"{x['error'][:300]}\n    tail: {x['tail'][-700:]!r}" for x in chk['runs']))
        if not chk['valid']:
            B.remove_task_files(OUT, iid)
            append('rejects.jsonl', dict(instance_id=iid, repo=r['repo'], src=c['src'], stage='check', reason=chk['reason'],
                                         runs=[{k: x[k] for k in ('mode', 'round', 'resolved', 'seconds', 'status')} for x in chk['runs']],
                                         **{k: info.get(k) for k in ('wheels_mb', 'snapshot_mb', 'async_frac')}))
            stats['invalid'] += 1
            log(f'INVALID {iid}: {chk["reason"]}')
            return
        stage = 'emit'
        row, src_ps = EM.task_row(r, c['src'], info, gh)
        stage = 'graph'
        try:
            make_graph(iid, r, info)
        except Exception as e:  # a missing graph only disables the graph tools for this task
            blog.append('graph failed: ' + str(e)[-500:])
        stage = 'meta'
        meta = meta_row(c, r, info, chk, src_ps)
        append('tasks.jsonl', row)
        append('tasks_meta.jsonl', meta)
        stats['valid'] += 1
        log(f'VALID {iid} ps={src_ps} gold={meta["gold_seconds_max"]}s wheels={info.get("wheels_mb")}MB snap={info.get("snapshot_mb")}MB')
    except Exception as e:
        blog.append(traceback.format_exc())
        B.remove_task_files(OUT, iid)
        reason = str(e).splitlines()[0][:300] if str(e) else type(e).__name__
        append('rejects.jsonl', dict(instance_id=iid, repo=c['repo'], src=c['src'], stage=stage, reason=reason))
        stats[f'fail_{stage}'] += 1
        log(f'FAIL[{stage}] {iid}: {reason}')
    finally:
        (OUT / 'build_log' / f'{iid}.log').write_text('\n'.join(blog))


def worker(wid, queue):
    while True:
        with LOCK:
            if not queue or stop['reason']:
                return
            repo, items = queue.pop(0)
        for c in items:
            el = (time.time() - T0) / 3600
            if el > a.deadline_hours:
                stop['reason'] = stop['reason'] or f'deadline {a.deadline_hours} h'
            if not stop['reason'] and du_gb(OUT) > a.max_out_gb:
                stop['reason'] = f'output > {a.max_out_gb} GB'
            if stop['reason']:
                append('rejects.jsonl', dict(instance_id=c['instance_id'], repo=c['repo'], src=c['src'], stage='skipped', reason=stop['reason']))
                stats['skipped'] += 1
                continue
            one(c, wid)
        shutil.rmtree(WORK / 'mirrors' / (items[0]['repo'].replace('/', '__') + '.git'), ignore_errors=True)
        shutil.rmtree(WORK / 'uvcache' / f'w{wid}', ignore_errors=True)
        st = shutil.disk_usage(str(WORK))
        (OUT / 'status.json').write_text(json.dumps(dict(stats, elapsed_h=round((time.time() - T0) / 3600, 2),
                                                         remaining_repos=len(queue), work_free_gb=round(st.free / 1e9, 1),
                                                         out_gb=round(du_gb(OUT), 2), gh_blocked=gh.blocked)))


queue = list(groups.items())
log(f'start: {sum(len(v) for v in groups.values())} candidates in {len(groups)} repos ({len(done)} already done), jobs={a.jobs}')
with ThreadPoolExecutor(a.jobs) as pool:
    for f in [pool.submit(worker, i, queue) for i in range(a.jobs)]:
        f.result()
# leftovers when stopped early
for repo, items in queue:
    for c in items:
        append('rejects.jsonl', dict(instance_id=c['instance_id'], repo=c['repo'], src=c['src'], stage='skipped', reason=stop['reason']))
        stats['skipped'] += 1
summary = dict(stats, elapsed_h=round((time.time() - T0) / 3600, 2), out_gb=round(du_gb(OUT), 2), stop=stop['reason'],
               gh_calls=gh.calls, gh_blocked=gh.blocked)
(OUT / 'summary.json').write_text(json.dumps(summary, indent=1))
log('done', summary)
