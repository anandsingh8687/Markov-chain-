"""hdiag.py SEED PLANNER T0 OPP: sales by item from T0 on, final leftovers, v14 vs hybrid."""
import sys, os, collections
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
def go(agent):
    LOG = []; CUR = {}
    opm, ocu = K._process_market, K._commit_unit
    def pm(s, e): CUR['s'] = s; return opm(s, e)
    def cu(o, item, price, farm, private, market, *a, **k):
        ok = ocu(o, item, price, farm, private, market, *a, **k)
        if ok and private is CUR['s'][0].observation.private and CUR['s'][0].observation.step >= t0: LOG.append((o, item, price))
        return ok
    K._process_market, K._commit_unit = pm, cu
    env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([agent, f'{SP}/pool/{opp}/main.py'])
    K._process_market, K._commit_unit = opm, ocu
    agg = collections.defaultdict(lambda: [0, 0])
    for o, it, pr in LOG:
        a = agg[(o, it)]; a[0] += 1; a[1] += pr
    last = env.steps[-1][0]['observation']
    ob_t0 = env.steps[t0][0]['observation']
    return env.steps[-1][0]['reward'], dict(agg), last['private']['shed'], last['private']['inventories'], ob_t0['farms'][0]['money']
ns = {'__name__': 'x'}; exec(compile(open(V14).read(), V14, 'exec'), ns)
a14 = [v for v in ns.values() if callable(v)][-1]
r1 = go(a14); r2 = go(hybrid.make_agent(V14, planner, t0))
out = []
for name, r in (('v14', r1), ('hyb', r2)):
    out.append(f"{name} bank {r[0]:.0f} money@T0 {r[4]:.0f} shed_end {r[2]} inv_end {[i for i in r[3] if i]}")
    out.append('   ' + ', '.join(f"{k[0][:4]}:{k[1][:5]} {v[0]}u avg {v[1]/v[0]:.0f}" for k, v in sorted(r[1].items(), key=lambda kv: -kv[1][1])))
open(os.environ.get('HD_OUT', 'hdiag.out'), 'w').write('\n'.join(out) + '\n')
