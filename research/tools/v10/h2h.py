"""Run agent A (seat 0) vs each opponent on seeds; append jsonl incrementally."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def play(job):
    seed, a, b = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([f'{SP}/pool/{a}/main.py', f'{SP}/pool/{b}/main.py'])
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    o = env.steps[-1][0]['observation']
    s18 = list(env.steps[432][0]['observation']['town']['unlocked_shops'])
    return {'seed': seed, 'a': a, 'opp': b, 'm': r[0] - r[1], 'r': r, 'shops': list(o['town']['unlocked_shops']), 's18': s18}
if __name__ == "__main__":
    seeds = [int(x) for x in open(sys.argv[1]).read().replace(',', ' ').split()]
    agents = sys.argv[2].split(','); opps = sys.argv[3].split(','); out = sys.argv[4]
    jobs = [(s, a, o) for s in seeds for o in opps for a in agents]
    with ProcessPoolExecutor(int(os.environ.get('NP', 4))) as ex, open(out, 'a') as fh:
        for f in as_completed([ex.submit(play, j) for j in jobs]):
            fh.write(json.dumps(f.result()) + "\n"); fh.flush()
