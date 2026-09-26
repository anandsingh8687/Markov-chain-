"""oppprof.py EPS [side=opp|me]: market profile per player from ghost actions."""
import json, sys, collections
eps = [int(x) for x in open(sys.argv[1]).read().split()]
side = sys.argv[2] if len(sys.argv) > 2 else 'opp'
sc = json.load(open('ghost_opp_scores.json'))
rows = []
for ep in eps:
    g = json.load(open(f'ghosts/{ep}.json')); me = g['names'].index('Anand Singh'); p = 1 - me if side == 'opp' else me
    acts = g['acts'][p]; c = collections.Counter(); land = []
    for t, a in enumerate(acts):
        if not a: continue
        for o in a.get('market') or []:
            if not o: continue
            k = o[0]
            if k == 'BUY_SEED': c['seed_' + o[1]] += o[2] if len(o) > 2 else 1
            elif k == 'BUY_ANIMAL': c['an_' + o[1]] += o[2] if len(o) > 2 else 1
            elif k == 'HIRE': c['hire'] += 1
            elif k in ('BUY_LAND', 'BUY_QUADRANT', 'UNLOCK'): land.append(t // 24)
            elif k == 'SELL': c['sell_' + o[1]] += o[2] if len(o) > 2 else 1
            elif k == 'BUY_PRODUCT': c['buyp_' + o[1]] += o[2] if len(o) > 2 else 1
            else: c['k_' + k] += 1
        for h in [a.get('farmer')] + list(a.get('hands') or []):
            if h and isinstance(h, list) and h[0] == "PLANT": c['plant_' + (h[1] if len(h) > 1 else '?')] += 1
    rows.append((ep, g['names'][p], sc.get(str(ep), [None, None])[1], g['r'][p] - g['r'][1 - p], g['r'][p], c, land))
keys = sorted({k for r in rows for k in r[5]})
for ep, n, s, m, bank, c, land in rows:
    print(ep, n[:16].ljust(16), s, f"{m:+7.0f} bank {bank:7.0f} land {land}", ' '.join(f"{k}={c[k]}" for k in keys if c[k] and not k.startswith('sell_') and not k.startswith('buyp_')))
