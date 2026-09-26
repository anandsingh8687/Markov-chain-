import sys, os, collections
sys.path.insert(0, 'v10'); from sales import run
from concurrent.futures import ProcessPoolExecutor
seed, opp, agents = int(sys.argv[1]), sys.argv[2], sys.argv[3].split(',')
with ProcessPoolExecutor(2) as ex:
    res = list(ex.map(run, [(seed, a, opp) for a in agents]))
agg = {}
for a, (s, r, LOG) in zip(agents, res):
    d = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])
    for p, o, item, price, step in LOG:
        if o != 'SELL' or step < 432: continue
        x = d[item]
        if p == 0: x[0] += 1; x[1] += price
        else: x[2] += 1; x[3] += price
    agg[a] = (r, d)
    print(a, 'margin', r[0] - r[1])
items = sorted(set().union(*[set(v[1]) for v in agg.values()]))
for it in items:
    print(f"{it:10s}", ' | '.join(f"{a}: us {agg[a][1][it][0]}u ${agg[a][1][it][1]:.0f} them {agg[a][1][it][2]}u ${agg[a][1][it][3]:.0f}" for a in agents))
