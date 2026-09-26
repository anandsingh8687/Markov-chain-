import json, sys, importlib.util, collections
from kaggle_environments import make
seed = int(sys.argv[1]); mode = sys.argv[2]
params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
spec = importlib.util.spec_from_file_location("fm", "v10/foreman.py"); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm); fm.P.update(params)
ns = {'__name__': 'x'}; exec(compile(open('pool/v9_open8/main.py').read(), 'v9', 'exec'), ns); v9 = ns['agent']
F = fm.Foreman()
def ag(o, c=None):
    if mode == 'v9' or o['step'] < 144: return v9(o, c)
    return F.act(o, c)
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([ag, 'pool/prv_rain/main.py'])
for d in (8, 11, 14, 17, 20, 23, 26):
    o = env.steps[d * 24 + 12][0]['observation']; f = o['farms'][0]
    c = collections.Counter()
    for y in range(10):
        for x in range(10):
            t = f['tiles'][y][x]
            if isinstance(t, dict):
                c[t.get('animal') or (t['crop'] if t.get('kind') == 'PLANT' else t['kind'])] += 1
            elif t is None: c['empty'] += 1
    print(mode, f"d{d}", f"${f['money']:.0f}", 'hands', len(f['hands']), dict(sorted(c.items())))
print(mode, 'final', [s['reward'] for s in env.steps[-1]])
