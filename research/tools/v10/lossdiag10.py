import json, sys, collections, os
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def run(ep):
    import kaggle_environments.envs.kaggriculture.kaggriculture as K
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
    LOG = []; CUR = {}
    opm, ocu = K._process_market, K._commit_unit
    def pm(s, e): CUR['s'] = s; return opm(s, e)
    def cu(o, item, price, farm, private, market, *a, **k):
        ok = ocu(o, item, price, farm, private, market, *a, **k)
        if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, o, item, price))
        return ok
    K._process_market, K._commit_unit = pm, cu
    ns = {'__name__': 'x'}; p = f'{SP}/pool/v10d/main.py'; exec(compile(open(p).read(), p, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]
    def ghost(acts):
        def f(o, c=None):
            t = o['step'] + 1; a = acts[t] if t < len(acts) else None; return a or {}
        return f
    ag = [None, None]; ag[me] = fn; ag[op] = ghost(g['acts'][op])
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
    env.run(ag)
    r = [env.steps[-1][i]['reward'] for i in (me, op)]
    agg = collections.defaultdict(lambda: [0, 0.0, 0, 0.0])
    for p_, o, item, price in LOG:
        if o != 'SELL': continue
        a = agg[item]
        if p_ == me: a[0] += 1; a[1] += price
        else: a[2] += 1; a[3] += price
    return {'ep': ep, 'opp': g['names'][op], 'm': r[0] - r[1], 'orig': g['r'][me] - g['r'][op], 'route': ns.get('_RT_LOG',{}).get('default'), 'shops': ns.get('_RT_LOG',{}).get('shops'), 'agg': dict(agg)}
if __name__ == "__main__":
    eps = [int(x) for x in open(sys.argv[1]).read().split()]
    with ProcessPoolExecutor(2) as ex: res = list(ex.map(run, eps))
    tot_vol = collections.Counter(); tot_price = collections.Counter()
    for r in res:
        worst = []
        for item, (un, us, on, os_) in r['agg'].items():
            up = us / un if un else 0; opp_p = os_ / on if on else 0
            vol = (un - on) * (opp_p or up); pr = un * (up - opp_p) if on else 0
            tot_vol[item] += vol; tot_price[item] += pr
            if abs(us - os_) > 400: worst.append(f"{item[:5]} {us - os_:+.0f} (units {un}-{on}, $/u {up:.0f}-{opp_p:.0f})")
        print(r['ep'], r['opp'][:14].ljust(14), f"{r['m']:+7.0f}", 'route', r['route'], r['shops'], '|', '; '.join(worst))
    print('\nSUM over losses: volume effect', {k: round(v) for k, v in tot_vol.most_common() if abs(v) > 300}, '\n                 price effect ', {k: round(v) for k, v in sorted(tot_price.items(), key=lambda kv: kv[1]) if abs(v) > 300})
