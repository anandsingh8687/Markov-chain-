"""For top-team episodes: (a) v8 in the top team's seat vs the recorded opponent,
(b) v8 in the opponent's seat vs the top team's recorded tape. Logs per-item market ledger."""
import json, os, sys, collections
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.abspath(__file__))
META = json.load(open(f"{SP}/top_meta.json"))
def ghost(acts):
    def f(o, c=None):
        t = o["step"] + 1; a = acts[t] if t < len(acts) else None; return a or {}
    return f
def play(job):
    ep, mode, cand = job
    import kaggle_environments.envs.kaggriculture.kaggriculture as K
    LOG = []; CUR = {}
    opm, ocu = K._process_market, K._commit_unit
    def pm(state, env): CUR['s'] = state; return opm(state, env)
    def cu(op, item, price, farm, private, market, *a, **k):
        ok = ocu(op, item, price, farm, private, market, *a, **k)
        if ok:
            st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, op, item, price))
        return ok
    K._process_market, K._commit_unit = pm, cu
    g = json.load(open(f"{SP}/ghosts/{ep}.json"))
    team, sub = META['eps'][str(ep)]
    T = g['names'].index(team); O = 1 - T
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g["seed"]})
    ag = [ghost(g['acts'][0]), ghost(g['acts'][1])]
    seat = T if mode == 'top_seat' else O
    if cand != 'ghost': ag[seat] = f"{SP}/pool/{cand}/main.py"
    env.run(ag)
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    led = collections.defaultdict(lambda: [0, 0.0])
    for p, op, item, price in LOG:
        k = f"{p}|{op}|{item}"; led[k][0] += 1; led[k][1] += price
    return {'ep': ep, 'team': team, 'mode': mode, 'cand': cand, 'T': T, 'seed': g['seed'], 'orig': g['r'], 'r': r,
            'opp': g['names'][O], 'ledger': dict(led)}
if __name__ == "__main__":
    OUT = sys.argv[1]; cands = sys.argv[2].split(','); modes = sys.argv[3].split(',')
    eps = [int(x) for x in open(f"{SP}/eps_top.txt").read().split()]
    jobs = [(e, m, c) for e in eps for m in modes for c in cands]
    with open(OUT, 'w') as fh, ProcessPoolExecutor(max_workers=4) as ex:
        for res in ex.map(play, jobs): fh.write(json.dumps(res) + "\n"); fh.flush()
