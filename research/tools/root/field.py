"""Each candidate vs each field opponent, both sides, on real ladder seeds."""
import json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
POOL, OUT = sys.argv[1], sys.argv[2]
CANDS = sys.argv[3].split(","); FIELD = sys.argv[4].split(",")
SEEDS = [int(s) for s in sys.argv[5].split(",")]
def play(job):
    c, f, seed, flip = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    pa, pb = os.path.join(POOL, c, "main.py"), os.path.join(POOL, f, "main.py")
    try:
        env.run([pb, pa] if flip else [pa, pb])
        r = [s["reward"] for s in env.steps[-1]]; st = [s["status"] for s in env.steps[-1]]
        if flip: r, st = r[::-1], st[::-1]
    except Exception as e:
        r, st = [None, None], ["EXC"] * 2
    return {"cand": c, "opp": f, "seed": seed, "flip": flip, "r": r, "st": st}
jobs = [(c, f, s, fl) for c in CANDS for f in FIELD if f != c for s in SEEDS for fl in ((False,) if os.environ.get("ONESIDE") else (False, True))]
t = time.time()
with open(OUT, "w") as fh, ProcessPoolExecutor(max_workers=4) as ex:
    for res in ex.map(play, jobs):
        fh.write(json.dumps(res) + "\n"); fh.flush()
print("done", len(jobs), "in", round(time.time() - t), "s")
