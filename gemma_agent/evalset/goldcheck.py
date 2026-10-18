"""Gold / empty patch check of one task through the official verifier (run_official.py --phase2-only).

Library: check(row, snapshot, wheels_dir, base, cfg, rounds=2) -> dict(valid, runs=[...], reason)
CLI:     python -I goldcheck.py DATA_DIR ID [ID...]   (DATA_DIR = build layout: tasks.jsonl, snapshots/, wheels_by_task/)
         env: EVALSET_HPY (python with swegemma), EVALSET_OFFICIAL (run_official.py), EVALSET_PY313,
              EVALSET_IMAGE (dir holding a prepared image313/), EVALSET_COMPDATA (dir with docker/ and sandbox/setup.py)

Each task gets its own data dir (only its row in tasks.jsonl, its wheels as wheels/) and its own TMPDIR, because
the harness caches the unpacked wheels in $TMPDIR/swegemma_sp_cache_v8 under a fixed name whatever the wheel set.
Valid = gold resolved in every round and empty unresolved in every round. Order gold1, empty1, gold2, empty2 with an
early exit on the first disqualifying run.
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path


def _run(mode, k, iid, dt, cfg, timeout):
    res = dt / f'res_{mode}{k}'
    shutil.rmtree(res, ignore_errors=True)
    env = dict(os.environ, TMPDIR=str(dt / 'tmp'))
    (dt / 'tmp').mkdir(exist_ok=True)
    cmd = [cfg['hpy'], '-I', cfg['official'], '--phase2-only', mode, '--deps', 'image', '--no-graphs',
           '--data', str(dt), '--ids', iid, '--results', str(res), '--workdir', str(dt / 'w'),
           '--python313', cfg['py313']]
    t0 = time.time()
    try:
        x = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        out = x.stdout + x.stderr
    except subprocess.TimeoutExpired as e:
        out = f'TIMEOUT {timeout}s ' + str(e.stdout or '')[-2000:]
    row = {}
    try:
        row = json.loads((res / 'results.jsonl').read_text().splitlines()[-1])
    except Exception:
        pass
    run = dict(mode=mode, round=k, resolved=bool(row.get('resolved')), status=row.get('status'),
               test_exit_code=row.get('test_exit_code'), seconds=round(time.time() - t0, 1),
               error=str(row.get('error') or '')[:600], tail=(row.get('test_tail') or out[-1500:])[-1500:])
    # sandbox dirs, unpacked-wheel cache and results are throwaway
    for d in (dt / 'w', dt / 'tmp', res):
        shutil.rmtree(d, ignore_errors=True)
    return run


def check(row, snapshot: Path, wheels_dir: Path, base: Path, cfg, rounds=2, timeout=1200):
    iid = row['instance_id']
    dt = base / iid
    shutil.rmtree(dt, ignore_errors=True)
    (dt / 'snapshots').mkdir(parents=True)
    (dt / 'sandbox').mkdir()
    (dt / 'tasks.jsonl').write_text(json.dumps(row) + '\n')
    (dt / 'snapshots' / f'{iid}.tgz').symlink_to(snapshot.resolve())
    (dt / 'wheels').symlink_to(wheels_dir.resolve())
    (dt / 'image313').symlink_to((Path(cfg['image']) / 'image313').resolve())
    (dt / 'docker').symlink_to((Path(cfg['compdata']) / 'docker').resolve())
    shutil.copy(Path(cfg['compdata']) / 'sandbox' / 'setup.py', dt / 'sandbox' / 'setup.py')
    runs, reason = [], None
    try:
        for k in range(1, rounds + 1):
            g = _run('gold', k, iid, dt, cfg, timeout); runs.append(g)
            if not g['resolved']:
                reason = f'gold failed (round {k}, status={g["status"]}, exit={g["test_exit_code"]})'; break
            e = _run('empty', k, iid, dt, cfg, timeout); runs.append(e)
            if e['resolved']:
                reason = f'empty patch passes (round {k})'; break
    finally:
        shutil.rmtree(dt, ignore_errors=True)
    return dict(valid=reason is None, reason=reason, runs=runs)


def cfg_from_env():
    return dict(hpy=os.environ['EVALSET_HPY'], official=os.environ['EVALSET_OFFICIAL'], py313=os.environ['EVALSET_PY313'],
                image=os.environ['EVALSET_IMAGE'], compdata=os.environ['EVALSET_COMPDATA'])


if __name__ == '__main__':
    D = Path(sys.argv[1])
    rows = {json.loads(l)['instance_id']: json.loads(l) for l in open(D / 'tasks.jsonl') if l.strip()}
    cfg = cfg_from_env()
    for iid in sys.argv[2:]:
        r = check(rows[iid], D / 'snapshots' / f'{iid}.tgz', D / 'wheels_by_task' / iid, D / 'per_task', cfg)
        print(iid, 'VALID' if r['valid'] else 'INVALID', r['reason'] or '', [(x['mode'], x['resolved'], x['seconds']) for x in r['runs']], flush=True)
