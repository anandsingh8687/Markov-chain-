import json, os, sys, random
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(seed):
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 13 * 24, "seed": seed})
    env.run([f'{SP}/pool/u16sH/main.py', f'{SP}/pool/fr16/main.py'])
    shops = env.steps[-1][0]['observation']['town']['unlocked_shops']
    return seed, shops
seeds = random.Random(1234).sample(range(10**6, 2 * 10**9), int(sys.argv[1]))
with ProcessPoolExecutor(int(os.environ.get('NP', 2))) as ex:
    out = list(ex.map(run, seeds))
json.dump(out, open('v12/yarnseeds.json', 'w'))
ys = [s for s, sh in out if sh.count('YARN_STORE') >= 2]
print(len(ys), 'of', len(out)); open('seeds_yarn.txt', 'w').write(' '.join(map(str, ys)))
