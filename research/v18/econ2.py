"""econ2.py SEED A B: live game A (seat0) vs B (seat1); revenue/units/avg price per product, money by day, herd/plants."""
import json, sys, os, collections
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from kaggle_environments import make
SP = os.getcwd(); seed = int(sys.argv[1]); A, B = sys.argv[2], sys.argv[3]
LOG = []; CUR = {}
opm, ocu = K._process_market, K._commit_unit
def pm(s, e): CUR['s'] = s; return opm(s, e)
def cu(o, item, price, farm, private, market, *a, **k):
    ok = ocu(o, item, price, farm, private, market, *a, **k)
    if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, o, item, price, st[0].observation.step))
    return ok
K._process_market, K._commit_unit = pm, cu
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([f'{SP}/pool/{A}/main.py', f'{SP}/pool/{B}/main.py'])
print('final', [env.steps[-1][i]['reward'] for i in (0, 1)], env.steps[-1][0]['observation']['town']['unlocked_shops'])
for p in (0, 1):
    rev = collections.Counter(); u = collections.Counter(); sp = collections.Counter()
    for pp, o, it, pr, st in LOG:
        if pp != p: continue
        if o == 'SELL': rev[it] += pr; u[it] += 1
        else: sp[o + ':' + it] += pr
    print(['A', 'B'][p], 'rev', round(sum(rev.values())), ' '.join(f'{k[:5]} {rev[k]/1000:.1f}k/{u[k]}u@{rev[k]/max(1,u[k]):.0f}' for k in sorted(rev, key=lambda k: -rev[k])))
    print('   spend', ' '.join(f'{k} {v/1000:.1f}k' for k, v in sp.most_common(8)))
    line = []
    for d in (4, 6, 8, 10, 12, 15, 20, 25):
        f = env.steps[d * 24 + 12][0]['observation']['farms'][p]
        tiles = [t for row in f['tiles'] for t in row if isinstance(t, dict)]
        cr = collections.Counter(t.get('crop') for t in tiles if t.get('kind') == 'PLANT'); an = collections.Counter(t.get('animal') for t in tiles if t.get('animal'))
        line.append(f"d{d}:q{len(f['unlocked_quadrants'])} h{len(f['hands'])} ${f['money']/1000:.1f}k C{an.get('COW',0)}S{an.get('SHEEP',0)}G{an.get('GOOSE',0)} W{cr.get('WHEAT',0)}Ca{cr.get('CARROT',0)}T{cr.get('TOMATO',0)}St{cr.get('STRAWBERRY',0)}M{cr.get('MELON',0)}")
    print('  ', ' '.join(line))
