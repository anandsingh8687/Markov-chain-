import sys, time, json, collections
from kaggle_environments import make
path, opp, seed = sys.argv[1], sys.argv[2], int(sys.argv[3])
ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
fn = ns['agent']; T = []
def timed(o, c=None):
    t = time.perf_counter(); a = fn(o, c); T.append(time.perf_counter() - t); return a
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
env.run([timed, f'pool/{opp}/main.py'])
T.sort()
print(f"steps {len(T)} mean {sum(T)/len(T)*1000:.1f}ms p99 {T[int(.99*len(T))]*1000:.0f}ms max {T[-1]*1000:.0f}ms total {sum(T):.1f}s  result {[env.steps[-1][i]['reward'] for i in (0,1)]} status {[env.steps[-1][i]['status'] for i in (0,1)]}")
cash = [(d, env.steps[d*24][0]['observation']['farms'][0]['money'], len([t for row in env.steps[d*24][0]['observation']['farms'][0]['tiles'] for t in row if isinstance(t, dict) and 'animal' in t]), len(env.steps[d*24][0]['observation']['farms'][0]['unlocked_quadrants']), len(env.steps[d*24][0]['observation']['farms'][0]['hands'])) for d in range(0, 30, 2)]
print(' '.join(f"d{d}:${m/1000:.1f}k/{a}an/{q}q/{h}h" for d, m, a, q, h in cash))
