import json,sys,collections,itertools
recs=[json.loads(l) for l in open(sys.argv[1])]
base={};alt=collections.defaultdict(dict)
for r in recs:
    k=(r['seed'],r['opp'])
    if r['route'] is None: base[k]=r
    else: alt[k][r['route']]=r
lay={k:tuple(v['shops']) for k,v in base.items()}
def table(keys):
    T=collections.defaultdict(lambda: collections.defaultdict(list))
    for k in keys:
        b=base[k]
        for rt,a in alt[k].items():
            if rt==b['default']: continue
            T[lay[k]][rt].append(a['m']-b['m'])
    return T
def policy(T,minn,minmean,minfrac):
    P={}
    for L,d in T.items():
        best=None
        for rt,g in d.items():
            if len(g)<minn: continue
            m=sum(g)/len(g); f=sum(x>0 for x in g)/len(g)
            if m>=minmean and f>=minfrac and (best is None or m>best[1]): best=(rt,m)
        if best: P[L]=best[0]
    return P
seeds=sorted({k[0] for k in base})
for minn,minmean,minfrac in [(3,0,0),(3,300,0.66),(3,500,0.8),(5,300,0.8),(5,500,0.8),(6,500,0.83)]:
    tot=0;n=0;flips=0;losses=0;wins_lost=0
    for s in seeds:  # leave one seed out
        train=[k for k in base if k[0]!=s]; test=[k for k in base if k[0]==s]
        P=policy(table(train),minn,minmean,minfrac)
        for k in test:
            b=base[k];L=lay[k]
            if L in P and P[L] in alt[k]:
                a=alt[k][P[L]]; d=a['m']-b['m']
                if b['m']<0 and a['m']>0: flips+=1
                if b['m']>0 and a['m']<0: wins_lost+=1
            else: d=0
            tot+=d;n+=1
    print(f"minn={minn} minmean={minmean} minfrac={minfrac}: LOSO mean gain {tot/n:+.0f}/game  flips L->W {flips}  W->L {wins_lost}  n={n}")
P=policy(table(list(base)),5,500,0.8)
print("full-data policy (5,500,.8):",P)
P=policy(table(list(base)),3,300,0.66)
print("full-data policy (3,300,.66):",P)
