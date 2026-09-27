"""hday.py SEED PLANNER T0 OPP: per-turn unit commands on day 29 (hybrid), to debug labour."""
import sys, os, collections
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
h = hybrid.make_agent(V14, planner, t0); OUT = []
def ag(o, c=None):
    a = h(o, c)
    if o['step'] >= t0:
        f = o['farms'][o['player']]
        ops = collections.Counter(x[0] for x in [a['farmer']] + a['hands'])
        crops = sum(1 for row in f['tiles'] for t in row if isinstance(t, dict) and t.get('kind') == 'PLANT' and int(t.get('yield_units', 0)) > 0)
        OUT.append(f"{o['step']} h{o['step']%24} hands {len(f['hands'])} plants_with_yield {crops} ops {dict(ops)} mkt {a['market'][:4]}")
    return a
env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([ag, f'{SP}/pool/{opp}/main.py'])
open('hday.out', 'w').write('\n'.join(OUT))
