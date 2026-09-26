import json, collections, sys
T = collections.defaultdict(lambda: collections.defaultdict(list))
for f in sys.argv[1:]:
    for r in map(json.loads, open(f)): T[r['a']][r['opp']].append(r['m'])
opps = sorted({o for a in T for o in T[a]})
print('agent'.ljust(34) + ''.join(o[:9].rjust(10) for o in opps) + '   total W   mean')
for a in T:
    row = a[:33].ljust(34); W = N = 0; S = 0
    for o in opps:
        m = T[a].get(o, [])
        w = sum(x > 0 for x in m); W += w; N += len(m); S += sum(m)
        row += (f"{w}/{len(m)}" if m else '-').rjust(10)
    print(row + f"   {W}/{N}  {S/max(1,N):+6.0f}")
