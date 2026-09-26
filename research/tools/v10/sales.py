import json, sys, collections, os
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def run(job):
    seed, a, b = job
    import kaggle_environments.envs.kaggriculture.kaggriculture as K
    from kaggle_environments import make
    LOG = []; CUR = {}
    opm, ocu = K._process_market, K._commit_unit
    def pm(s, e): CUR['s'] = s; return opm(s, e)
    def cu(o, item, price, farm, private, market, *x, **k):
        ok = ocu(o, item, price, farm, private, market, *x, **k)
        if ok: st = CUR['s']; LOG.append((0 if private is st[0].observation.private else 1, o, item, price, st[0].observation.step))
        return ok
    K._process_market, K._commit_unit = pm, cu
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([f'{SP}/pool/{a}/main.py', f'{SP}/pool/{b}/main.py'])
    return seed, [env.steps[-1][i]['reward'] for i in (0, 1)], LOG
if __name__ == "__main__":
    seeds=[int(x) for x in sys.argv[1].split(',')]
    W=[(0,10),(10,15),(15,20),(20,25),(25,30)]
    tot=collections.defaultdict(lambda:[0,0.0])
    with ProcessPoolExecutor(4) as ex:
        for seed,r,LOG in ex.map(run,[(s,sys.argv[2],sys.argv[3]) for s in seeds]):
            print(seed,r)
            agg=collections.defaultdict(lambda:[0,0.0])
            for p,o,item,price,step in LOG:
                if p!=0 or o!='SELL': continue
                d=step//24; w=[i for i,(lo,hi) in enumerate(W) if lo<=d<hi][0]
                agg[(item,w)][0]+=1; agg[(item,w)][1]+=price
                tot[(item,w)][0]+=1; tot[(item,w)][1]+=price
            for item in sorted({k[0] for k in agg}):
                print(f"   {item[:6]:6s} "+" ".join(f"d{W[w][0]:2d}+: {agg[(item,w)][0]:4d}u ${agg[(item,w)][1]/max(1,agg[(item,w)][0]):4.0f}" for w in range(len(W))))
    print("TOTAL")
    for item in sorted({k[0] for k in tot}):
        print(f"   {item[:6]:6s} "+" ".join(f"d{W[w][0]:2d}+: {tot[(item,w)][0]:4d}u ${tot[(item,w)][1]/max(1,tot[(item,w)][0]):4.0f}" for w in range(len(W))))
