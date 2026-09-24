"""Run hybrid(v9->Foreman) vs opponent on seeds; report bank and revenue by product."""
import json, sys, importlib.util, collections, os
from concurrent.futures import ProcessPoolExecutor
def run(args):
    seed, opp, switch, params = args
    import kaggle_environments.envs.kaggriculture.kaggriculture as K
    from kaggle_environments import make
    spec = importlib.util.spec_from_file_location("fm", "agents/foreman/foreman.py"); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm)
    fm.P.update(params)
    ns = {'__name__': 'x'}; exec(compile(open('main.py').read(), 'v9', 'exec'), ns); v9 = ns['agent']
    F = fm.Foreman()
    LOG = []; CUR = {}
    opm, ocu = K._process_market, K._commit_unit
    def pm(st, e): CUR['s'] = st; return opm(st, e)
    def cu(op, item, price, farm, private, market, *a, **k):
        ok = ocu(op, item, price, farm, private, market, *a, **k)
        if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, op, item, price))
        return ok
    K._process_market, K._commit_unit = pm, cu
    def ag(o, c=None):
        return v9(o, c) if o['step'] < switch else F.act(o, c)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([ag, opp])
    rev = collections.defaultdict(float)
    for p, op, item, price in LOG:
        if p == 0: rev[('+' if op == 'SELL' else '-') + item] += price
    return {'seed': seed, 'r': [env.steps[-1][i]['reward'] for i in (0, 1)], 'rev': dict(rev)}
if __name__ == "__main__":
    seeds = [int(x) for x in sys.argv[1].split(',')]; opp = sys.argv[2]; switch = int(sys.argv[3])
    params = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(run, [(s, opp, switch, params) for s in seeds]))
    tot = collections.defaultdict(float)
    for r in res:
        for k, v in r['rev'].items(): tot[k] += v / len(res)
    print('bank', round(sum(r['r'][0] for r in res) / len(res)), 'opp', round(sum(r['r'][1] for r in res) / len(res)), 'W', sum(r['r'][0] > r['r'][1] for r in res), '/', len(res))
    print(' '.join(f"{k}:{v:.0f}" for k, v in sorted(tot.items(), key=lambda kv: -abs(kv[1]))))
