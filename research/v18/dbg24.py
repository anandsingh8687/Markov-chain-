import sys, os, json
from kaggle_environments import make
SP = os.getcwd(); seed = int(sys.argv[1]); A, B = sys.argv[2], sys.argv[3]
env = make("kaggriculture", configuration={"episodeSteps": 60, "seed": seed})
env.run([f'{SP}/pool/{A}/main.py', f'{SP}/pool/{B}/main.py'])
for t in list(range(1, 4)) + list(range(18, 30)):
    o = env.steps[t - 1][0]['observation']; a = env.steps[t][0]['action']
    print(t - 1, 'money', o['farms'][0]['money'], 'hands', len(o['farms'][0]['hands']), 'shed', o['private']['shed'], 'mk', a.get('market'), '| opp mk', env.steps[t][1]['action'].get('market'))
