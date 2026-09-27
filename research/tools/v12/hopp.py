"""hopp.py SEED PLANNER T0 OPP: revenue by item for BOTH players, mirror (v14 vs OPP) vs hybrid vs OPP."""
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
        if ok and o == 'SELL': LOG.append((0 if private is CUR['s'][0].observation.private else 1, item, price))
        return ok
    K._process_market, K._commit_unit = pm, cu
    env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([agent, f'{SP}/pool/{opp}/main.py'])
    K._process_market, K._commit_unit = opm, ocu
    R = [collections.defaultdict(lambda: [0, 0]) for _ in range(2)]
    for p, it, pr in LOG: R[p][it][0] += 1; R[p][it][1] += pr
    return [env.steps[-1][i]['reward'] for i in (0, 1)], R
ns = {'__name__': 'x'}; exec(compile(open(V14).read(), V14, 'exec'), ns)
m = go([v for v in ns.values() if callable(v)][-1]); h = go(hybrid.make_agent(V14, planner, t0))
print('mirror banks', m[0], ' hybrid banks', h[0])
items = sorted(set(m[1][0]) | set(m[1][1]) | set(h[1][0]) | set(h[1][1]))
for it in items:
    a, b, c, d = m[1][0][it], m[1][1][it], h[1][0][it], h[1][1][it]
    print(f"{it:10s} mirror us {a[0]:4d}u ${a[1]:6d} opp {b[0]:4d}u ${b[1]:6d} | hybrid us {c[0]:4d}u ${c[1]:6d} opp {d[0]:4d}u ${d[1]:6d}  opp delta ${d[1]-b[1]:+6d}")
