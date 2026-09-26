import sys
from kaggle_environments import make
seed = int(sys.argv[1])
for path in ('pool/v12a/main.py', 'pool/v11i/main.py'):
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([ns['agent'], 'pool/prv_rain/main.py'])
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    print(path.split('/')[1], 'margin', r[0] - r[1], r, ns.get('_TS_REPORT'), 'status', [env.steps[-1][i]['status'] for i in (0, 1)])
