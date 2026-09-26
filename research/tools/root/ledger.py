"""Per-player market ledger for a ghost game: revenue/cost by (op,item) and by day."""
import json, sys, collections
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from ghostrun import ghost_agent
LOG = []; CUR = {}
_orig_pm, _orig_cu = K._process_market, K._commit_unit
def pm(state, env):
    CUR['state'] = state; CUR['step'] = state[0].observation.step if 'step' in state[0].observation else None
    return _orig_pm(state, env)
def cu(op, item, price, farm, private, market, *a, **k):
    ok = _orig_cu(op, item, price, farm, private, market, *a, **k)
    if ok:
        st = CUR['state']; p = 0 if private is st[0].observation.private else 1
        LOG.append((p, CUR.get('n', 0), op, item, price))
    return ok
K._process_market, K._commit_unit = pm, cu
def run(ep, cand):
    g = json.load(open(f"ghosts/{ep}.json")); me = g["names"].index("Anand Singh"); op = 1 - me
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g["seed"]})
    ag = [None, None]; ag[op] = ghost_agent(g["acts"][op])
    ag[me] = ghost_agent(g["acts"][me]) if cand == "ghost" else f"pool/{cand}/main.py"
    n = [0]
    def wrap(a):
        def f(o, c=None):
            if o['player'] == 0: CUR['n'] = o['step']
            return a(o, c) if callable(a) else a
        return f
    LOG.clear()
    env.run(ag)
    return g, me, op, env
if __name__ == "__main__":
    ep = int(sys.argv[1]); cand = sys.argv[2] if len(sys.argv) > 2 else "ghost"
    g, me, op, env = run(ep, cand)
    T = collections.defaultdict(lambda: [0, 0.0])
    for p, n, o, item, price in LOG:
        key = ('US' if p == me else 'OPP', o, item)
        T[key][0] += 1; T[key][1] += price
    print(ep, g['names'][op], 'final', [env.steps[-1][me]['reward'], env.steps[-1][op]['reward']])
    for key in sorted(T, key=lambda k: (k[1], k[2], k[0])):
        print(f"{key[0]:3s} {key[1]:11s} {key[2]:10s} n={T[key][0]:5d} total={T[key][1]:9.0f}")
    f = env.steps[-1][0]['observation']['farms'] if 'farms' in env.steps[-1][0]['observation'] else None
