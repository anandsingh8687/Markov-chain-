import json, sys, importlib.util, collections
from concurrent.futures import ProcessPoolExecutor
def run(args):
    seed, mode, params = args
    from kaggle_environments import make
    spec = importlib.util.spec_from_file_location("fm", "v10/foreman.py"); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm); fm.P.update(params)
    ns = {'__name__': 'x'}; exec(compile(open('pool/v9_open8/main.py').read(), 'v9', 'exec'), ns); v9 = ns['agent']
    F = fm.Foreman(); sold = collections.defaultdict(lambda: [0, 0.0]); prev = {}
    def ag(o, c=None):
        # infer our sales from market inventory deltas is ambiguous; instead track our SELL orders vs shed deltas
        a = v9(o, c) if (mode == 'v9' or o['step'] < 144) else F.act(o, c)
        if o['step'] >= 144:
            for od in a.get('market') or []:
                if od and od[0] == 'SELL' and len(od) >= 3:
                    q = min(int(od[2]), int(o['private']['shed'].get(od[1], 0)))
                    if q > 0:
                        sold[od[1]][0] += q; sold[od[1]][1] += q * o['market']['prices'][od[1]]
        return a
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([ag, 'pool/prv_rain/main.py'])
    return {k: v for k, v in sold.items()}, env.steps[-1][0]['reward']
if __name__ == "__main__":
    seeds = [int(x) for x in open('v10/bench_seeds.txt').read().strip().split(',')][:4]
    for mode, params in (('v9', {}), ('fm', json.loads(sys.argv[1]))):
        with ProcessPoolExecutor(4) as ex: res = list(ex.map(run, [(s, mode, params) for s in seeds]))
        tot = collections.defaultdict(lambda: [0, 0.0])
        for r, _ in res:
            for k, (n, v) in r.items(): tot[k][0] += n; tot[k][1] += v
        print(mode, 'bank', round(sum(b for _, b in res) / len(res)), ' '.join(f"{k[:5]}:{n//len(res)}u@{v/max(1,n):.0f}" for k, (n, v) in sorted(tot.items(), key=lambda kv: -kv[1][1])))
