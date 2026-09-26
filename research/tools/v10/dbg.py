import json, sys, importlib.util, collections
OUT = open("v10/dbg.out", "w")
def pr(*a): print(*a, file=OUT, flush=True)
from kaggle_environments import make
seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1683030426
show = [int(x) for x in sys.argv[2].split(',')] if len(sys.argv) > 2 else [150, 300, 500]
spec = importlib.util.spec_from_file_location("fm", "v10/foreman.py"); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm)
ns = {'__name__': 'x'}; exec(compile(open('pool/v9_open8/main.py').read(), 'v9', 'exec'), ns); v9 = ns['agent']
F = fm.Foreman()
log = collections.Counter(); acts = collections.Counter()
def ag(o, c=None):
    if o['step'] < 144: return v9(o, c)
    a = F.act(o, c)
    for u in [a['farmer']] + a['hands']: acts[u[0]] += 1
    for od in a['market']: log[od[0] + (':' + od[1] if len(od) > 1 else '')] += 1
    if o['step'] in show:
        s = F.st[o['player']]; f = o['farms'][o['player']]
        pr('--- step', o['step'], 'money', f['money'], 'hands', len(f['hands']), 'seeds', {k: v for k, v in o['private']['seeds'].items() if v}, 'shed', {k: v for k, v in o['private']['shed'].items() if v})
        for y in range(10):
            row = ''
            for x in range(10):
                t = f['tiles'][y][x]
                if t == 'LOCKED': row += ' ## '
                elif t is None:
                    r = s['design'].get((x, y)) or s['planned'].get((x, y))
                    row += ' ' + ((r[:2].lower() + '?') if r else '.. ')
                elif 'animal' in t: row += ' ' + t['animal'][:2] + ('f' if t['fed_today'] else '_')
                elif t.get('kind') == 'PLANT': row += ' ' + t['crop'][:2].lower() + str(t['yield_units'])
                else: row += ' ' + t['kind'][:3]
            pr(row)
        pr('orders', a['market'])
    return a
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([ag, 'pool/prv_rain/main.py'])
print('final', [s['reward'] for s in env.steps[-1]])
print('unit actions', dict(acts)); print('orders', dict(log))
