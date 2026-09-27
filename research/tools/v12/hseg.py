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
        S = h.planner.S.get(o['player'], {})
        owner = [i for i, sg in enumerate(S.get('segs', [])) if tile in sg]
        jl = h.planner.tile_jobs(f, tile, o['step'] // 24, o['step'] % 24)
        own = owner[0] if owner else None
        up = None
        if own is not None:
            pos = ([f['farmer']] + f['hands'])[own] if own < len(f['hands']) + 1 else None
            cmd = (a['farmer'] if own == 0 else a['hands'][own - 1]) if own < len(f['hands']) + 1 else None
            up = (pos, cmd, S['ptr'][own], len(S['segs'][own]), S['segs'][own].index(tile))
        OUT.append(f"{o['step']} tile {t} jobs {jl} owner {own} {up}")
    return a
env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([ag, f'{SP}/pool/{opp}/main.py'])
open('hseg.out', 'w').write('\n'.join(OUT))
