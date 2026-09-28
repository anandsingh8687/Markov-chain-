"""endgame.py EPS OUT: exact ghost-vs-ghost replay; per-player money, net worth, units sold per day (days 18-29)."""
import json, sys, os, collections
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(ep):
    import kaggle_environments.envs.kaggriculture.kaggriculture as K
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh')
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
    out = {'ep': ep, 'me': me, 'days': {}}
    for d in list(range(12, 30)) + [29.99]:
        st = min(int(d * 24), 719) if d != 29.99 else 719
        o0 = env.steps[st][0]['observation']; pr = o0['market']['prices']
        row = []
        for p in (0, 1):
            f = o0['farms'][p]; priv = env.steps[st][p]['observation']['private']
            inv = collections.Counter(priv['shed'])
            for i in priv.get('inventories') or []: inv.update(i)
            val = sum(n * pr.get(k, 0) for k, n in inv.items() if k in pr)
            ytiles = sum(t.get('yield_units', 0) for rr in f['tiles'] for t in rr if isinstance(t, dict))
            row.append({'money': f['money'], 'stock': val, 'held_on_tiles': ytiles})
        out['days'][str(d)] = row
    sold = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    for p, o, item, price, st in LOG:
        if o == 'SELL': sold[st // 24][p][item] += 1
    out['sold'] = {str(d): [dict(sold[d][0]), dict(sold[d][1])] for d in sold}
    return out
if __name__ == "__main__":
    eps = [int(x) for x in open(sys.argv[1]).read().split()]
    with ProcessPoolExecutor(4) as ex, open(sys.argv[2], 'w') as fh:
        for r in ex.map(run, eps): fh.write(json.dumps(r) + "\n")
