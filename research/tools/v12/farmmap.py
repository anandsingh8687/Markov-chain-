import json, sys, os, collections
from kaggle_environments import make
SP = os.getcwd(); ep = int(sys.argv[1]); path = sys.argv[2]; days = [int(x) for x in sys.argv[3].split(',')]
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = [v for v in ns.values() if callable(v)][-1]; OUT = []
AB = {'WHEAT': 'w', 'CARROT': 'c', 'TOMATO': 'T', 'STRAWBERRY': 's', 'MELON': 'm', 'COW': 'C', 'SHEEP': 'S', 'GOOSE': 'G'}
def draw(f):
    rows = []
    for row in f['tiles']:
        r = ''
        for t in row:
            if t == 'LOCKED': r += '#'
            elif t is None: r += '.'
            elif isinstance(t, dict): r += AB.get(t.get('crop') or t.get('animal'), (t.get('kind') or '?')[0].lower())
            else: r += '?'
        rows.append(r)
    return rows
def wrap(o, c=None):
    a = fn(o, c)
    if o['step'] % 24 == 12 and o['step'] // 24 in days:
        A = draw(o['farms'][me]); B = draw(o['farms'][op])
        OUT.append(f"day {o['step']//24}   us{' '*9}opp ({g['names'][op]})")
        for x, y in zip(A, B): OUT.append(f"  {x}    {y}")
    return a
def ghost(o, c=None):
    t = o['step'] + 1; x = g['acts'][op][t] if t < len(g['acts'][op]) else None; return x or {}
ag = [None, None]; ag[me] = wrap; ag[op] = ghost
make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}).run(ag)
open('farmmap.out', 'w').write('\n'.join(OUT))
