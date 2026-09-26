import json, sys, collections
V = {}
for l in open('games.jsonl'):
    d = json.loads(l); V[d['ep']] = d['ver']
R = collections.defaultdict(dict)
for f in sys.argv[1:]:
    for l in open(f):
        d = json.loads(l)
        if None in d['r']: continue
        R[d['cand']][d['ep']] = (d['r'][0] - d['r'][1], d['orig'][0] - d['orig'][1])
eps = set.intersection(*[set(v) for v in R.values()])
print("common eps", len(eps))
for c, D in R.items():
    for grp in ('lost', 'tied', 'won', 'all'):
        sel = [e for e in eps if grp == 'all' or (grp == 'lost' and D[e][1] < 0) or (grp == 'tied' and D[e][1] == 0) or (grp == 'won' and D[e][1] > 0)]
        if not sel: continue
        m = [D[e][0] for e in sel]
        print(f"{c:12s} {grp:5s} n={len(sel):3d} W={sum(x>0 for x in m):3d} T={sum(x==0 for x in m):2d} L={sum(x<0 for x in m):3d} mean={sum(m)/len(m):7.0f}")
