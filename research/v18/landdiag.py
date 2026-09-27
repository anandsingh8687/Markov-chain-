"""Replay one ghost episode with an agent; log money, quadrants and market orders for days 5-13."""
import json, sys, os
SP = os.getcwd()
ep, path, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
from kaggle_environments import make
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = ns['agent']
acts = g['acts'][op]
log = open(out, 'w')
def ghost(o, c=None):
    t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
def mine(o, c=None):
    a = fn(o, c)
    s = int(o['step'])
    if 5 * 24 <= s < 14 * 24:
        f = o['farms'][o['player']]; of = o['farms'][1 - o['player']]
        log.write(json.dumps({'d': s // 24, 'h': s % 24, 'money': f['money'], 'q': f['unlocked_quadrants'],
                              'oq': of['unlocked_quadrants'], 'omoney': of['money'], 'hands': len(f['hands']),
                              'mk': a.get('market')}) + "\n")
    return a
ag = [None, None]; ag[me] = mine; ag[op] = ghost
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
env.run(ag)
r = [env.steps[-1][i]['reward'] for i in (me, op)]
log.write(json.dumps({'final': r}) + "\n")
