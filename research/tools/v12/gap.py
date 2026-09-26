"""Units produced/sold and revenue by product: planner (switch at step) vs v11, same seeds, vs prv_rain."""
import json, sys, importlib.util, collections, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(args):
    seed, who, fmpath, switch = args
    import kaggle_environments.envs.kaggriculture.kaggriculture as K
    from kaggle_environments import make
    LOG = []; CUR = {}
    opm, ocu = K._process_market, K._commit_unit
    def pm(st, e): CUR['s'] = st; return opm(st, e)
    def cu(op, item, price, farm, private, market, *a, **k):
        ok = ocu(op, item, price, farm, private, market, *a, **k)
        if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, op, item, price))
        return ok
    K._process_market, K._commit_unit = pm, cu
    ns = {'__name__': 'x'}; exec(compile(open(f'{SP}/pool/v11i/main.py').read(), 'v11', 'exec'), ns); base = ns['agent']
    if who == 'planner':
        spec = importlib.util.spec_from_file_location("fm", fmpath); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm); F = fm.Foreman()
        ag = lambda o, c=None: base(o, c) if o['step'] < switch else F.act(o, c)
    else:
        ag = base
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}); env.run([ag, f'{SP}/pool/prv_rain/main.py'])
    units = collections.Counter(); rev = collections.Counter(); spend = collections.Counter()
    for p, op, item, price in LOG:
        if p: continue
        if op == 'SELL': units[item] += 1; rev[item] += price
        else: spend[op + ':' + item] += price
    f = env.steps[-1][0]['observation']['farms'][0]
    return who, env.steps[-1][0]['reward'], units, rev, spend
if __name__ == "__main__":
    seeds = [int(x) for x in open(sys.argv[1]).read().replace(',', ' ').split()]
    fmpath, switch = sys.argv[2], int(sys.argv[3])
    jobs = [(s, w, fmpath, switch) for s in seeds for w in ('planner', 'v11')]
    agg = {w: [0, collections.Counter(), collections.Counter(), collections.Counter()] for w in ('planner', 'v11')}
    with ProcessPoolExecutor(4) as ex:
        for who, bank, u, r, sp in ex.map(run, jobs):
            a = agg[who]; a[0] += bank / len(seeds); a[1].update(u); a[2].update(r); a[3].update(sp)
    n = len(seeds)
    for w, (bank, u, r, sp) in agg.items():
        print(f"{w:8s} bank {bank:9,.0f} | units/game " + ' '.join(f"{k[:5]}:{v/n:.0f}" for k, v in u.most_common()) )
        print(f"{'':8s} revenue/game " + ' '.join(f"{k[:5]}:{v/n:,.0f}" for k, v in r.most_common()))
        print(f"{'':8s} spend/game " + ' '.join(f"{k}:{v/n:,.0f}" for k, v in sp.most_common(8)))
