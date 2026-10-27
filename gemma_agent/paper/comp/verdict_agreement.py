import csv, json, sys
from collections import Counter
rows = list(csv.DictReader(open(sys.argv[1])))  # toasterson built tasks (sound or unsound after build)
ours={}
for l in open(sys.argv[2]):
    o=json.loads(l); ours[(o['repo'].lower(), o['instance_id'].rsplit('-',1)[1])]='sound'
for l in open(sys.argv[3]):
    o=json.loads(l)
    if o['stage']=='check': ours[(o['repo'].lower(), o['instance_id'].rsplit('-',1)[-1])]='unsound'
t=Counter()
for r in rows:
    k=(r['repo'].lower(), r['instance_id'].rsplit('_',1)[1])
    if k in ours:
        t[(ours[k], 'sound' if r['sound']=='1' else 'unsound')]+=1
print(t, sum(t.values()))
