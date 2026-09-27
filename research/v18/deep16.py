"""deep16.py EPS OUT: exact ghost-vs-ghost replay; per-player economy profile."""
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
    ag = [(lambda acts: (lambda o, c=None: (acts[o['step'] + 1] if o['step'] + 1 < len(acts) else None) or {}))(g['acts'][s]) for s in (0, 1)]
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
    env.run(ag)
    out = {'ep': ep, 'me': me, 'r': [env.steps[-1][i]['reward'] for i in (0, 1)], 'p': []}
    for p in (0, 1):
        rev = collections.Counter(); units = collections.Counter(); spend = collections.Counter()
        for pp, o, item, price, st in LOG:
            if pp != p: continue
            if o == 'SELL': rev[item] += price; units[item] += 1
            else: spend[(o, item)] += price
        prof = {'rev': dict(rev), 'units': dict(units), 'spend': {f'{a}:{b}': v for (a, b), v in spend.items()}}
        for d in (6, 8, 10, 12, 15, 20, 25):
            ob = env.steps[d * 24 + 12][0]['observation']; f = ob['farms'][p]
            tiles = [t for row in f['tiles'] for t in row if isinstance(t, dict)]
            crops = collections.Counter(t.get('crop') for t in tiles if t.get('kind') == 'PLANT')
            an = collections.Counter(t.get('animal') for t in tiles if t.get('animal'))
            prof[f'd{d}'] = {'q': len(f['unlocked_quadrants']), 'hands': len(f['hands']), 'money': f['money'],
                             'crops': dict(crops), 'animals': dict(an), 'empty': sum(1 for row in f['tiles'] for t in row if t is None)}
        out['p'].append(prof)
    out['shops'] = list(env.steps[-1][0]['observation']['town']['unlocked_shops'])
    return out
if __name__ == "__main__":
    eps = [int(x) for x in open(sys.argv[1]).read().split()]
    with ProcessPoolExecutor(4) as ex, open(sys.argv[2], 'w') as fh:
        for r in ex.map(run, eps): fh.write(json.dumps(r) + "\n"); fh.flush()
