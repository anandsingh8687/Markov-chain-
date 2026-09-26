import sys, time, json
from kaggle_environments import make
path, seed = sys.argv[1], int(sys.argv[2])
t = time.time()
try:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
    env.run([path, path])
    r = [s["reward"] for s in env.steps[-1]]; st = [s["status"] for s in env.steps[-1]]
    print(json.dumps({"r": r, "st": st, "sec": round(time.time() - t, 1)}))
except Exception as e:
    print(json.dumps({"err": str(e)[:120]}))
