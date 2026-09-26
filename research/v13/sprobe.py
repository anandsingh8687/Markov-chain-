"""sprobe.py EP AGENT ITEM D0 D1: our shed stock + tape plan + our sells of ITEM per hour."""
import json, sys, os
from kaggle_environments import make
SP = os.getcwd()
ep, path, item, d0, d1 = int(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = [v for v in ns.values() if callable(v)][-1]
ROWS = []
def wrap(o, c=None):
    a = fn(o, c)
    s = o['step']
    if d0 * 24 <= s < d1 * 24:
        try:
            fv = ns['FarmView'](o); shed = fv.shed if hasattr(fv, 'shed') else None
        except Exception as e:
            shed = str(e)
        try:
            ps = ns['projected_shed'](a, ns['FarmView'](o)).get(item, 0)
        except Exception as e:
            ps = str(e)
        native = ns['_IMPL'].chassis.players.get(int(o['player'])) or {}
        tape = ns['_IMPL'].chassis.routes.get(native.get('route'), [])
        plan = [ (o2[2]) for o2 in ((tape[s] or {}).get('market') or []) if len(o2) >= 3 and o2[0]=='SELL' and o2[1]==item] if s < len(tape) else []
        mine = [x for x in (a.get('market') or []) if len(x) > 1 and x[1] == item]
        ROWS.append((s // 24, s % 24, ps, plan, mine, o['market']['prices'].get(item)))
    return a
def ghost(o, c=None):
    t = o['step'] + 1; x = g['acts'][op][t] if t < len(g['acts'][op]) else None; return x or {}
ag = [None, None]; ag[me] = wrap; ag[op] = ghost
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
for r in ROWS:
    if r[3] or r[4] or r[2]: print(f"d{r[0]}h{r[1]:2d} shed {r[2]} plan {r[3]} ours {r[4]} price {r[5]}")
