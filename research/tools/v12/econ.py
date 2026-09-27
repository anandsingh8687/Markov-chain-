"""econ.py EP [AGENT_FOR_SEAT SEAT]: per-player revenue and spend by item for a game (ghost replay)."""
import json, sys, os, collections
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from kaggle_environments import make
ep = int(sys.argv[1]); g = json.load(open(f"ghosts/{ep}.json"))
LOG = []; CUR = {}
opm, ocu = K._process_market, K._commit_unit
def pm(s, e): CUR['s'] = s; return opm(s, e)
def cu(o, item, price, farm, private, market, *a, **k):
    ok = ocu(o, item, price, farm, private, market, *a, **k)
    if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, o, item, price))
    return ok
K._process_market, K._commit_unit = pm, cu
ag = []
HIRES = [collections.Counter(), collections.Counter()]
for side in (0, 1):
    if len(sys.argv) > 3 and int(sys.argv[3]) == side:
        ns = {'__name__': 'x'}; exec(compile(open(sys.argv[2]).read(), sys.argv[2], 'exec'), ns)
        ag.append([v for v in ns.values() if callable(v)][-1])
    else:
        acts = g['acts'][side]
        ag.append((lambda acts: (lambda o, c=None: (acts[o['step'] + 1] if o['step'] + 1 < len(acts) else None) or {}))(acts))
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
env.run(ag)
hands = [[len(env.steps[d * 24 + 12][0]['observation']['farms'][p]['hands']) for d in range(30)] for p in (0, 1)]
for p in (0, 1):
    rev = collections.defaultdict(lambda: [0, 0]); spend = collections.defaultdict(lambda: [0, 0])
    for pp, o, item, price in LOG:
        if pp != p: continue
        d = rev if o == 'SELL' else spend
        d[(o, item)][0] += 1; d[(o, item)][1] += price
    print(f"== {g['names'][p]} bank {env.steps[-1][p]['reward']:.0f}  hands/day {hands[p]}")
    print('  revenue:', ', '.join(f"{i[1][:5]} {v[0]}u ${v[1]/1000:.1f}k" for i, v in sorted(rev.items(), key=lambda kv: -kv[1][1])))
    print('  spend  :', ', '.join(f"{i[0][4:7]}:{i[1][:5]} {v[0]}u ${v[1]/1000:.1f}k" for i, v in sorted(spend.items(), key=lambda kv: -kv[1][1])))
