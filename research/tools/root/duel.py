import sys, time, json, os, statistics
from kaggle_environments import make

def run(a, b, seed, debug=False):
    env = make("kaggriculture", configuration={"episodeSteps":720, "seed":seed}, debug=debug)
    t0=time.time()
    env.run([a,b])
    dt=time.time()-t0
    last=env.steps[-1]
    r=[s["reward"] for s in last]
    st=[s["status"] for s in last]
    # per-agent cumulative time not exposed; approximate
    return r, st, dt, env

if __name__=="__main__":
    a,b=sys.argv[1],sys.argv[2]
    seeds=[int(x) for x in sys.argv[3].split(",")]
    wins=[0,0,0]
    for s in seeds:
        r,st,dt,env = run(a,b,s)
        res = "TIE" if r[0]==r[1] else ("A" if r[0]>r[1] else "B")
        wins[0 if res=="A" else (1 if res=="B" else 2)] += 1
        print(f"seed={s:>5} A={r[0]:>10} B={r[1]:>10} {st} {res} {dt:.1f}s", flush=True)
    print(f"TOTAL A={wins[0]} B={wins[1]} TIE={wins[2]}")
