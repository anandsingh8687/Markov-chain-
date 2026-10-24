"""Convert SWE-rebench rows into the swegemma/Kaggle data layout (snapshot + py3.13 wheels per task).

Library use (pipeline.py): build_task(row, out, work, mirror, pip, env) -> info dict (raises BuildError).
CLI (prototype path, still works):
    python -I build.py IDS_JSON OUT_DIR PARQUET[,PARQUET...] [--jobs N]
OUT_DIR gets: tasks.jsonl, snapshots/<id>.tgz, wheels_by_task/<id>/*.whl, build_log/<id>.log

Environment knobs: EVALSET_MIRRORS (bare clones, default OUT/../mirrors), EVALSET_PIP (pip used for downloads),
EVALSET_MAX_WHEEL_MB (default 1500: tasks whose dependency wheels exceed this are dropped; GPU stacks are unlike
the hidden repos and would blow the output budget).
"""
import json, os, re, shlex, subprocess, sys, shutil, time, traceback
from pathlib import Path

ASYNC_MAX = 0.018  # hosts: private repos have <= 1.8% async functions
MAX_WHEEL_MB = float(os.environ.get('EVALSET_MAX_WHEEL_MB', '1500'))
PLATFORM = ('--only-binary=:all: --python-version 3.13 --implementation cp --abi cp313 --abi abi3 --abi none '
            '--platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 '
            '--platform any')


class BuildError(RuntimeError):
    pass


