"""hbench.py SEEDS PLANNER T0S OPP [N]: bank of hybrid(v14 until T0, planner after) vs OPP, per T0,
next to pure v14 vs OPP on the same seeds."""
import sys, os, json, traceback
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd(); sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
V14 = f'{SP}/pool/x6/main.py'
def run(a):
    seed, planner, t0, opp = a
    from kaggle_environments import make
    import hybrid
    errs = []
    if t0 >= 720:
        ns = {'__name__': 'x'}; exec(compile(open(V14).read(), V14, 'exec'), ns)
        me = [v for v in ns.values() if callable(v)][-1]
    else:
        h = hybrid.make_agent(V14, planner, t0)
        def me(o, c=None):
            try: return h(o, c)
            except Exception: errs.append(traceback.format_exc().splitlines()[-1]); return {'farmer': ['PASS'], 'hands': [], 'market': []}
    env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed})
    env.run([me, f'{SP}/pool/{opp}/main.py'])
    return seed, t0, env.steps[-1][0]['reward'], env.steps[-1][1]['reward'], len(errs), errs[:1]
if __name__ == '__main__':
    seeds = [int(x) for x in open(sys.argv[1]).read().replace(',', ' ').split()][:int(sys.argv[5]) if len(sys.argv) > 5 else 99]
    t0s = [int(x) for x in sys.argv[3].split(',')] + [720]
    with ProcessPoolExecutor(4) as ex:
        R = list(ex.map(run, [(s, sys.argv[2], t, sys.argv[4]) for t in t0s for s in seeds]))
    by = {}
    for s, t, b, o, ne, e in R: by.setdefault(t, []).append((s, b, o, ne, e))
    base = {s: b for s, b, o, ne, e in by[720]}
    for t in t0s:
        L = by[t]
        print(f"T0={t:3d} (day {t/24:4.1f}) bank {sum(x[1] for x in L)/len(L):8.0f} opp {sum(x[2] for x in L)/len(L):8.0f}  vs v14 {sum(x[1]-base[x[0]] for x in L)/len(L):+7.0f}  errors {sum(x[3] for x in L)} {next((x[4] for x in L if x[4]), '')}")
