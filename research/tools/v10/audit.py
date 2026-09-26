"""Per-crop execution audit from observation diffs (player 0)."""
import json, sys, importlib.util, collections
from kaggle_environments import make
seed = int(sys.argv[1]); mode = sys.argv[2]; params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
spec = importlib.util.spec_from_file_location("fm", "v10/foreman.py"); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm); fm.P.update(params)
ns = {'__name__': 'x'}; exec(compile(open('pool/v9_open8/main.py').read(), 'v9', 'exec'), ns); v9 = ns['agent']
F = fm.Foreman(); A = collections.Counter(); prev = {}
def key(t):
    if not isinstance(t, dict): return t
    return (t.get('kind'), t.get('crop') or t.get('animal'), t.get('planted_day'), t.get('yield_units'), t.get('fertilized_until_day'))
def ag(o, c=None):
    f = o['farms'][0]; step = o['step']
    if 'tiles' in prev and step >= 144:
        for y in range(10):
            for x in range(10):
                a, b = prev['tiles'][y][x], f['tiles'][y][x]
                if isinstance(b, dict) and b.get('kind') == 'PLANT' and not (isinstance(a, dict) and a.get('kind') == 'PLANT' and a.get('planted_day') == b.get('planted_day')):
                    A[('plant', b['crop'])] += 1
                if isinstance(a, dict) and a.get('kind') == 'PLANT' and isinstance(b, dict) and b.get('kind') == 'WEED':
                    A[('died', a['crop'])] += 1
                    A[('died_age', a['crop'], step // 24 - 1 - a['planted_day'], a.get('yield_units', 0))] += 1
                if isinstance(a, dict) and isinstance(b, dict) and a.get('kind') == 'PLANT' and b.get('kind') == 'PLANT' and int(b.get('fertilized_until_day', -1)) > int(a.get('fertilized_until_day', -1)):
                    A[('fert', a['crop'])] += 1
                if isinstance(a, dict) and a.get('yield_units', 0) > 0:
                    gone = (not isinstance(b, dict)) or b.get('kind') != a.get('kind') or b.get('yield_units', 0) < a.get('yield_units', 0) and (b.get('planted_day') == a.get('planted_day') or 'animal' in a)
                    same_day = step % 24 != 0
                    if gone and same_day:
                        k = a.get('crop') or a.get('animal'); A[('units', k)] += a['yield_units'] - (b.get('yield_units', 0) if isinstance(b, dict) and b.get('kind') == a.get('kind') else 0)
    prev['tiles'] = json.loads(json.dumps(f['tiles']))
    if mode == 'v9' or step < 144: return v9(o, c)
    return F.act(o, c)
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([ag, 'pool/prv_rain/main.py'])
print(mode, 'final', [s['reward'] for s in env.steps[-1]])
print('  strawberry deaths (age, units lost):', sorted((k[2], k[3], v) for k, v in A.items() if k[0] == 'died_age' and k[1] == 'STRAWBERRY'))
for c in ('WHEAT', 'CARROT', 'TOMATO', 'STRAWBERRY', 'MELON', 'COW', 'SHEEP', 'GOOSE'):
    print(f"  {c:10s} planted {A[('plant', c)]:4d} harvested_units {A[('units', c)]:4d} died {A[('died', c)]:3d} fertilized {A[('fert', c)]:3d}")
