"""idnb.py EP N [cands...]: match notebooks in nb4 against the opponent's recorded actions for N steps."""
import json, sys, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd(); EP = int(sys.argv[1]); N = int(sys.argv[2])
def norm(a):
    a = a or {}
    return json.dumps([a.get('farmer'), a.get('hands') or [], a.get('market') or []])
def test(cand):
    try:
        from kaggle_environments import make
        g = json.load(open(f"{SP}/ghosts/{EP}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
        acts = g['acts']
        ghost = (lambda A: (lambda o, c=None: (A[o['step'] + 1] if o['step'] + 1 < len(A) else None) or {}))(acts[me])
        ag = [None, None]; ag[me] = ghost; ag[op] = f"{SP}/nb4/{cand}/main.py"
        env = make("kaggriculture", configuration={"episodeSteps": N + 2, "seed": g['seed']})
        env.run(ag)
        hit = sum(norm(env.steps[t + 1][op]['action']) == norm(acts[op][t + 1]) for t in range(N) if t + 1 < len(env.steps))
        return cand, hit
    except Exception as e:
        return cand, -1
cands = sys.argv[3:] or sorted(d for d in os.listdir(f"{SP}/nb4") if os.path.exists(f"{SP}/nb4/{d}/main.py"))
with ProcessPoolExecutor(4) as ex:
    res = sorted(ex.map(test, cands), key=lambda x: -x[1])
for c, h in res[:15]: print(h, '/', N, c)
json.dump(res, open(f'v12/idnb_{EP}_{N}.json', 'w'))
