import json, os, sys
from kaggle_environments import make
seeds = sorted({json.load(open(f"ghosts/{f}"))["seed"] for f in os.listdir("ghosts") if f.endswith(".json")})
out = {}
for s in seeds:
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": s})
    env.reset()
    while env.state[0].observation["step"] < 145:
        env.step([{}, {}])
    out[s] = list(env.state[0].observation["town"]["unlocked_shops"])
json.dump(out, open("seed_shops.json", "w"))
import collections
print(collections.Counter(tuple(v[:2]) for v in out.values()).most_common(40))
