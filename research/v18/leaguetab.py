import json, collections, sys
names = {l.split()[0]: l.split()[1][:28] for l in open('league.txt')}
names.update({'g_haideptry_2965_latest_20260927': 'haideptry2965'})
d = collections.defaultdict(list)
for f in sys.argv[1:]:
    for l in open(f):
        r = json.loads(l); d[(r['a'], r['opp'])].append(r['m'])
agents = sorted(set(a for a, o in d)); opps = sorted(set(o for a, o in d))
print('opponent'.ljust(30) + ''.join(a[:12].rjust(16) for a in agents))
tot = collections.defaultdict(lambda: [0, 0, 0.0])
for o in opps:
    row = names.get(o, o)[:29].ljust(30)
    for a in agents:
        v = d.get((a, o))
        if v:
            row += f"{sum(x>0 for x in v):>4d}-{sum(x<0 for x in v):<2d}{sum(v)/len(v)/1000:+6.1f}k  "
            t = tot[a]; t[0] += sum(x > 0 for x in v); t[1] += len(v); t[2] += sum(v)
        else: row += ' ' * 16
    print(row)
print('TOTAL'.ljust(30) + ''.join(f"{t[0]:>4d}/{t[1]:<3d}{t[2]/max(1,t[1])/1000:+5.1f}k  " for a in agents for t in [tot[a]]))
