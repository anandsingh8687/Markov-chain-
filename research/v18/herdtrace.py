import json, sys, os, collections
from kaggle_environments import make
SP=os.getcwd(); ep=int(sys.argv[1])
g=json.load(open(f"{SP}/ghosts/{ep}.json")); me=g['names'].index('Anand Singh')
ag=[(lambda acts:(lambda o,c=None:(acts[o['step']+1] if o['step']+1<len(acts) else None) or {}))(g['acts'][s]) for s in (0,1)]
env=make("kaggriculture",configuration={"episodeSteps":720,"seed":g['seed']}); env.run(ag)
for p,lab in ((me,'me'),(1-me,'op')):
    line=[]
    for d in range(10,30):
        o=env.steps[d*24+1][0]['observation']; f=o['farms'][p]
        an=collections.Counter(t.get('animal') for row in f['tiles'] for t in row if isinstance(t,dict) and t.get('animal'))
        unfed=sum(1 for row in f['tiles'] for t in row if isinstance(t,dict) and t.get('animal') and int(t.get('days_unfed',t.get('unfed_days',0)) or 0)>0)
        line.append(f"{d}:{an.get('COW',0)}/{an.get('SHEEP',0)}/{an.get('GOOSE',0)}u{unfed}")
    print(lab,' '.join(line))
# sample an animal tile's keys
o=env.steps[15*24][0]['observation']; f=o['farms'][me]
for row in f['tiles']:
    for t in row:
        if isinstance(t,dict) and t.get('animal'): print(t); break
    else: continue
    break
# my market orders with animals
acts=g['acts'][me]
for t,a in enumerate(acts):
    for o in (a or {}).get('market') or []:
        if o and o[0] in ('SELL','SELL_ANIMAL') and o[1] in ('COW','SHEEP','GOOSE'): print('sell animal',t//24,t%24,o)
