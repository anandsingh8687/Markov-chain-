import json, sys, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(ep):
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
    path = f'{SP}/pool/p1/main.py'
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]; F = {}
    def wrap(o, c=None):
        a = fn(o, c)
        s = o['step']
        if s in (14 * 24 + 1, 18 * 24 + 1, 24 * 24 + 1):
            F[s // 24] = {'shops': list(o['town']['unlocked_shops']), 'p': dict(o['market']['prices'])}
        return a
    def ghost(o, c=None):
        t = o['step'] + 1; x = g['acts'][op][t] if t < len(g['acts'][op]) else None; return x or {}
    ag = [None, None]; ag[me] = wrap; ag[op] = ghost
    make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}).run(ag)
    return ep, F, bool(ns['_V219_STATES'].get(me, {}).get('committed') or any(v.get('committed') for v in ns['_V219_STATES'].values()))
if __name__ == '__main__':
    eps = [int(x) for x in open(sys.argv[1]).read().split()]
    with ProcessPoolExecutor(4) as ex:
        out = {str(ep): {'F': F, 'v219': v} for ep, F, v in ex.map(run, eps)}
    json.dump(out, open(sys.argv[2], 'w'))
