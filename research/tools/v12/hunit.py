import sys, os
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp, day = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5])
h = hybrid.make_agent(V14, planner, t0); OUT = []
def ag(o, c=None):
    a = h(o, c)
    if o['step'] // 24 == day:
        f = o['farms'][o['player']]; pos = [f['farmer']] + f['hands']
        tg = h.planner.S.get(o['player'], {}).get('tgt', {})
        OUT.append(f"h{o['step']%24:2d} " + ' | '.join(f"{i}:{tuple(p)}->{(a['farmer'] if i == 0 else a['hands'][i-1])[0][:5]} t{tg.get(i)}" for i, p in enumerate(pos[:5])))
    return a
env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([ag, f'{SP}/pool/{opp}/main.py'])
open('hunit.out', 'w').write('\n'.join(OUT))
