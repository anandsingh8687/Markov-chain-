import json, sys, importlib.util, collections
from kaggle_environments import make
seed = int(sys.argv[1])
spec = importlib.util.spec_from_file_location("fm", "v10/foreman.py"); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm)
ns = {'__name__': 'x'}; exec(compile(open('pool/v9_open8/main.py').read(), 'v9', 'exec'), ns); v9 = ns['agent']
F = fm.Foreman(); acts = collections.defaultdict(collections.Counter)
def ag(o, c=None):
    if o['step'] < 144: return v9(o, c)
    a = F.act(o, c)
    for u in [a['farmer']] + a['hands']:
        acts[o['step'] // 24][u[0] if u[0] not in ('NORTH', 'SOUTH', 'EAST', 'WEST') else 'MOVE'] += 1
    return a
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([ag, 'pool/prv_rain/main.py'])
for d in range(6, 30):
    o = env.steps[min(719, d * 24 + 23)][0]['observation']; f = o['farms'][0]
    T = [f['tiles'][y][x] for y in range(10) for x in range(10)]
    an = sum(1 for t in T if isinstance(t, dict) and 'animal' in t)
    unfed = sum(1 for t in T if isinstance(t, dict) and 'animal' in t and not t['fed_today'])
    pl = sum(1 for t in T if isinstance(t, dict) and t.get('kind') == 'PLANT')
    dry = sum(1 for t in T if isinstance(t, dict) and t.get('kind') == 'PLANT' and not t['watered_today'])
    wd = sum(1 for t in T if isinstance(t, dict) and t.get('kind') == 'WEED')
    emp = sum(1 for t in T if t is None)
    st = sum(1 for t in T if isinstance(t, dict) and t.get('kind') in ('COOP', 'PASTURE') and 'animal' not in t)
    c = acts[d]
    print(f"d{d} $ {f['money']:7.0f} hands {len(f['hands']):2d} animals {an:2d} unfed@23 {unfed:2d} plants {pl:2d} dry@23 {dry:2d} weeds {wd:2d} empty {emp:2d} emptyStruct {st:2d} | " + ' '.join(f"{k}:{v}" for k, v in sorted(c.items())))
print('final', [s['reward'] for s in env.steps[-1]])
