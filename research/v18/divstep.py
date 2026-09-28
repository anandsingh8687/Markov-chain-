import sys, os, json
from kaggle_environments import make
SP = os.getcwd(); seed = int(sys.argv[1]); A = sys.argv[2]; B1, B2 = sys.argv[3], sys.argv[4]
runs = []
for B in (B1, B2):
    env = make("kaggriculture", configuration={"episodeSteps": 120, "seed": seed})
    env.run([f'{SP}/pool/{A}/main.py', f'{SP}/pool/{B}/main.py'])
    runs.append(env)
for t in range(1, 120):
    a1 = runs[0].steps[t][0]['action']; a2 = runs[1].steps[t][0]['action']
    if json.dumps(a1, sort_keys=True) != json.dumps(a2, sort_keys=True):
        print('first divergence at step', t - 1)
        for k, env in zip((B1, B2), runs):
            o = env.steps[t - 1][0]['observation']
            print(' vs', k, 'our action', json.dumps(env.steps[t][0]['action'])[:300])
            print('    opp action', json.dumps(env.steps[t][1]['action'])[:300])
            print('    our money', o['farms'][0]['money'], 'prices', {x: o['market']['prices'][x] for x in ('WHEAT', 'MELON', 'STRAWBERRY', 'FERTILIZER')})
        for tt in range(max(1, t - 3), t):
            print(' step', tt - 1, 'opp actions:', B1, json.dumps(runs[0].steps[tt][1]['action'].get('market'))[:200], '|', B2, json.dumps(runs[1].steps[tt][1]['action'].get('market'))[:200])
        break
