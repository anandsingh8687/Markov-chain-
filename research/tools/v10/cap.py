import json, sys, importlib.util, collections
from kaggle_environments import make
seed = int(sys.argv[1]); params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
spec = importlib.util.spec_from_file_location("fm", "v10/foreman.py"); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm); fm.P.update(params)
ns = {'__name__': 'x'}; exec(compile(open('pool/v9_open8/main.py').read(), 'v9', 'exec'), ns); v9 = ns['agent']
F = fm.Foreman(); rec = collections.defaultdict(dict); acts = collections.defaultdict(collections.Counter)
def crit(o):
    f = o['farms'][0]; n = 0; m = 0
    for y in range(10):
        for x in range(10):
            t = f['tiles'][y][x]
            if isinstance(t, dict) and t.get('kind') == 'PLANT':
                w = fm.water_needed(t, o['step'] // 24)
                n += w == 2; m += w == 1
            if isinstance(t, dict) and 'animal' in t and not t['fed_today']: n += 1
    return n, m
def ag(o, c=None):
    if o['step'] < 144: return v9(o, c)
    d, h = divmod(o['step'], 24)
    if h in (1, 12, 23):
        rec[d][h] = crit(o)
    rec[d]['hands'] = len(o['farms'][0]['hands'])
    a = F.act(o, c)
    for u in [a['farmer']] + a['hands']:
        acts[d]['MOVE' if u[0] in ('NORTH', 'SOUTH', 'EAST', 'WEST') else u[0]] += 1
    if h == 1:
        s = F.st[0]; rec[d]['route_cost'] = [round(x) for x in s.get('route_cost', [])]
    return a
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([ag, 'pool/prv_rain/main.py'])
for d in sorted(rec):
    r = rec[d]; c = acts[d]
    print(f"d{d} hands {r.get('hands')} crit/opt h1 {r.get(1)} h12 {r.get(12)} h23 {r.get(23)} | MOVE {c['MOVE']} WATER {c['WATER']} PASS {c['PASS']} FEED {c['FEED']} HARV {c['HARVEST']} PLANT {c['PLANT']} | routecost {r.get('route_cost')}")
print('final', [s['reward'] for s in env.steps[-1]])
