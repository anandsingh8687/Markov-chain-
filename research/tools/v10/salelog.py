import json, sys, os, collections
SP = os.getcwd()
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from kaggle_environments import make
ep, path, items = int(sys.argv[1]), sys.argv[2], sys.argv[3].split(',')
d0 = int(sys.argv[4]) if len(sys.argv) > 4 else 15
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
LOG = []; CUR = {}
opm, ocu = K._process_market, K._commit_unit
def pm(s, e): CUR['s'] = s; return opm(s, e)
def cu(o, item, price, farm, private, market, *a, **k):
    ok = ocu(o, item, price, farm, private, market, *a, **k)
    if ok: st = CUR['s']; LOG.append((0 if private is st[me].observation.private else 1, o, item, price, st[0].observation.step))
    return ok
K._process_market, K._commit_unit = pm, cu
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = [v for v in ns.values() if callable(v)][-1]; acts = g['acts'][op]
def ghost(o, c=None):
    t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
ag = [None, None]; ag[me] = fn; ag[op] = ghost
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
print('margin', env.steps[-1][me]['reward'] - env.steps[-1][op]['reward'])
by = collections.defaultdict(lambda: [[], []])
for p, o, item, price, step in LOG:
    if o == 'SELL' and item in items and step // 24 >= d0: by[(step, item)][p].append(price)
tot = collections.defaultdict(lambda: [0, 0, 0, 0])
for (step, item), (us, them) in sorted(by.items()):
    t = tot[item]; t[0] += len(us); t[1] += sum(us); t[2] += len(them); t[3] += sum(them)
    print(f"d{step//24:2d}h{step%24:2d} {item[:5]:5s} us {len(us):3d}u {('$%d-%d' % (max(us), min(us))) if us else '':10s} them {len(them):3d}u {('$%d-%d' % (max(them), min(them))) if them else ''}")
for item, t in tot.items(): print(item, f"us {t[0]}u ${t[1]:.0f} (avg {t[1]/max(1,t[0]):.1f})  them {t[2]}u ${t[3]:.0f} (avg {t[3]/max(1,t[2]):.1f})")
