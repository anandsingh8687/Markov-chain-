import sys, os, collections
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp, crop = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
for name in ('v14', 'hyb'):
    if name == 'v14':
        ns = {'__name__': 'x'}; exec(compile(open(V14).read(), V14, 'exec'), ns); a0 = [v for v in ns.values() if callable(v)][-1]
    else:
        a0 = hybrid.make_agent(V14, planner, t0)
    env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([a0, f'{SP}/pool/{opp}/main.py'])
    plant_day = collections.Counter(); units = collections.Counter(); fert = collections.Counter(); water_eve = 0
    for i in range(0, len(env.steps) - 1):
        a = env.steps[i][0]['observation']['farms'][0]['tiles']; b = env.steps[i + 1][0]['observation']['farms'][0]['tiles']
        for y in range(10):
            for x in range(10):
                ta, tb = a[y][x], b[y][x]
                if isinstance(tb, dict) and tb.get('crop') == crop and not (isinstance(ta, dict) and ta.get('crop') == crop):
                    plant_day[tb['planted_day']] += 1
                if isinstance(ta, dict) and ta.get('crop') == crop and isinstance(tb, dict) and tb.get('crop') == crop and tb['yield_units'] < ta['yield_units']:
                    units[ta['planted_day']] += ta['yield_units'] - tb['yield_units']
    print(name, 'planted by day', dict(sorted(plant_day.items())), 'harvested units by planting day', dict(sorted(units.items())))