def sh(cmd, cwd=None, timeout=3600, env=None):
    try:
        return subprocess.run(['bash', '-c', cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, e.stdout or '', f'TIMEOUT after {timeout}s')


def pip_extras_and_pkgs(install: str):
    """Parse 'pip install -e .[a,b]' extras and 'pip install X Y' / '-r FILE' packages from the install string."""
    extras, pkgs = set(), []
    for part in re.split(r'&&|;', install):
        try:
            toks = shlex.split(part.strip()) if part.strip() else []
        except ValueError:
            continue
        if 'install' not in toks or not any(t.endswith('pip') for t in toks):
            continue
        rest = toks[toks.index('install') + 1:]
        i = 0
        while i < len(rest):
            t = rest[i]
            if t in ('-e', '--editable'):
                i += 1
                m = re.match(r'\.\[(.*)\]', rest[i]) if i < len(rest) else None
                if m: extras |= {e.strip() for e in m.group(1).split(',')}
            elif t in ('-r', '--requirement') and i + 1 < len(rest):
                i += 1; pkgs += ['-r', rest[i]]
            elif t.startswith('-'):
                if t in ('-c', '--index-url', '-i', '--extra-index-url', '-f', '--find-links'): i += 1
            elif re.match(r'\.\[(.*)\]', t):
                extras |= {e.strip() for e in re.match(r'\.\[(.*)\]', t).group(1).split(',')}
            elif t not in ('.',):
                pkgs.append(t)
            i += 1
    return sorted(extras), pkgs


def ensure_mirror(repo, base_commit, mirror: Path, log):
    if not mirror.exists():
        x = sh(f'git clone --bare -q https://github.com/{repo}.git {mirror}', timeout=1800)
        if x.returncode:
            shutil.rmtree(mirror, ignore_errors=True)
            raise BuildError('clone ' + x.stderr[-500:])
    if sh(f'git cat-file -e {base_commit}^{{commit}}', cwd=mirror).returncode:
        sh(f'git fetch -q origin {base_commit}', cwd=mirror, timeout=900)
        if sh(f'git cat-file -e {base_commit}^{{commit}}', cwd=mirror).returncode:
            raise BuildError(f'base commit {base_commit} not found')


def git_facts(mirror: Path, base_commit: str, pr_number):
    """First-commit date (repo age proxy) and the PR title/body as recorded in the merge/squash commit."""
    facts = {}
    roots = sh(f'git rev-list --max-parents=0 {base_commit}', cwd=mirror).stdout.split()
    if roots:
        dates = [sh(f'git show -s --format=%cI {c}', cwd=mirror).stdout.strip() for c in roots]
        facts['first_commit_date'] = min(d for d in dates if d) if any(dates) else None
    if pr_number:
        pat = rf'(\(#{pr_number}\)|pull request #{pr_number}( |$))'
        x = sh(f"git log --all -E --grep={shlex.quote(pat)} --format=%H%x1f%P%x1f%s%x1f%b%x1e", cwd=mirror)
        for rec in x.stdout.split('\x1e'):
            f = rec.strip('\n').split('\x1f')
            if len(f) < 4:
                continue
            sha, parents, subj, body = f[0], f[1].split(), f[2], f[3].strip()
            if re.match(rf'Merge pull request #{pr_number}\b', subj):  # merge commit: body = PR title (+ body)
                title, _, rest = body.partition('\n')
                facts.update(git_pr_title=title.strip(), git_pr_body=rest.strip(), git_pr_commit=sha)
                break
            if f'(#{pr_number})' in subj:  # squash merge: subject = "title (#N)", body = squashed messages
                facts.update(git_pr_title=re.sub(rf'\s*\(#{pr_number}\)\s*$', '', subj).strip(),
                             git_pr_body=body, git_pr_commit=sha)
                break
    return facts


def build_task(r, out: Path, work: Path, mirror: Path, pip='pip', env=None, log=None):
    """Build snapshot + wheels for one SWE-rebench row (pandas Series or dict). Returns an info dict."""
    log = log if log is not None else []
    get = (lambda k, d=None: r.get(k, d)) if hasattr(r, 'get') else (lambda k, d=None: getattr(r, k, d))
    iid, repo, base = get('instance_id'), get('repo'), get('base_commit')
    t0 = time.time()
    info = {}
    ensure_mirror(repo, base, mirror, log)
    m = re.search(r'-(\d+)(?:_interface)?$', iid)
    info.update(git_facts(mirror, base, int(m.group(1)) if m else None))
    ws = work / iid
    shutil.rmtree(ws, ignore_errors=True); ws.mkdir(parents=True)
    try:
        # history up to base_commit only, on branch main (like the hosts' fast-export snapshots)
        for c in ['git init -q -b tmp0', f'git fetch -q {mirror} {base}', 'git checkout -q -b main FETCH_HEAD',
                  'git config user.email agent@eval && git config user.name Agent']:
            x = sh(c, cwd=ws, timeout=1800)
            if x.returncode: raise BuildError(c + ' ' + x.stderr[-500:])
        n_async = int(sh(r"grep -rE --include='*.py' -c '^\s*async\s+def\s' . | awk -F: '{s+=$2} END{print s+0}'", cwd=ws).stdout.strip() or 0)
        n_def = int(sh(r"grep -rE --include='*.py' -c '^\s*def\s' . | awk -F: '{s+=$2} END{print s+0}'", cwd=ws).stdout.strip() or 0)
        info.update(n_async=n_async, n_def=n_def, async_frac=round(n_async / max(1, n_async + n_def), 4))
        if n_async > ASYNC_MAX * max(1, n_async + n_def):
            raise BuildError(f'async fraction {n_async}/{n_async + n_def} > 1.8%')
        x = sh(f'tar czf {out}/snapshots/{iid}.tgz -C {ws} .', timeout=1800)
        if x.returncode: raise BuildError('tar ' + x.stderr[-500:])
        info['snapshot_mb'] = round((out / 'snapshots' / f'{iid}.tgz').stat().st_size / 1e6, 1)
        # dependency closure for python 3.13
        ic = get('install_config')
        ic = ic if isinstance(ic, dict) else {}
        inst = ic.get('install')
        inst = inst if isinstance(inst, str) else ' && '.join(list(inst) if inst is not None else [])
        extras, pkgs = pip_extras_and_pkgs(inst)
        pp = ic.get('pip_packages'); pkgs += list(pp) if pp is not None else []
        pkgs = [p for p in pkgs if not p.startswith(('pytest-cov', 'coverage'))] + ['pytest']
        venv = work / (iid + '_venv')
        sh(f'uv venv -q -p 3.13 {venv}', env=env)
        spec = '.[' + ','.join(extras) + ']' if extras else '.'
        cmd = f'uv pip install -q -p {venv}/bin/python -e {shlex.quote(spec)} ' + ' '.join(p if p == '-r' else shlex.quote(p) for p in pkgs)
        x = sh(cmd, cwd=ws, timeout=1800, env=env)
        log.append(f'$ {cmd}\n{x.stdout[-2000:]}{x.stderr[-3000:]}')
        if x.returncode:
            x = sh(f'uv pip install -q -p {venv}/bin/python -e . pytest', cwd=ws, timeout=1800, env=env)
            log.append(f'fallback rc={x.returncode} {x.stderr[-2000:]}')
            if x.returncode: raise BuildError('deps install failed: ' + x.stderr[-300:])
            info['deps_fallback'] = True
        frz = sh(f'uv pip freeze -p {venv}/bin/python --exclude-editable', env=env).stdout
        reqs = [l for l in frz.splitlines() if l and not l.startswith(('-e', '#')) and ' @ ' not in l]
        wdir = out / 'wheels_by_task' / iid; wdir.mkdir(parents=True, exist_ok=True)
        (wdir / 'requirements.txt').write_text('\n'.join(reqs) + '\n')
        x = sh(f'{pip} download -q --no-deps {PLATFORM} -d {wdir} -r {wdir}/requirements.txt', timeout=1800, env=env)
        log.append(f'download rc={x.returncode} {x.stderr[-3000:]}')
        if x.returncode:  # per package, build sdists where no wheel exists
            have = {re.sub(r'[-_.]+', '_', w.name.split('-')[0]).lower() for w in wdir.glob('*.whl')}
            for q in reqs:
                n = re.sub(r'[-_.]+', '_', q.split('==')[0]).lower()
                if n in have: continue
                y = sh(f'{pip} download -q --no-deps {PLATFORM} -d {wdir} {shlex.quote(q)}', env=env)
                if y.returncode:
                    y = sh(f'{venv}/bin/python -m pip --version >/dev/null 2>&1 || uv pip install -q -p {venv}/bin/python pip; '
                           f'{venv}/bin/python -m pip wheel -q --no-deps -w {wdir} {shlex.quote(q)}', timeout=1800, env=env)
                    log.append(f'sdist-build {q} rc={y.returncode} {y.stderr[-800:]}')
                    if y.returncode: info.setdefault('missing_wheels', []).append(q)
        wb = sum(w.stat().st_size for w in wdir.glob('*.whl'))
        info.update(n_wheels=len(list(wdir.glob('*.whl'))), wheels_mb=round(wb / 1e6, 1))
        if wb > MAX_WHEEL_MB * 1e6:
            raise BuildError(f'wheels {wb / 1e6:.0f} MB > {MAX_WHEEL_MB:.0f} MB')
        info['build_seconds'] = round(time.time() - t0, 1)
        return info
    finally:
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(work / (iid + '_venv'), ignore_errors=True)


def remove_task_files(out: Path, iid: str):
    (out / 'snapshots' / f'{iid}.tgz').unlink(missing_ok=True)
    shutil.rmtree(out / 'wheels_by_task' / iid, ignore_errors=True)


def load_rows(parquets):
    import pandas as pd
    return pd.concat([pd.read_parquet(p) for p in parquets]).drop_duplicates('instance_id').set_index('instance_id', drop=False)


def main():
    from concurrent.futures import ThreadPoolExecutor
    ids_file, out, parquets = sys.argv[1], Path(sys.argv[2]), sys.argv[3].split(',')
    jobs = int(sys.argv[sys.argv.index('--jobs') + 1]) if '--jobs' in sys.argv else 3
    mirrors = Path(os.environ.get('EVALSET_MIRRORS', out.parent / 'mirrors'))
    pip = os.environ.get('EVALSET_PIP', 'pip')
    for d in ('snapshots', 'wheels_by_task', 'build_log', 'work'):
        (out / d).mkdir(parents=True, exist_ok=True)
    mirrors.mkdir(parents=True, exist_ok=True)
    want = [r['instance_id'] for r in json.load(open(ids_file))]
    df = load_rows(parquets)

    def one(iid):
        log = []
        try:
            r = df.loc[iid]
            build_task(r, out, out / 'work', mirrors / (r.repo.replace('/', '__') + '.git'), pip, log=log)
            row = dict(instance_id=iid, repo=r.repo, base_commit=r.base_commit, patch=r.patch, test_patch=r.test_patch,
                       problem_statement=r.problem_statement, hints_text='', created_at=str(r.created_at))
            return row, 'ok'
        except Exception:
            log.append(traceback.format_exc())
            return None, 'FAIL'
        finally:
            (out / 'build_log' / f'{iid}.log').write_text('\n'.join(log))

    with ThreadPoolExecutor(jobs) as pool:
        results = list(pool.map(one, want))
    with open(out / 'tasks.jsonl', 'a') as fh:
        for (row, st), iid in zip(results, want):
            print(iid, st, flush=True)
            if row: fh.write(json.dumps(row) + '\n')


if __name__ == '__main__':
    main()
