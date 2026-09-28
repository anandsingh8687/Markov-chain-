"""gbt.py AGENT OUT: our agent in the non-top seat of top26_sel episodes; top team ghosted."""
import json, sys, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
SEL = {s['ep']: s for s in json.load(open(f'{SP}/top26_sel.json'))}
def run(a):
    ep, path = a
    from kaggle_environments import make
    s = SEL[ep]; g = json.load(open(f"{SP}/ghosts/{ep}.json"))
    top = s['seat']; me = 1 - top
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]
    acts = g['acts'][top]
    def ghost(o, c=None):
        t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
    ag = [None, None]; ag[me] = fn; ag[top] = ghost
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
    env.run(ag)
    r = [env.steps[-1][i]['reward'] for i in (me, top)]
    return {'ep': ep, 'team': s['team'], 'score': s['score'], 'me': r[0], 'top_live': r[1], 'top_rec': g['r'][top], 'opp_rec': g['r'][me]}
if __name__ == "__main__":
    path = sys.argv[1]; out = sys.argv[2]
    eps = [e for e in SEL if os.path.exists(f'{SP}/ghosts/{e}.json')]
    with ProcessPoolExecutor(int(os.environ.get('NP', 4))) as ex, open(out, 'w') as fh:
        for r in ex.map(run, [(e, path) for e in eps]): fh.write(json.dumps(r) + "\n"); fh.flush()
