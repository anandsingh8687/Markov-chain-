"""routeid.py EPS RESULTS.jsonl: identify both sides' route tape from recorded market orders."""
import json, sys, collections
ns = {'__name__': 'x'}; p = 'pool/c1/main.py'; exec(compile(open(p).read(), p, 'exec'), ns)
routes = ns['_IMPL'].chassis.routes
def sig(acts, lo=144, hi=700):
    s = collections.Counter()
    for t in range(lo, min(hi, len(acts))):
        a = acts[t] or {}
        for o in a.get('market') or []:
            if o and o[0] in ('BUY_SEED', 'BUY_ANIMAL'):
                s[(t // 24, o[1])] += (o[2] if len(o) > 2 else 1)
    return s
TS = {r: sig(tape) for r, tape in routes.items()}
def ident(acts):
    s = sig(acts)
    def sim(r):
        t = TS[r]; ks = set(s) | set(t)
        return sum(min(s[k], t[k]) for k in ks) / max(1, sum(max(s[k], t[k]) for k in ks))
    best = max(TS, key=sim)
    return best, round(sim(best), 2)
res = {}
if len(sys.argv) > 2:
    res = {r['ep']: r['m'] for r in map(json.loads, open(sys.argv[2]))}
sc = json.load(open('ghost_opp_scores.json'))
rows = []
for ep in [int(x) for x in open(sys.argv[1]).read().split()]:
    g = json.load(open(f'ghosts/{ep}.json')); me = g['names'].index('Anand Singh')
    mr, mq = ident(g['acts'][me]); orr, oq = ident(g['acts'][1 - me])
    rows.append((ep, g['names'][1 - me][:14], sc.get(str(ep), [0, None])[1], mr, mq, orr, oq, res.get(ep)))
for r in rows: print(*r)
same = [r for r in rows if r[3] == r[5] and r[6] >= 0.5 and r[7] is not None]
diff = [r for r in rows if r[3] != r[5] and r[6] >= 0.5 and r[7] is not None]
other = [r for r in rows if r[6] < 0.5 and r[7] is not None]
for name, L in (('same route', same), ('different route', diff), ('opp not a tape', other)):
    if L: print(name, len(L), 'won', sum(r[7] > 0 for r in L), 'mean %+.0f' % (sum(r[7] for r in L) / len(L)))
print('opp routes', collections.Counter(r[5] for r in rows if r[6] >= 0.5).most_common(10))
