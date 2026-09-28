import json, os, sys
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
SEL = json.load(open(sys.argv[1]))
def run(s):
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{s['ep']}.json"))
    ag = [(lambda A: (lambda o, c=None: (A[o['step'] + 1] if o['step'] + 1 < len(A) else None) or {}))(g['acts'][k]) for k in (0, 1)]
    env = make("kaggriculture", configuration={"episodeSteps": 80, "seed": g['seed']}); env.run(ag)
    shops = env.steps[-1][0]['observation']['town']['unlocked_shops']
    A = g['acts'][s['seat']]
    op = tuple(sorted(f"{o[0]}:{o[1] if len(o) > 1 else ''}" for o in (A[2] or {}).get('market') or [] if o))
    return dict(s, first=shops[0] if shops else None, sig=op, seed=g['seed'])
with ProcessPoolExecutor(4) as ex:
    out = list(ex.map(run, SEL))
json.dump(out, open(sys.argv[2], 'w'))
