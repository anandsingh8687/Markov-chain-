"""Exact replay of a recorded episode (both tapes) and a per-seat labour/economy audit."""
import json, sys, os, collections
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
MOVES = {'NORTH', 'SOUTH', 'EAST', 'WEST'}
def audit(ep):
    import kaggle_environments.envs.kaggriculture.kaggriculture as K
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{ep}.json"))
    LOG = []; CUR = {}
    opm, ocu = K._process_market, K._commit_unit
    def pm(s, e): CUR['s'] = s; return opm(s, e)
    def cu(o, item, price, farm, private, market, *a, **k):
        ok = ocu(o, item, price, farm, private, market, *a, **k)
        if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, o, item, price))
        return ok
    K._process_market, K._commit_unit = pm, cu
    def tape(i):
        acts = g['acts'][i]
        def f(o, c=None):
            t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
        return f
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run([tape(0), tape(1)])
    out = {}
    for p in (0, 1):
        ops = collections.Counter(); unit_turns = 0; hires = 0
        comp = {}
        for s in range(0, 719):
            o = env.steps[s][0]['observation']; f = o['farms'][p]
            nunits = 1 + len(f['hands'])
            a = g['acts'][p][s + 1] if s + 1 < len(g['acts'][p]) else None
            a = a or {}
            cmds = [a.get('farmer')] + list(a.get('hands') or [])
            for c in cmds[:nunits]:
                unit_turns += 1
                k = 'PASS' if not c else ('MOVE' if c[0] in MOVES else c[0])
                if k == 'HARVEST':
                    x, y = (f['farmer'] if cmds.index(c) == 0 else f['farmer'])  # position not needed
                ops[k] += 1
            hires += sum(1 for m in a.get('market') or [] if m and m[0] == 'HIRE')
            if s % 24 == 0 and s // 24 in (6, 10, 14, 20, 26):
                tiles = [t for row in f['tiles'] for t in row]
                comp[s // 24] = dict(land=len(f['unlocked_quadrants']), money=round(f['money']),
                    animals=dict(collections.Counter(t['animal'] for t in tiles if isinstance(t, dict) and 'animal' in t)),
                    crops=dict(collections.Counter(t['crop'] for t in tiles if isinstance(t, dict) and t.get('kind') == 'PLANT')))
        rev = collections.Counter(); spend = collections.Counter()
        for pp, op, item, price in LOG:
            if pp != p: continue
            if op == 'SELL': rev[item] += price
            else: spend[op + ':' + item] += price
        out[p] = dict(name=g['names'][p], bank=env.steps[-1][p]['reward'], unit_turns=unit_turns, ops=dict(ops), hires=hires,
                      comp=comp, revenue=dict(rev), spend=dict(spend))
    return ep, out
if __name__ == "__main__":
    eps = sys.argv[1].split(',')
    with ProcessPoolExecutor(4) as ex, open(sys.argv[2], 'w') as fh:
        for ep, out in ex.map(audit, eps):
            fh.write(json.dumps({'ep': ep, 'seats': out}) + "\n"); fh.flush()
