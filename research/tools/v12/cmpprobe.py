"""cmpprobe.py EP AGENT_A AGENT_B: daily money / animals / crops for our side under two agents."""
import json, sys, os, collections
from kaggle_environments import make
SP = os.getcwd(); ep = int(sys.argv[1]); res = {}
for path in sys.argv[2:4]:
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]; D = []
    def wrap(o, c=None):
        a = fn(o, c)
        if o['step'] % 24 == 22:
            f = o['farms'][o['player']]; cnt = collections.Counter()
            for row in f['tiles']:
                for t in row:
                    if isinstance(t, dict): cnt[t.get('crop') or t.get('animal') or t.get('kind')] += 1
            D.append((o['step'] // 24, round(f['money']), len(f['hands']), dict(cnt)))
        return a
    def ghost(o, c=None):
        t = o['step'] + 1; x = g['acts'][op][t] if t < len(g['acts'][op]) else None; return x or {}
    ag = [None, None]; ag[me] = wrap; ag[op] = ghost
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
    res[path] = (env.steps[-1][me]['reward'] - env.steps[-1][op]['reward'], D, dict(ns.get('_STX_REPORT', ns.get('_TMS_REPORT', {}))))
with open('cmpprobe.out', 'w') as fh:
    (a, (ma, Da, ra)), (b, (mb, Db, rb)) = res.items()
    fh.write(f"{a} {ma}  {b} {mb} {rb}\n")
    for x, y in zip(Da, Db):
        fh.write(f"d{x[0]:2d} A ${x[1]:6d} h{x[2]:2d} {x[3]}\n    B ${y[1]:6d} h{y[2]:2d} {y[3]}\n")
