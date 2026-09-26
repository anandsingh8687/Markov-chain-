import sys, json, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def play(a):
    seed, x, y = a
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([f'{SP}/pool/{x}/main.py', f'{SP}/pool/{y}/main.py'])
    o = lambda s: env.steps[s][0]['observation']
    f = o(264)['farms'][0]['tiles']
    straw_planted = sum(1 for d in range(0, 24) for row in o(d*24)['farms'][0]['tiles'] for t in row if isinstance(t, dict) and t.get('crop') == 'STRAWBERRY' and t.get('planted_day') == d - 0) 
    return {'seed': seed, 'd6': o(144)['town']['unlocked_shops'], 'd11': o(264)['town']['unlocked_shops'], 'd18': o(432)['town']['unlocked_shops'], 'end': o(719)['town']['unlocked_shops'],
            'straw_px': [o(d*24)['market']['prices']['STRAWBERRY'] for d in (12, 16, 20, 24, 28)]}
if __name__ == "__main__":
    seeds = [int(x) for x in open(sys.argv[1]).read().replace(',', ' ').split()]
    with ProcessPoolExecutor(4) as ex, open(sys.argv[4], 'w') as fh:
        for r in ex.map(play, [(s, sys.argv[2], sys.argv[3]) for s in seeds]): fh.write(json.dumps(r) + "\n")
