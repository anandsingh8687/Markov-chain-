import json, os, sys
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def play(job):
    seed, a, b = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([f'{SP}/pool/{a}/main.py', f'{SP}/pool/{b}/main.py'])
    out = []
    for st in env.steps[::24]:
        o = st[0]['observation']
        out.append((o['step']//24, o['market']['prices']['TOMATO'], o['market']['inventory']['TOMATO'], list(o['town']['unlocked_shops'])))
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    return seed, r, out
if __name__ == "__main__":
    seeds = [int(x) for x in sys.argv[1].split(',')]
    with ProcessPoolExecutor(4) as ex:
        for seed, r, out in ex.map(play, [(s, sys.argv[2], sys.argv[3]) for s in seeds]):
            print(seed, r)
            for d, p, inv, shops in out:
                if d % 3 == 0 or d > 26: print(f"  d{d:2d} tomato ${p:4d} inv {inv-10000:+5d} shops {shops}")
