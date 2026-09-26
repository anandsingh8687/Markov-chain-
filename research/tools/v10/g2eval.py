import json, collections, sys
V=[json.loads(l) for l in open('v10/g2.jsonl')]
B={(r['seed'],r['opp']):r for r in map(json.loads,open('v10/g2base.jsonl'))} if len(sys.argv)<2 else {}
for opp in ('v9_open8','prv_rain'):
    for n in (0,1,2,3):
        L=[r for r in V if r['opp']==opp and min(3,sum(s in('PIZZA_SHOP','FARMERS_MARKET') for s in r['s18']))==n]
        if not L: continue
        if opp=='v9_open8':
            ms=[r['m'] for r in L]; print(f"{opp:10s} n@d18={n} games {len(L):3d} mean margin {sum(ms)/len(ms):+6.0f}  W-L {sum(m>0 for m in ms)}-{sum(m<0 for m in ms)}")
        else:
            P=[(r['m'],B[(r['seed'],opp)]['m']) for r in L if (r['seed'],opp) in B]
            if P: print(f"{opp:10s} n@d18={n} games {len(P):3d} delta {sum(a-b for a,b in P)/len(P):+6.0f}  wins {sum(b>0 for a,b in P)}->{sum(a>0 for a,b in P)}")
