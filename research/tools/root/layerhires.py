import json, sys, collections
from kaggle_environments import make
p='pool/v9_open8/main.py'
seed=int(sys.argv[1])
ns={'__name__':'x'}; exec(compile(open(p).read(),p,'exec'),ns)
fn=[v for v in ns.values() if callable(v)][-1]
extra=collections.Counter(); hourset=collections.Counter(); handsmax=collections.Counter()
def wrap(o,c=None):
    a=fn(o,c)
    t=o['step']; pl=int(o['player'])
    native=ns['_IMPL'].chassis.players.get(pl) or {}
    tape=ns['_IMPL'].chassis.routes[2 if t>=648 else native.get('route',0)]
    th=sum(1 for x in tape[t].get('market') or [] if x and x[0]=='HIRE')
    ah=sum(1 for x in a.get('market') or [] if x and x[0]=='HIRE')
    if ah>th: extra[t//24]+=ah-th; hourset[t%24]+=1
    handsmax[t//24]=max(handsmax[t//24], len(o['farms'][pl]['hands']))
    return a
env=make("kaggriculture",configuration={"episodeSteps":720,"seed":seed})
env.run([wrap,'pool/prv_rain/main.py'])
print(seed, 'extra hires by day', dict(sorted(extra.items())), 'hours', dict(hourset))
print('   max hands by day', [handsmax[d] for d in range(30)], 'money end', env.steps[-1][0]['reward'])
