"""Play agents against ghost opponents (recorded ladder actions), on the ghost's seed and seat.
usage: ghostrun.py OUT CAND[,CAND..] EP[,EP..]|all   (CAND may be 'ghost' = replay our own recorded side)"""
import json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.abspath(__file__))
def ghost_agent(acts):
    def agent(obs, cfg=None):
        t = obs.get("step", 0) if isinstance(obs, dict) else obs.step
        a = acts[t + 1] if t + 1 < len(acts) else {}
        return a if a else {}
    return agent
def play(job):
    cand, ep = job
    base, _, forced = cand.partition("@")
    if forced: os.environ["KG_ROUTE"] = forced
    else: os.environ.pop("KG_ROUTE", None)
    g = json.load(open(f"{SP}/ghosts/{ep}.json"))
    me = g["names"].index("Anand Singh"); op = 1 - me
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g["seed"]}, debug=False)
    ag = [None, None]
    ag[op] = ghost_agent(g["acts"][op])
    ag[me] = ghost_agent(g["acts"][me]) if cand == "ghost" else f"{SP}/pool/{base}/main.py"
    try:
        env.run(ag)
        r = [s["reward"] for s in env.steps[-1]]; st = [s["status"] for s in env.steps[-1]]
    except Exception as e:
        r, st = [None, None], ["EXC:" + str(e)[:60]] * 2
    return {"cand": cand, "ep": ep, "seed": g["seed"], "opp": g["names"][op],
            "orig": [g["r"][me], g["r"][op]], "r": [r[me], r[op]], "st": [st[me], st[op]]}
if __name__ == "__main__":
    OUT = sys.argv[1]; CANDS = sys.argv[2].split(",")
    EPS = sorted(int(f[:-5]) for f in os.listdir(f"{SP}/ghosts")) if sys.argv[3] == "all" else [int(x) for x in sys.argv[3].split(",")]
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT):
            d = json.loads(l); done.add((d["cand"], d["ep"]))
    jobs = [(c, e) for e in EPS for c in CANDS if (c, e) not in done]
    t = time.time()
    with open(OUT, "a") as fh, ProcessPoolExecutor(max_workers=int(os.environ.get("NP", 4))) as ex:
        for res in ex.map(play, jobs):
            fh.write(json.dumps(res) + "\n"); fh.flush()
    print("done", len(jobs), "in", round(time.time() - t), "s")
