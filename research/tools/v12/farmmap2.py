"""farmmap2.py EP DAYS NAME: replay a recorded game (both sides ghosts) and draw NAME's farm."""
import json, sys, os
from kaggle_environments import make
ep = int(sys.argv[1]); days = [int(x) for x in sys.argv[2].split(',')]; who = sys.argv[3]
g = json.load(open(f"ghosts/{ep}.json")); p = [i for i, n in enumerate(g['names']) if n.startswith(who)][0]
AB = {'WHEAT': 'w', 'CARROT': 'c', 'TOMATO': 'T', 'STRAWBERRY': 's', 'MELON': 'm', 'COW': 'C', 'SHEEP': 'S', 'GOOSE': 'G'}
OUT = []
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
def mk(side):
    def f(o, c=None):
        t = o['step'] + 1; x = g['acts'][side][t] if t < len(g['acts'][side]) else None
        if side == p and o['step'] % 24 == 12 and o['step'] // 24 in days:
            fm = o['farms'][p]
            OUT.append(f"day {o['step']//24} ${fm['money']:.0f} hands {len(fm['hands'])} quads {fm['unlocked_quadrants']}")
            OUT.extend('  ' + r for r in draw(fm))
        return x or {}
    return f
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run([mk(0), mk(1)])
OUT.append(f"final {[env.steps[-1][i]['reward'] for i in (0,1)]} recorded {g['r']}")
open('farmmap2.out', 'w').write('\n'.join(OUT))
