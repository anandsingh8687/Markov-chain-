import json, sys, os, collections
from kaggle_environments import make
SP = os.getcwd(); ep = int(sys.argv[1]); path = sys.argv[2]
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = ns['agent']; LOG = []
def mine(o, c=None):
    a = fn(o, c)
    s = o['step']
    if s % 24 == int(os.environ.get("HR", 12)) and s // 24 >= 9:
        f = o['farms'][o['player']]
        se = [f['tiles'][y][x] for y in range(5, 10) for x in range(5, 10)]
        LOG.append((s // 24, len(f['unlocked_quadrants']), len(f['hands']), len(a.get('hands') or []),
                    sum(1 for t in se if isinstance(t, dict) and t.get('animal') == 'SHEEP'),
                    sum(1 for t in se if isinstance(t, dict) and t.get('kind') == 'PASTURE'), round(f['money']), o['private']['shed'].get('WHEAT',0), sum(1 for t in se if isinstance(t, dict) and t.get('animal') and t.get('fed_today')), sum(1 for t in se if isinstance(t, dict) and t.get('cared_today'))))
    return a
acts = g['acts'][op]
def ghost(o, c=None):
    t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
ag = [None, None]; ag[me] = mine; ag[op] = ghost
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
r = [env.steps[-1][i]['reward'] for i in (me, op)]
print(ep, 'final', r, 'margin', round(r[0] - r[1]), 'orig', round(g['r'][me] - g['r'][op]), ns['_RANCH_REPORT'])
for l in LOG: print('  d%d q%d hands%d cmds%d SEsheep%d pastures%d money%d shedwheat%d fed%d cared%d' % l)
