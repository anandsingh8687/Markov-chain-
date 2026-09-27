import sys, os
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
for name in ('v14', 'hyb'):
    if name == 'v14':
        ns = {'__name__': 'x'}; exec(compile(open(V14).read(), V14, 'exec'), ns); a0 = [v for v in ns.values() if callable(v)][-1]
    else:
        a0 = hybrid.make_agent(V14, planner, t0)
    R = []
    def ag(o, c=None, a0=a0, R=R):
        a = a0(o, c)
        if o['step'] >= t0 and o['step'] % 24 in (0, 23):
            sh = o['private']['shed']; iv = o['private']['inventories']
            R.append(f"d{o['step']//24}h{o['step']%24} shed {sum(sh.values())} {dict((k, v) for k, v in sh.items() if v)} hands {sum(sum(i.values()) for i in iv if i)}")
        return a
    env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([ag, f'{SP}/pool/{opp}/main.py'])
    print(name); print('\n'.join(R))
