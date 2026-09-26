import json, sys, os, collections
SP = os.getcwd()
from kaggle_environments import make
ep, path = int(sys.argv[1]), sys.argv[2]
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = [v for v in ns.values() if callable(v)][-1]; acts = g['acts'][op]
def ghost(o, c=None):
    t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
ag = [None, None]; ag[me] = fn; ag[op] = ghost
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
ev = collections.defaultdict(list); prev = None
for st in env.steps:
    o = st[0]['observation']; step = o['step']; tiles = o['farms'][op]['tiles']
    if prev is not None:
        for y, row in enumerate(tiles):
            for x, t in enumerate(row):
                p = prev[y][x]
                if t == p: continue
                d, h = step // 24, step % 24
                was = isinstance(p, dict) and p.get('crop') == 'TOMATO'; now = isinstance(t, dict) and t.get('crop') == 'TOMATO'
                if now and not was: ev[(x, y)].append(f"d{d}h{h} PLANT(prev {p.get('crop') if isinstance(p, dict) else p})")
                elif was and not now: ev[(x, y)].append(f"d{d}h{h} END->{t.get('crop') if isinstance(t, dict) and t.get('crop') else (t.get('kind') if isinstance(t, dict) else t)}")
                elif was and now:
                    if p.get('yield_units', 0) > t.get('yield_units', 0) and h: ev[(x, y)].append(f"d{d}h{h} H{p['yield_units']}")
                    if t.get('fertilized_until_day', -1) > p.get('fertilized_until_day', -1): ev[(x, y)].append(f"d{d}h{h} F")
    prev = tiles
o = env.steps[432][0]['observation']
print('shops d18', o['town']['unlocked_shops'], 'tomato px d18', o['market']['prices']['TOMATO'])
for k in sorted(ev): print(k, ' | '.join(ev[k]))
