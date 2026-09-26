import json, sys, os, collections
SP = os.getcwd()
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from kaggle_environments import make
ep, path, item = int(sys.argv[1]), sys.argv[2], sys.argv[3]
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
LOG = []; CUR = {}
opm, ocu = K._process_market, K._commit_unit
def pm(s, e): CUR['s'] = s; return opm(s, e)
def cu(o, it, price, farm, private, market, *a, **k):
    ok = ocu(o, it, price, farm, private, market, *a, **k)
    if ok: st = CUR['s']; LOG.append((0 if private is st[me].observation.private else 1, o, it, price, st[0].observation.step))
    return ok
K._process_market, K._commit_unit = pm, cu
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = [v for v in ns.values() if callable(v)][-1]; acts = g['acts'][op]
def ghost(o, c=None):
    t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
ag = [None, None]; ag[me] = fn; ag[op] = ghost
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
print('margin', env.steps[-1][me]['reward'] - env.steps[-1][op]['reward'], 'opp', g['names'][op])
S = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0.0]))
for p, o, it, price, step in LOG:
    if it != item: continue
    S[(p, o)][step // 24][0] += 1; S[(p, o)][step // 24][1] += price
for (p, o), days in sorted(S.items()):
    tot = sum(v[0] for v in days.values()); rev = sum(v[1] for v in days.values())
    print(('us  ' if p == 0 else 'them'), o.ljust(11), f"{tot:5d}u ${rev:8.0f} avg {rev/max(1,tot):5.1f} | by day:", ' '.join(f"d{d}:{v[0]}@{v[1]/v[0]:.0f}" for d, v in sorted(days.items())))
