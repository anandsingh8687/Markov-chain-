import json, sys, os
from kaggle_environments import make
SP = os.getcwd(); path = sys.argv[1]; out = []
for ep in [int(x) for x in sys.argv[2:]]:
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]; TT = []
    def wrap(o, c=None):
        a = fn(o, c)
        if o['step'] % 24 in (1, 23):
            f = o['farms'][o['player']]
            toms = [(t.get('planted_day'), t.get('yield_units'), t.get('consecutive_unwatered')) for row in f['tiles'] for t in row if isinstance(t, dict) and t.get('crop') == 'TOMATO']
            TT.append((o['step'] // 24, o['step'] % 24, len(toms), sum(x[1] for x in toms), o['private']['shed'].get('TOMATO', 0), o['market']['prices'].get('TOMATO')))
        return a
    def ghost(o, c=None):
        t = o['step'] + 1; x = g['acts'][op][t] if t < len(g['acts'][op]) else None; return x or {}
    ag = [None, None]; ag[me] = wrap; ag[op] = ghost
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
    r = env.steps[-1]
    out.append((ep, r[me]['reward'] - r[op]['reward'], dict(ns.get('_STX_REPORT', ns.get('_TMS_REPORT', {}))), ns['_MDX_REPORT'], [x for x in TT if x[2] or x[4]]))
open('tprobe.out', 'w').write('\n'.join(map(repr, out)))
