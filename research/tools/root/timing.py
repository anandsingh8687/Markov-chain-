import sys, time
from kaggle_environments import make
path = sys.argv[1]; opp = sys.argv[2]; seed = int(sys.argv[3])
env0 = {}; exec(compile(open(path).read(), path, "exec"), env0)
fn = [v for v in env0.values() if callable(v)][-1]
ts = []
def timed(obs, config=None):
    t = time.perf_counter(); a = fn(obs, config); ts.append(time.perf_counter() - t); return a
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=False)
env.run([timed, opp])
ts.sort(); n = len(ts)
print("%s: turns=%d mean=%.1fms p99=%.1fms max=%.1fms  total=%.1fs  reward=%s" % (
    path.split('/')[-2], n, 1000*sum(ts)/n, 1000*ts[int(n*.99)], 1000*ts[-1], sum(ts),
    [s["reward"] for s in env.steps[-1]]))
