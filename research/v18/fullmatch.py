import json, sys, os
from kaggle_environments import make
SP = os.getcwd(); ep = int(sys.argv[1]); path = sys.argv[2]
g = json.load(open(f"ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
ghost = (lambda A: (lambda o, c=None: (A[o['step'] + 1] if o['step'] + 1 < len(A) else None) or {}))(g['acts'][me])
ag = [None, None]; ag[me] = ghost; ag[op] = path
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
print(ep, g['names'][op], 'recorded', g['r'], 'replayed', [env.steps[-1][i]['reward'] for i in (0, 1)])
