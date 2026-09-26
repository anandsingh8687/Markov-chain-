import json, sys, os
from kaggle_environments import make
SP = os.getcwd(); ep, path = int(sys.argv[1]), sys.argv[2]
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = [v for v in ns.values() if callable(v)][-1]
def wrap(o, c=None):
    a = fn(o, c); s = o['step']
    if s in (24*26, 24*26+1, 24*24+5):
        fl = ns['_FX_STATE'][o['player']]['flow']
        print(s, file=open("mdbg.out","a")) if 0 else open("mdbg.out","a").write(repr((s, {k: v for k, v in fl.items() if k[1] == 'STRAWBERRY' and k[0] >= 18*24}, ns['_MDX_REPORT'], sorted(x for x in ns['_MDX_OWN'].get(o['player'], ()) if x[1]=="STRAWBERRY" and x[0]>=18*24)))+"\n")
    return a
def ghost(o, c=None):
    t = o['step'] + 1; x = g['acts'][op][t] if t < len(g['acts'][op]) else None; return x or {}
ag = [None, None]; ag[me] = wrap; ag[op] = ghost
make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}).run(ag)
