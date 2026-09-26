import json, os, sys
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P=["WHEAT","CARROT","TOMATO","STRAWBERRY","MELON","EGG","MILK","WOOL","FERTILIZER"]
def play(job):
    seed, a, b = job
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([f'{SP}/pool/{a}/main.py', f'{SP}/pool/{b}/main.py'])
    out=[]
    for d in (8,15,22,29):
        o=env.steps[d*24][0]['observation']
        out.append((d,[(o['market']['prices'][p],o['market']['inventory'][p]-10000) for p in P]))
    return seed,[env.steps[-1][i]['reward'] for i in (0,1)],out
if __name__=="__main__":
    seeds=[int(x) for x in sys.argv[1].split(',')]
    with ProcessPoolExecutor(4) as ex:
        for seed,r,out in ex.map(play,[(s,sys.argv[2],sys.argv[3]) for s in seeds]):
            print(seed,r); print("      "+" ".join(f"{p[:6]:>11}" for p in P))
            for d,row in out: print(f"  d{d:2d} "+" ".join(f"{pr:4d}/{inv:+5d} " for pr,inv in row))
