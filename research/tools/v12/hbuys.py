import sys, os, collections
from kaggle_environments import make
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, opp, d0 = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
ns = {'__name__': 'x'}; exec(compile(open(V14).read(), V14, 'exec'), ns); a0 = [v for v in ns.values() if callable(v)][-1]
B = collections.defaultdict(collections.Counter)
def ag(o, c=None):
    a = a0(o, c)
    if o['step'] >= d0 * 24:
        for m in a.get('market') or []:
            if m and m[0] in ('BUY_SEED', 'BUY_ANIMAL', 'BUY_LAND', 'BUY_PRODUCT'):
                B[o['step'] // 24][m[0][4:] + ':' + (m[1] if len(m) > 1 else '')] += int(m[2]) if len(m) > 2 else 1
        for x in [a.get('farmer')] + list(a.get('hands') or []):
            if x and x[0] in ('PLANT', 'BUILD_PASTURE', 'BUILD_COOP'):
                B[o['step'] // 24]['op:' + x[0] + (':' + x[1] if len(x) > 1 else '')] += 1
    return a
env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([a0 if False else ag, f'{SP}/pool/{opp}/main.py'])
for d in sorted(B): print(d, dict(B[d]))
