import json, sys, os, collections
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from kaggle_environments import make
ep = int(sys.argv[1]); side = sys.argv[2]
g = json.load(open(f"ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); P = 1 - me if side == 'op' else me
LOG = []; CUR = {}
opm, ocu = K._process_market, K._commit_unit
def pm(s, e): CUR['s'] = s; return opm(s, e)
def cu(o, item, price, farm, private, market, *a, **k):
    ok = ocu(o, item, price, farm, private, market, *a, **k)
    if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, o, item, price, st[0].observation.step))
    return ok
K._process_market, K._commit_unit = pm, cu
ag = [(lambda A: (lambda o, c=None: (A[o['step'] + 1] if o['step'] + 1 < len(A) else None) or {}))(g['acts'][s]) for s in (0, 1)]
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
by = collections.defaultdict(lambda: {'BUY': [], 'SELL': []})
for p, o, item, price, st in LOG:
    if p == P and item == 'WHEAT':
        by[st]['BUY' if o.startswith('BUY') else 'SELL'].append(price)
tb = ts = nb = ns = 0
for st in sorted(by)[:40]:
    b, s = by[st]['BUY'], by[st]['SELL']
    print(st // 24, st % 24, 'buy', len(b), (min(b), max(b)) if b else '', 'sell', len(s), (min(s), max(s)) if s else '')
for st in by:
    tb += sum(by[st]['BUY']); nb += len(by[st]['BUY']); ts += sum(by[st]['SELL']); ns += len(by[st]['SELL'])
print('total buy', nb, tb, 'avg', tb / max(1, nb), '| sell', ns, ts, 'avg', ts / max(1, ns))
same = sum(1 for st in by if by[st]['BUY'] and by[st]['SELL'])
print('steps with both buy and sell:', same, 'of', len(by))
# the raw orders at a few steps
acts = g['acts'][P]
k = 0
for t, a in enumerate(acts):
    m = (a or {}).get('market') or []
    if any(o and len(o) > 1 and o[1] == 'WHEAT' for o in m) and (t - 1) // 24 >= 15:
        print('step', t - 1, m); k += 1
        if k > 6: break
