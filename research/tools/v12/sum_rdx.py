import json, collections, sys
cand = sys.argv[1] if len(sys.argv) > 1 else 'v12r'
R = collections.defaultdict(dict)
for f in ('v10/cl11e.jsonl', 'v10/cl12r.jsonl') + tuple(sys.argv[2:]):
    for r in map(json.loads, open(f)): R[r['a']][(r['seed'], r['opp'])] = r['m']
opps = ['q_demand-preserving-turn-sale-', 'r_the-shepherds-ledger-herd-', 'r_kaggriculture-top-2-master', 'r_kaggriculture-harvest-ledg', 'v9_open8', 's_ff4p', 'v11i', 'v10d']
tw = tb = 0
for o in opps:
    ks = [k for k in R[cand] if k[1] == o]
    if not ks: continue
    w = sum(R[cand][k] > 0 for k in ks)
    b = [R['v10d'][k] for k in ks if k in R['v10d']]
    d = [R[cand][k] - R['v10d'][k] for k in ks if k in R['v10d']]
    tw += w; tb += sum(x > 0 for x in b)
    print(f"{o[:28]:28s} {cand} {w}/{len(ks)}" + (f"  v10 {sum(x>0 for x in b)}/{len(b)}  paired {sum(d)/len(d):+.0f}" if d else ''))
print('total wins (excl. mirror)', tw, 'vs v10', tb)
try:
    G = {r['ep']: r['m'] for r in map(json.loads, open(f'v10/g11_{cand}.jsonl'))}
    B = {r['ep']: r['m'] for r in map(json.loads, open('v10/g11_v10d.jsonl'))}
    print(f"v11-ladder replays: {cand} {sum(x>0 for x in G.values())}/98  v10 {sum(x>0 for x in B.values())}/98  L->W {sum(B[e]<0<G[e] for e in G)} W->L {sum(G[e]<0<B[e] for e in G)}")
except Exception as e: print('ghost', e)
