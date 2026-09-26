"""Compare variant jsonl (h2h format) against v9 default rows from adapt2 (+ self-play baseline = 0)."""
import json, sys, collections
base = {}
for l in open('v10/adapt2.jsonl'):
    r = json.loads(l)
    if r['route'] is None: base[(r['seed'], r['opp'])] = r['m']
T = collections.defaultdict(list)
for l in open(sys.argv[1]):
    r = json.loads(l); k = (r['seed'], r['opp'])
    if k not in base: continue
    n = sum(s in ('PIZZA_SHOP', 'FARMERS_MARKET') for s in r['s18'])
    T[(r['opp'], min(n, 3))].append((r['m'], base[k]))
    T[('ALL', min(n, 3))].append((r['m'], base[k]))
for key in sorted(T):
    L = T[key]; d = [a - b for a, b in L]
    w = sum(a > 0 for a, b in L); wb = sum(b > 0 for a, b in L)
    ch = sum(abs(x) > 0.5 for x in d)
    print(f"{key[0][:14]:14s} tomato-shops@d18={key[1]} n={len(L):3d} changed={ch:3d} mean delta {sum(d)/len(d):+7.0f}  wins {wb}->{w}")
