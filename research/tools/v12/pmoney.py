import importlib.util, collections, sys
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from kaggle_environments import make
path, seed = sys.argv[1], int(sys.argv[2])
LOG = []; CUR = {}
opm, ocu = K._process_market, K._commit_unit
def pm(st, e): CUR['s'] = st; return opm(st, e)
def cu(op, item, price, farm, private, market, *a, **k):
    ok = ocu(op, item, price, farm, private, market, *a, **k)
    if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, op, item, price, st[0].observation.step))
    return ok
K._process_market, K._commit_unit = pm, cu
spec = importlib.util.spec_from_file_location("pl", path); pl = importlib.util.module_from_spec(spec); spec.loader.exec_module(pl)
Pl = pl.Planner(); hires = collections.Counter()
def ag(o, c=None):
    a = Pl.act(o, c); return a
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}); env.run([ag, 'pool/prv_rain/main.py'])
wages = 0
for st in env.steps[1:]:
    o = st[0]['observation']
for d in range(30):
    o = env.steps[min(719, d * 24 + 23)][0]['observation']; wages += sum(pl.fib(k) for k in range(o['farms'][0]['hires_today']))
rev = collections.Counter(); units = collections.Counter(); spend = collections.Counter()
for p, op, item, price, step in LOG:
    if p: continue
    if op == 'SELL': rev[item] += price; units[item] += 1
    else: spend[op + ':' + item] += price
print('bank', env.steps[-1][0]['reward'], 'wages', wages, 'land', 1000 + 2000 * (len(env.steps[-1][0]['observation']['farms'][0]['unlocked_quadrants']) >= 3) + 4000 * (len(env.steps[-1][0]['observation']['farms'][0]['unlocked_quadrants']) >= 4))
print('revenue', {k: round(v) for k, v in rev.most_common()}, 'total', round(sum(rev.values())))
print('units', dict(units))
print('spend', {k: round(v) for k, v in spend.most_common()}, 'total', round(sum(spend.values())))
for d in (2, 6, 10, 14, 20, 26):
    o = env.steps[d * 24 + 12][0]['observation']; f = o['farms'][0]
    print(f"d{d} money {f['money']:.0f} hands {len(f['hands'])} hires {f['hires_today']} tours {len(Pl.S[0].get('tours', []))} shed { {k: v for k, v in o['private']['shed'].items() if v} }")
