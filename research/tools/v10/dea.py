"""Input-oriented VRS DEA (as in the uploaded paper) over farm-games.
Inputs: wages, land, animals, seeds, bought feed/fertilizer. Output: sale revenue."""
import json, collections, numpy as np
from scipy.optimize import linprog
FIB = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987]
LAND = [1000, 2000, 4000]
def tape_costs(acts):
    wages = 0; land = 0; nl = 0
    per_day = collections.Counter()
    for t, a in enumerate(acts):
        if t == 0 or not a: continue
        for o in a.get('market') or []:
            if o and o[0] == 'HIRE': per_day[(t - 1) // 24] += 1
            if o and o[0] == 'BUY_LAND' and nl < 3: land += LAND[nl]; nl += 1
    for d, n in per_day.items(): wages += sum(FIB[:min(n, len(FIB))])
    return wages, land
dmus = []
M = json.load(open('top_meta.json'))
for l in open('top1.jsonl'):
    d = json.loads(l)
    if d['cand'] != 'ghost' or d['mode'] != 'top_seat': continue
    g = json.load(open(f"ghosts/{d['ep']}.json"))
    for side in (0, 1):
        led = collections.defaultdict(float)
        for k, (n, s) in d['ledger'].items():
            p, op, item = k.split('|')
            if int(p) == side: led[op] += s
        w, land = tape_costs(g['acts'][side])
        grp = 'TOP' if side == d['T'] else 'TOP-opp'
        dmus.append((grp, [w, land, led['BUY_ANIMAL'], led['BUY_SEED'], led['BUY_PRODUCT']], led['SELL']))
# v8 games (our seat and theirs) via ledger replay
from kaggle_environments import make
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from ghostrun import ghost_agent
for ep in open('eps_v8.txt').read().split():
    g = json.load(open(f'ghosts/{ep}.json')); me = g['names'].index('Anand Singh')
    LOG = []; CUR = {}
    opm, ocu = K._process_market, K._commit_unit
    def pm(s, e): CUR['s'] = s; return opm(s, e)
    def cu(op, item, price, farm, private, market, *a, **k):
        ok = ocu(op, item, price, farm, private, market, *a, **k)
        if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, op, price))
        return ok
    K._process_market, K._commit_unit = pm, cu
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
    env.run([ghost_agent(g['acts'][0]), ghost_agent(g['acts'][1])])
    K._process_market, K._commit_unit = opm, ocu
    for side in (0, 1):
        led = collections.defaultdict(float)
        for p, op, price in LOG:
            if p == side: led[op] += price
        w, land = tape_costs(g['acts'][side])
        dmus.append(('v8' if side == me else 'v8-opp', [w, land, led['BUY_ANIMAL'], led['BUY_SEED'], led['BUY_PRODUCT']], led['SELL']))
X = np.array([d[1] for d in dmus], float) + 1.0; Y = np.array([d[2] for d in dmus], float)
n, m = X.shape
theta = []
for a in range(n):
    # variables: theta, lambda_1..n ; minimize theta
    c = np.zeros(n + 1); c[0] = 1
    A_ub = []; b_ub = []
    for i in range(m):                       # sum l x_i - theta x_ia <= 0
        row = np.zeros(n + 1); row[0] = -X[a, i]; row[1:] = X[:, i]; A_ub.append(row); b_ub.append(0)
    row = np.zeros(n + 1); row[1:] = -Y; A_ub.append(row); b_ub.append(-Y[a])   # sum l y >= y_a
    A_eq = [np.r_[0, np.ones(n)]]; b_eq = [1]
    r = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=[(0, None)] * (n + 1), method='highs')
    theta.append(r.x[0] if r.success else float('nan'))
by = collections.defaultdict(list)
for (grp, x, y), t in zip(dmus, theta): by[grp].append((t, x, y))
names = ['wages', 'land', 'animals', 'seeds', 'bought feed/fert']
for grp, L in by.items():
    th = [t for t, _, _ in L]; xs = np.mean([x for _, x, _ in L], 0); ys = np.mean([y for _, _, y in L])
    print(f"{grp:8s} n={len(L):3d} efficiency mean {np.mean(th):.3f} median {np.median(th):.3f} | revenue ${ys:,.0f} | inputs " + ', '.join(f"{nm} ${v:,.0f}" for nm, v in zip(names, xs)))
