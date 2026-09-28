import json, os, collections, sys
def sig(A):
    m = [(o[0], o[1] if len(o) > 1 else '') for o in ((A[2] if len(A) > 2 else None) or {}).get('market') or [] if o and o[0] in ('BUY_SEED','BUY_ANIMAL','BUY_LAND','HIRE')]
    return 'pipe7' if m[:6] == [('HIRE', '')] * 5 + [('BUY_ANIMAL', 'COW')] else 'other'
if __name__ == "__main__":
    d = json.load(open('v18live.json')); b = json.load(open('bands12.json'))
    fam = collections.defaultdict(list)
    for n, rows in list(d.items()) + [('v16', b['v16']), ('v17', b['v17'])]:
        for r in rows:
            f = f'ghosts/{r["ep"]}.json'
            if not os.path.exists(f): continue
            g = json.load(open(f)); me = g['names'].index('Anand Singh')
            fam[(n, sig(g['acts'][1 - me]))].append(r['m'])
    for k, v in sorted(fam.items()): print(k, len(v), 'W', sum(x > 0 for x in v), 'L', sum(x < 0 for x in v), 'mean', round(sum(v) / len(v)))
