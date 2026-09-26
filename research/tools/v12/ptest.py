"""Run a planner module (no error guard) vs an opponent; report bank, production and failures."""
import sys, importlib.util, collections, traceback, json
from concurrent.futures import ProcessPoolExecutor
def run(a):
    seed, path, opp = a
    from kaggle_environments import make
    spec = importlib.util.spec_from_file_location("pl", path); pl = importlib.util.module_from_spec(spec); spec.loader.exec_module(pl)
    Pl = pl.Planner(); errs = []
    def ag(o, c=None):
        try: return Pl.act(o, c)
        except Exception: errs.append(traceback.format_exc().splitlines()[-3:]); return {"farmer": ["PASS"], "hands": [], "market": []}
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}); env.run([ag, f'pool/{opp}/main.py'])
    deaths = 0; prev = None
    for st in env.steps:
        tiles = st[0]['observation']['farms'][0]['tiles']
        if prev:
            for y in range(10):
                for x in range(10):
                    if isinstance(prev[y][x], dict) and prev[y][x].get('kind') == 'PLANT' and isinstance(tiles[y][x], dict) and tiles[y][x].get('kind') == 'WEED': deaths += 1
        prev = tiles
    f = env.steps[-1][0]['observation']['farms'][0]
    animals = collections.Counter(t['animal'] for row in f['tiles'] for t in row if isinstance(t, dict) and 'animal' in t)
    return seed, [env.steps[-1][i]['reward'] for i in (0, 1)], len(errs), errs[:1], deaths, dict(animals), f['unlocked_quadrants']
if __name__ == "__main__":
    seeds = [int(x) for x in open(sys.argv[1]).read().replace(',', ' ').split()][:int(sys.argv[4]) if len(sys.argv) > 4 else 99]
    with ProcessPoolExecutor(4) as ex:
        R = list(ex.map(run, [(s, sys.argv[2], sys.argv[3]) for s in seeds]))
    for r in R: print(r[0], 'bank', r[1][0], 'opp', r[1][1], 'errors', r[2], r[3], 'plant deaths', r[4], 'animals', r[5], 'land', r[6])
    print('MEAN bank', round(sum(r[1][0] for r in R) / len(R)), 'opp', round(sum(r[1][1] for r in R) / len(R)))
