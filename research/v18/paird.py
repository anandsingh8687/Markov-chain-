import json, sys, csv, glob
def ld(f): return {json.loads(l)['ep']: json.loads(l) for l in open(f)}
b = ld('v10/gd_fr16.jsonl')
sc = {}
for n, rows in json.load(open('bands12.json')).items():
    for r in rows: sc[r['ep']] = r['score']
for n, rows in json.load(open('v18live.json')).items():
    for r in rows: sc[r['ep']] = r['score']
for n in sys.argv[1:]:
    a = ld(f'v10/gd_{n}.jsonl'); c = [e for e in a if e in b]
    d = [a[e]['m'] - b[e]['m'] for e in c]
    lo26 = [e for e in c if (sc.get(e) or 0) < 2600]
    print(f"{n:8s} {len(c)} won {sum(a[e]['m']>0 for e in c)} (V16 {sum(b[e]['m']>0 for e in c)})  paired {sum(d)/len(d):+.0f}  better {sum(x>1 for x in d)} worse {sum(x<-1 for x in d)}  | <2600: losses {sum(a[e]['m']<0 for e in lo26)} (V16 {sum(b[e]['m']<0 for e in lo26)}) of {len(lo26)}")
