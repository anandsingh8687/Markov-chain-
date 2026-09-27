import json, sys, os
from kaggle_environments import make
SP = os.getcwd(); ep = int(sys.argv[1]); path = sys.argv[2]; D = int(sys.argv[3])
g = json.load(open(f"{SP}/ghosts/{ep}.json")); me = g['names'].index('Anand Singh'); op = 1 - me
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = ns['agent']
def mine(o, c=None):
    a = fn(o, c); s = o['step']
    if s // 24 == D:
        st = ns['_RANCH_STATE'].get(o['player'], {})
        at = st.get('crew_at')
        f = o['farms'][o['player']]
        if at is not None:
            hs = a.get('hands') or []
            print(s % 24, 'crew_at', at, 'pos', [f['hands'][at + j] if at + j < len(f['hands']) else None for j in range(2)],
                  'cmd', [hs[at + j] if at + j < len(hs) else None for j in range(2)],
                  'inv', [o['private']['inventories'][1 + at + j] if 1 + at + j < len(o['private']['inventories']) else None for j in range(2)],
                  'shedW', o['private']['shed'].get('WHEAT', 0))
        else:
            print(s % 24, 'no crew', 'hands', len(f['hands']), 'mk', a.get('market'))
    return a
acts = g['acts'][op]
def ghost(o, c=None):
    t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
ag = [None, None]; ag[me] = mine; ag[op] = ghost
env = make("kaggriculture", configuration={"episodeSteps": (D + 1) * 24 + 2, "seed": g['seed']}); env.run(ag)
