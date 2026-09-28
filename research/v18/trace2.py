"""trace2.py SEED A B: per-day public signals (money, q, plants, animals, hands) for both seats."""
import sys, os, json, collections
from kaggle_environments import make
SP = os.getcwd(); seed = int(sys.argv[1]); A, B = sys.argv[2], sys.argv[3]
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([f'{SP}/pool/{A}/main.py', f'{SP}/pool/{B}/main.py'])
out = {'seed': seed, 'A': A, 'B': B, 'r': [env.steps[-1][i]['reward'] for i in (0, 1)], 'd': []}
for d in range(0, 30):
    o = env.steps[min(d * 24 + 12, 719)][0]['observation']
    row = []
    for p in (0, 1):
        f = o['farms'][p]
        tiles = [t for r in f['tiles'] for t in r if isinstance(t, dict)]
        row.append([round(f['money']), len(f['unlocked_quadrants']), sum(t.get('kind') == 'PLANT' for t in tiles),
                    sum(bool(t.get('animal')) for t in tiles), len(f['hands']),
                    sum(t.get('yield_units', 0) for t in tiles)])
    out['d'].append(row)
print(json.dumps(out))
