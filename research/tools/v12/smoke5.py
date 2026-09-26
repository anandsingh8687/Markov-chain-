import sys
from concurrent.futures import ProcessPoolExecutor
def f(a):
    seed, path, opp = a
    from kaggle_environments import make
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}); env.run([ns['agent'], f'pool/{opp}/main.py'])
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    return seed, path.split('/')[1], opp, r[0] - r[1], ns.get('_TS_REPORT')
seeds = [81963585, 279070016, 359194352, 398542741, 408328273]
jobs = [(s, f'pool/{a}/main.py', o) for s in seeds for o in sys.argv[2].split(',') for a in sys.argv[1].split(',')]
with ProcessPoolExecutor(4) as ex:
    R = list(ex.map(f, jobs))
import collections
M = collections.defaultdict(dict)
for s, a, o, m, rep in R:
    M[(s, o)][a] = m
    if rep: print(s, o[:10], a, m, {k: v for k, v in rep.items() if v})
for k, v in M.items(): print(k[0], k[1][:10], v)
for a in sys.argv[1].split(','):
    L = [v[a] for v in M.values()]; print(a, 'mean', round(sum(L) / len(L)), 'wins', sum(x > 0 for x in L), '/', len(L))
