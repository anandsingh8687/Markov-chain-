import json, collections
B = {r['ep']: r for r in json.load(open('v10_opp_bands.json'))}
def profile(acts):
    land = []; animals = collections.Counter(); an_day = collections.defaultdict(int); crops = collections.Counter(); hires = collections.Counter(); tom_first = None
    for t, a in enumerate(acts):
        if not a or t == 0: continue
        d = (t - 1) // 24
        for o in a.get('market') or []:
            if not o: continue
            if o[0] == 'BUY_LAND': land.append(d)
            elif o[0] == 'BUY_ANIMAL' and len(o) > 1:
                n = int(o[2]) if len(o) > 2 else 1; animals[o[1]] += n
                if d <= 12: an_day[o[1]] += n
            elif o[0] == 'HIRE': hires[d] += 1
        for c in [a.get('farmer')] + list(a.get('hands') or []):
            if c and c[0] == 'PLANT' and len(c) > 1:
                crops[c[1]] += 1
                if c[1] == 'TOMATO' and tom_first is None: tom_first = d
    return {'land': land, 'animals': dict(animals), 'animals_by_d12': dict(an_day), 'crops': dict(crops), 'hires_per_day': round(sum(hires.values()) / max(1, len(hires)), 1), 'tomato_from': tom_first}
rows = []
for ep, r in B.items():
    try: g = json.load(open(f'ghosts/{ep}.json'))
    except Exception: continue
    me = g['names'].index('Anand Singh'); op = 1 - me
    rows.append((r['score'] or 0, r['m'], r['opp'], profile(g['acts'][op]), profile(g['acts'][me])))
rows.sort(key=lambda x: -x[0])
for s, m, n, p, q in rows[:14]:
    print(f"{s:6.0f} {n[:14]:14s} m{m:+7.0f} | land d{p['land']} animals {p['animals']} (by d12 {p['animals_by_d12']}) crops {p['crops']} hires/d {p['hires_per_day']} tomato from d{p['tomato_from']}")
print('\nUS (typical):', rows[0][4])
