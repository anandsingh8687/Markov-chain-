"""Replay v10's ladder episodes (ghosts/) with a given agent in our seat."""
import json, sys, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(a):
    ep, path = a
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]
    acts = g['acts'][op]
    def ghost(o, c=None):
        t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
    ag = [None, None]; ag[me] = fn; ag[op] = ghost
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
    env.run(ag)
    r = [env.steps[-1][i]['reward'] for i in (me, op)]
    return {'ep': ep, 'opp': g['names'][op], 'orig': g['r'][me] - g['r'][op], 'm': r[0] - r[1]}
if __name__ == "__main__":
    eps = [int(x) for x in open(sys.argv[1]).read().split()]
    path = sys.argv[2]; out = sys.argv[3]
    with ProcessPoolExecutor(4) as ex, open(out, 'w') as fh:
        res = list(ex.map(run, [(e, path) for e in eps]))
        for r in res: fh.write(json.dumps(r) + "\n")
    w = sum(r['m'] > 0 for r in res); wo = sum(r['orig'] > 0 for r in res)
    print(f"{os.path.basename(os.path.dirname(path))}: won {w}/{len(res)} (orig {wo}), mean {sum(r['m'] for r in res)/len(res):+.0f} (orig {sum(r['orig'] for r in res)/len(res):+.0f}), exact {sum(abs(r['m']-r['orig'])<0.5 for r in res)}")
