import os, sys, time, glob, shutil, tarfile
from concurrent.futures import ThreadPoolExecutor
from kaggle.api.kaggle_api_extended import KaggleApi
api = KaggleApi(); api.authenticate()
refs = []
for sort in ('voteCount', 'dateRun', 'hotness', 'scoreDescending'):
    for page in (1, 2, 3):
        try:
            for k in api.kernels_list(competition='kaggriculture', sort_by=sort, page_size=50, page=page):
                if k.ref not in refs: refs.append(k.ref)
        except Exception as e:
            print('list err', sort, page, str(e)[:80])
print('refs', len(refs), flush=True)
def get(ref):
    d = 'nb4/' + ref.replace('/', '__')
    if os.path.exists(d + '/main.py'): return ref, 'have'
    os.makedirs(d, exist_ok=True)
    for attempt in range(4):
        try:
            api.kernels_output(ref, path=d, quiet=True)
            break
        except Exception as e:
            if '429' in str(e): time.sleep(15 * (attempt + 1)); continue
            return ref, 'err ' + str(e)[:60]
    # normalise: find main.py or a tar.gz containing it
    for f in glob.glob(d + '/**/*.tar.gz', recursive=True):
        try:
            with tarfile.open(f) as t:
                if 'main.py' in t.getnames(): t.extract('main.py', d + '/x'); shutil.copy(d + '/x/main.py', d + '/main.py'); break
        except Exception: pass
    if not os.path.exists(d + '/main.py'):
        c = glob.glob(d + '/**/main.py', recursive=True) or glob.glob(d + '/**/submission.py', recursive=True)
        if c: shutil.copy(c[0], d + '/main.py')
    return ref, 'ok' if os.path.exists(d + '/main.py') else 'nomain'
with ThreadPoolExecutor(3) as ex:
    for ref, s in ex.map(get, refs): print(s, ref, flush=True)
