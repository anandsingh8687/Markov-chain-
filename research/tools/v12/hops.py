"""hops.py SEED PLANNER T0 OPP: op counts, deaths, escapes, hires from T0 on: v14 vs hybrid."""
import sys, os, collections
sys.path.insert(0, '/home/user/Markov-chain-/agents/v17')
from kaggle_environments import make
import hybrid
SP = os.getcwd(); V14 = f'{SP}/pool/x6/main.py'
seed, planner, t0, opp = int(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
def go(agent):
    ops = collections.Counter(); mk = collections.Counter(); hands = []
    def ag(o, c=None):
        a = agent(o, c)
        try:
            if o['step'] >= t0:
                for x in [a.get('farmer') or ['PASS']] + list(a.get('hands') or []):
                    if not x: continue
                    ops[str(x[0]) if x[0] not in ('NORTH', 'SOUTH', 'EAST', 'WEST') else 'MOVE'] += 1
                for m in a.get('market') or []:
                    mk[str(m[0]) + (':' + str(m[1]) if len(m) > 1 else '')] += int(m[2]) if len(m) > 2 else 1
                if o['step'] % 24 == 12: hands.append(len(o['farms'][o['player']]['hands']))
        except Exception as e:
            ops['ERR ' + str(e)[:40]] += 1
        return a
    env = make('kaggriculture', configuration={'episodeSteps': 720, 'seed': seed}); env.run([ag, f'{SP}/pool/{opp}/main.py'])
    deaths = esc = 0; DL = []
    for i in range(t0, len(env.steps) - 1):
        a = env.steps[i][0]['observation']['farms'][0]['tiles']; b = env.steps[i + 1][0]['observation']['farms'][0]['tiles']
        for y in range(10):
            for x in range(10):
                if isinstance(a[y][x], dict) and a[y][x].get('kind') == 'PLANT' and isinstance(b[y][x], dict) and b[y][x].get('kind') == 'WEED': deaths += 1; DL.append((i, (x, y), a[y][x]['crop'], a[y][x]['planted_day'], a[y][x].get('yield_units'), a[y][x].get('consecutive_unwatered'), a[y][x].get('watered_today')))
                if isinstance(a[y][x], dict) and 'animal' in a[y][x] and not (isinstance(b[y][x], dict) and 'animal' in b[y][x]): esc += 1
    DLL.append(DL)
    return env.steps[-1][0]['reward'], ops, mk, hands, deaths, esc
ns = {'__name__': 'x'}; exec(compile(open(V14).read(), V14, 'exec'), ns)
a14 = [v for v in ns.values() if callable(v)][-1]
out = []; DLL = []
for name, ag in (('v14', a14), ('hyb', hybrid.make_agent(V14, planner, t0))):
    r = go(ag)
    out.append(f"{name} bank {r[0]:.0f} hands@noon {r[3]} deaths {r[4]} animals lost {r[5]}")
    out.append('   ops ' + ' '.join(f"{k}={v}" for k, v in r[1].most_common()))
    out.append('   mkt ' + ' '.join(f"{k}={v}" for k, v in r[2].most_common()))
out.extend(map(str, DLL)); open('hops.out', 'w').write('\n'.join(out) + '\n')
