import json, sys, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(a):
    ep, path = a
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]; acts = g['acts'][op]
    def ghost(o, c=None):
        t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
    ag = [None, None]; ag[me] = fn; ag[op] = ghost
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
    env.run(ag)
    diff = []
    for d in list(range(0, 30, 3)) + [29]:
        o = env.steps[min(719, d * 24 + 23)][0]['observation']
        diff.append(round(o['farms'][me]['money'] - o['farms'][op]['money']))
    fin = env.steps[-1][me]['reward'] - env.steps[-1][op]['reward']
    return ep, g['names'][op], fin, diff
if __name__ == "__main__":
    eps = [int(x) for x in open(sys.argv[1]).read().split()]
    with ProcessPoolExecutor(4) as ex:
        for ep, n, fin, diff in ex.map(run, [(e, sys.argv[2]) for e in eps]):
            print(ep, n[:12].ljust(12), f"{fin:+7.0f} |", ' '.join(f"{x:+6d}" for x in diff))
