import sys, os
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
h = hybrid.make_agent(V14, planner, t0); OUT = []
def ag(o, c=None):
    a = h(o, c)
    if o['step'] >= t0 and o['step'] % 24 == 3 and o['step'] // 24 <= 16:
        S = h.planner.S.get(o['player'], {})
        roles = S.get('role', {})
        from collections import Counter
        OUT.append(f"d{o['step']//24} shops {o['town']['unlocked_shops']} targets {S.get('targets')} roles {dict(Counter(roles.values()))} quads {o['farms'][o['player']]['unlocked_quadrants']} money {o['farms'][o['player']]['money']:.0f} prices W{o['market']['prices']['WOOL']} M{o['market']['prices']['MILK']} E{o['market']['prices']['EGG']}")
    return a
env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([ag, f'{SP}/pool/{opp}/main.py'])
open('htgt.out', 'w').write('\n'.join(OUT))
