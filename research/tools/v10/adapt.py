"""For each (seed, opponent): default v9 route, then alternative routes forced from step 144."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load():
    ns = {'__name__': 'x'}; p = f'{SP}/pool/v9rt/main.py'
    exec(compile(open(p).read(), p, 'exec'), ns)
    return ns
def play(job):
    seed, opp, route = job
    if route is None: os.environ.pop('KG_ROUTE', None)
    else: os.environ['KG_ROUTE'] = str(route)
    ns = load(); fn = [v for v in ns.values() if callable(v)][-1]
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([fn, f'{SP}/pool/{opp}/main.py'])
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    return {'seed': seed, 'opp': opp, 'route': route, 'default': ns['_RT_LOG'].get('default'), 'shops': ns['_RT_LOG'].get('shops'), 'm': r[0] - r[1], 'r': r}
if __name__ == "__main__":
    seeds = [int(x) for x in sys.argv[1].split(',')]; opps = sys.argv[2].split(','); out = sys.argv[3]
    alts = json.loads(sys.argv[4])      # {default_route: [alt routes]}
    with ProcessPoolExecutor(4) as ex:
        base = list(ex.map(play, [(s, o, None) for s in seeds for o in opps]))
    jobs = []
    for b in base:
        for a in alts.get(str(b['default']), alts.get('*', [])):
            if a != b['default']: jobs.append((b['seed'], b['opp'], a))
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(play, jobs))
    with open(out, 'w') as fh:
        for r in base + res: fh.write(json.dumps(r) + "\n")
    print('base games', len(base), 'alt games', len(res))
