import json, sys, os, time
from kaggle_environments import make
SP = os.getcwd(); path = sys.argv[1]; out = []
for ep in [int(x) for x in sys.argv[2:]]:
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]; T = []
    def wrap(o, c=None):
        t = time.time(); a = fn(o, c); T.append(time.time() - t); return a
    def ghost(o, c=None):
        t = o['step'] + 1; x = g['acts'][op][t] if t < len(g['acts'][op]) else None; return x or {}
    ag = [None, None]; ag[me] = wrap; ag[op] = ghost
    make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}).run(ag)
    out.append((ep, ns['_STX_REPORT'], ns['_MDX_REPORT'], round(1000*sum(T)/len(T), 2), round(1000*max(T), 1)))
open('errchk.out', 'w').write('\n'.join(map(repr, out)))
