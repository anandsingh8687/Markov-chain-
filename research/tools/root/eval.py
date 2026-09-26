import sys, json, time
from kaggle_environments import make
from concurrent.futures import ProcessPoolExecutor

def one(args):
    a, b, seed, flip = args
    env = make("kaggriculture", configuration={"episodeSteps":720,"seed":seed}, debug=False)
    x, y = (b, a) if flip else (a, b)
    try:
        env.run([x, y])
    except Exception as e:
        return (seed, flip, None, None, "ERR:"+str(e)[:80])
    last = env.steps[-1]
    r = [s["reward"] for s in last]; st=[s["status"] for s in last]
    ra, rb = (r[1], r[0]) if flip else (r[0], r[1])
    sa, sb = (st[1], st[0]) if flip else (st[0], st[1])
    return (seed, flip, ra, rb, sa+"/"+sb)

if __name__ == "__main__":
    A, B, seeds, nw = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv)>4 else 8
    sl = [int(x) for x in seeds.split(",")]
    jobs = [(A,B,s,f) for s in sl for f in (False,True)]
    w=l=t=0; sa=[]; sb=[]; bad=0
    t0=time.time()
    with ProcessPoolExecutor(max_workers=nw) as ex:
        for seed, flip, ra, rb, st in ex.map(one, jobs):
            if ra is None: bad+=1; print("FAIL", seed, st); continue
            sa.append(ra); sb.append(rb)
            if ra>rb: w+=1
            elif rb>ra: l+=1
            else: t+=1
    n=max(1,w+l+t)
    print(f"{A} vs {B}: W/L/T={w}/{l}/{t} winrate={w/n:.3f} meanA={sum(sa)/max(1,len(sa)):.0f} "
          f"meanB={sum(sb)/max(1,len(sb)):.0f} minA={min(sa) if sa else 0:.0f} errs={bad} {time.time()-t0:.0f}s")
