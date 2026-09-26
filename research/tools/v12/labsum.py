import json, collections, statistics as S
M = json.load(open('top_meta.json')); tops = set(k for k in M if k != 'eps')
G = collections.defaultdict(list)
for l in open('v12/labor.jsonl'):
    r = json.loads(l)
    for p, s in r['seats'].items():
        grp = 'TOP' if s['name'] in tops else ('US' if s['name'] == 'Anand Singh' else 'OTHER')
        G[grp].append(s)
def mean(xs): return round(S.mean(xs), 1) if xs else 0
for grp in ('TOP', 'US', 'OTHER'):
    L = G[grp]
    if not L: continue
    ut = [s['unit_turns'] for s in L]
    fr = lambda k: mean([s['ops'].get(k, 0) / s['unit_turns'] * 100 for s in L])
    work = ['WATER', 'FEED', 'CARE', 'HARVEST', 'COLLECT_FERTILIZER', 'PLANT', 'FERTILIZE', 'PICKUP', 'DROP', 'PLACE', 'DIG', 'BUILD_PASTURE', 'BUILD_COOP']
    print(f"== {grp}: n={len(L)} bank {mean([s['bank'] for s in L]):,.0f}  unit-turns {mean(ut):,.0f}  hires/day {mean([s['hires']/30 for s in L])}")
    print('   % of unit-turns:', {k: fr(k) for k in ['MOVE', 'PASS'] + work if fr(k) >= 0.5})
    for d in ('6', '10', '14', '20', '26'):
        land = mean([s['comp'].get(d, {}).get('land', 0) for s in L])
        an = collections.Counter(); cr = collections.Counter()
        for s in L:
            an.update(s['comp'].get(d, {}).get('animals', {})); cr.update(s['comp'].get(d, {}).get('crops', {}))
        print(f"   d{d}: land {land} money {mean([s['comp'].get(d, {}).get('money', 0) for s in L]):,.0f} animals { {k: round(v/len(L),1) for k, v in an.items()} } crops { {k: round(v/len(L),1) for k, v in cr.items()} }")
    rev = collections.Counter()
    for s in L: rev.update(s['revenue'])
    print('   revenue/game:', {k: round(v / len(L)) for k, v in rev.most_common()})
    sp = collections.Counter()
    for s in L: sp.update(s['spend'])
    print('   spend/game:', {k: round(v / len(L)) for k, v in sp.most_common(8)})
