"""Both-seat head-to-head: agent A vs opponents on seeds; margin from A's side; jsonl out."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def play(job):
    seed, a, b, seat = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    ps = [f'{SP}/pool/{a}/main.py', f'{SP}/pool/{b}/main.py']
    if seat: ps = ps[::-1]
    env.run(ps)
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    if seat: r = r[::-1]
    return {'seed': seed, 'a': a, 'opp': b, 'seat': seat, 'm': r[0] - r[1], 'r': r}
if __name__ == "__main__":
    seeds = [int(x) for x in open(sys.argv[1]).read().split()]
    agents = sys.argv[2].split(','); opps = sys.argv[3].split(','); out = sys.argv[4]
    jobs = [(s, a, o, seat) for s in seeds for o in opps for a in agents for seat in (0, 1) if a != o]
    with ProcessPoolExecutor(int(os.environ.get('NP', 4))) as ex, open(out, 'a') as fh:
        for f in as_completed([ex.submit(play, j) for j in jobs]):
            fh.write(json.dumps(f.result()) + "\n"); fh.flush()
