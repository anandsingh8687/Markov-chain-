import sys, os, collections
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
res = {}
for name in ('v14', 'hyb'):
    if name == 'v14':
        ns = {'__name__': 'x'}; exec(compile(open(V14).read(), V14, 'exec'), ns); ag0 = [v for v in ns.values() if callable(v)][-1]
    else:
        ag0 = hybrid.make_agent(V14, planner, t0)
    C = collections.Counter()
    def ag(o, c=None, ag0=ag0, C=C):
        a = ag0(o, c)
        if o['step'] >= t0 and o['step'] % 24 == 12:
            f = o['farms'][o['player']]
            for row in f['tiles']:
                for t in row:
                    k = 'LOCK' if t == 'LOCKED' else 'EMPTY' if t is None else (t.get('crop') or t.get('animal') or t.get('kind'))
                    C[(o['step'] // 24, k)] += 1
        return a
    env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([ag, f'{SP}/pool/{opp}/main.py'])
    res[name] = C
for d in range(t0 // 24, 30):
    print(d, 'v14', {k[1]: v for k, v in res['v14'].items() if k[0] == d}, '\n   hyb', {k[1]: v for k, v in res['hyb'].items() if k[0] == d})
