import sys, os
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
tile = tuple(int(v) for v in sys.argv[5].split(',')); steps = [int(v) for v in sys.argv[6].split(',')]
h = hybrid.make_agent(V14, planner, t0); OUT = []
def ag(o, c=None):
    a = h(o, c)
    if o['step'] in steps:
        f = o['farms'][o['player']]; t = f['tiles'][tile[1]][tile[0]]
        P = h.planner
        jl = P.tile_jobs(f, tile, o['step'] // 24, o['step'] % 24)
        OUT.append(f"{o['step']} tile {t} jobs {jl} units {[tuple(x) for x in [f['farmer']] + f['hands']]}")
    return a
env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([ag, f'{SP}/pool/{opp}/main.py'])
open('hjob.out', 'w').write('\n'.join(OUT))
