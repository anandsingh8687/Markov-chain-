"""Like gb.py, but also record our/opp quadrant counts per day and money at 6.3."""
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
    q = [len(env.steps[d * 24][0]['observation']['farms'][me]['unlocked_quadrants']) for d in range(5, 16)]
    oq = [len(env.steps[d * 24][0]['observation']['farms'][op]['unlocked_quadrants']) for d in range(5, 16)]
    m63 = env.steps[6 * 24 + 3][0]['observation']['farms'][me]['money']
    return {'ep': ep, 'opp': g['names'][op], 'orig': g['r'][me] - g['r'][op], 'm': r[0] - r[1], 'r': r, 'q': q, 'oq': oq, 'm63': m63}
if __name__ == "__main__":
    eps = [int(x) for x in open(sys.argv[1]).read().split()]
    path = sys.argv[2]; out = sys.argv[3]
    with ProcessPoolExecutor(int(os.environ.get('NP', 4))) as ex, open(out, 'w') as fh:
        for r in ex.map(run, [(e, path) for e in eps]):
            fh.write(json.dumps(r) + "\n"); fh.flush()
