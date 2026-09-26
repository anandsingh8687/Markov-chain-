"""Identify ladder opponents: replay our recorded side, run pool agent X in the opponent seat,
and report how many consecutive steps X reproduces the opponent's recorded actions."""
import json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.abspath(__file__))
class Diverged(Exception): pass
def norm(a): return json.dumps(a if a else {}, sort_keys=True)
def load(path):
    src = open(path).read(); ns = {"__name__": "agentmod"}
    exec(compile(src, path, "exec"), ns)
    return [v for v in ns.values() if callable(v)][-1]
def play(job):
    name, ep = job
    g = json.load(open(f"{SP}/ghosts/{ep}.json"))
    me = g["names"].index("Anand Singh"); op = 1 - me
    mine, theirs = g["acts"][me], g["acts"][op]
    X = load(f"{SP}/pool/{name}/main.py")
    state = {"n": 0}
    def xa(obs, cfg=None):
        t = obs["step"]; a = X(obs, cfg)
        if t + 1 < len(theirs) and norm(json.loads(json.dumps(a))) != norm(theirs[t + 1]):
            raise Diverged()
        state["n"] = t + 1
        return a
    def ga(obs, cfg=None):
        t = obs["step"]; return mine[t + 1] if t + 1 < len(mine) and mine[t + 1] else {}
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g["seed"]}, debug=False)
    ag = [None, None]; ag[me] = ga; ag[op] = xa
    try: env.run(ag)
    except Exception: pass
    return {"ep": ep, "opp": g["names"][op], "agent": name, "match": state["n"]}
if __name__ == "__main__":
    OUT = sys.argv[1]; NAMES = sys.argv[2].split(",")
    EPS = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else sorted(int(f[:-5]) for f in os.listdir(f"{SP}/ghosts") if f.endswith(".json"))
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT): d = json.loads(l); done.add((d["agent"], d["ep"]))
    jobs = [(n, e) for e in EPS for n in NAMES if (n, e) not in done]
    with open(OUT, "a") as fh, ProcessPoolExecutor(max_workers=int(os.environ.get("NP", 4))) as ex:
        for r in ex.map(play, jobs):
            fh.write(json.dumps(r) + "\n"); fh.flush()
