import os, sys, collections
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from kaggle_environments import make
seed=int(sys.argv[1])
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([f'{SP}/pool/v9_open8/main.py', f'{SP}/pool/prv_rain/main.py'])
ev=collections.defaultdict(list)
prev=None
print(env.steps[300][0]['observation']['farms'][0]['tiles'][2][2] if True else '')
for st in env.steps:
    o=st[0]['observation']; step=o['step']; tiles=o['farms'][0]['tiles']
    if prev is not None:
        for y,row in enumerate(tiles):
            for x,t in enumerate(row):
                p=prev[y][x]
                if t==p: continue
                d=step//24; h=step%24
                pk=p.get('crop') if isinstance(p,dict) else p
                tk=t.get('crop') if isinstance(t,dict) else t
                if isinstance(t,dict) and t.get('kind')=='PLANT' and not (isinstance(p,dict) and p.get('kind')=='PLANT'):
                    ev[(x,y)].append(f"d{d}h{h} PLANT {tk}")
                elif isinstance(p,dict) and p.get('kind')=='PLANT' and not (isinstance(t,dict) and t.get('kind')=='PLANT'):
                    ev[(x,y)].append(f"d{d}h{h} END {pk}->{tk if not isinstance(t,dict) else t.get('kind')}")
                elif isinstance(t,dict) and isinstance(p,dict) and t.get('kind')=='PLANT':
                    if p.get('yield_units',0)>t.get('yield_units',0) and h!=0: ev[(x,y)].append(f"d{d}h{h} HARV {p.get('yield_units')}")
                    if t.get('watered_today') and not p.get('watered_today'): ev[(x,y)].append(f"d{d}h{h} W")
    prev=tiles
for k in sorted(ev, key=lambda k:(k[1],k[0]))[:60]:
    e=ev[k]
    crops=collections.Counter(s.split()[-1] for s in e if 'PLANT' in s)
    print(k, dict(crops), ' | '.join(e[:40]))
