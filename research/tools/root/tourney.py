"""Round-robin among pool agents on real ladder seeds, both sides."""
import itertools, json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
POOL = sys.argv[1]; OUT = sys.argv[2]
AGENTS = sys.argv[3].split(","); SEEDS = [int(s) for s in sys.argv[4].split(",")]
def play(job):
    a, b, seed = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    try:
        env.run([os.path.join(POOL, a, "main.py"), os.path.join(POOL, b, "main.py")])
        r = [s["reward"] for s in env.steps[-1]]; st = [s["status"] for s in env.steps[-1]]
    except Exception as e:
        r, st = [None, None], ["EXC:" + str(e)[:40]] * 2
    return {"a": a, "b": b, "seed": seed, "r": r, "st": st}
jobs = [(a, b, s) for a, b in itertools.permutations(AGENTS, 2) for s in SEEDS]
t = time.time()
with open(OUT, "w") as fh, ProcessPoolExecutor(max_workers=4) as ex:
    for i, res in enumerate(ex.map(play, jobs)):
        fh.write(json.dumps(res) + "\n"); fh.flush()
print("done", len(jobs), "episodes in", round(time.time() - t), "s")
