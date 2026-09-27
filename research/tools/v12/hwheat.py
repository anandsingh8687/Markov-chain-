"""hwheat.py SEED PLANNER T0 OPP: wheat/carrot plantings, harvested units per planting, deaths (v14 vs hybrid)."""
import sys, os, collections
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
    env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([a0, f'{SP}/pool/{opp}/main.py'])
    st = collections.Counter()
    for i in range(t0, len(env.steps) - 1):
        a = env.steps[i][0]['observation']['farms'][0]['tiles']; b = env.steps[i + 1][0]['observation']['farms'][0]['tiles']
        for y in range(10):
            for x in range(10):
                ta, tb = a[y][x], b[y][x]
                if isinstance(ta, dict) and ta.get('kind') == 'PLANT' and ta['crop'] in ('WHEAT', 'CARROT'):
                    c = ta['crop']
                    if tb is None: st[c + ' harvested'] += 1; st[c + ' units'] += ta['yield_units']
                    elif isinstance(tb, dict) and tb.get('kind') == 'WEED': st[c + ' died'] += 1
                if (ta is None or (isinstance(ta, dict) and ta.get('kind') == 'WEED')) and isinstance(tb, dict) and tb.get('kind') == 'PLANT' and tb['crop'] in ('WHEAT', 'CARROT'):
                    st[tb['crop'] + ' planted'] += 1
    print(name, dict(sorted(st.items())))
