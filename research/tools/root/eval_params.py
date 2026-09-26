import sys, os, json
params = sys.argv[1]
if params and params != "{}":
    os.environ["KG_PARAMS"] = params
AG = sys.argv[2]; OPP = sys.argv[3]
seeds = [int(x) for x in sys.argv[4].split(",")]
from kaggle_environments import make
tot=[]; w=l=t=0
for s in seeds:
    for flip in (False, True):
        env = make("kaggriculture", configuration={"episodeSteps":720,"seed":s}, debug=False)
        x,y = (OPP,AG) if flip else (AG,OPP)
        try:
            env.run([x,y])
        except Exception as e:
            print(json.dumps({"err":str(e)[:100]})); sys.exit(1)
        r=[q["reward"] for q in env.steps[-1]]
        ra,rb = (r[1],r[0]) if flip else (r[0],r[1])
        if ra is None or rb is None:
            print(json.dumps({"err":"none reward"})); sys.exit(1)
        tot.append(ra)
        if ra>rb: w+=1
        elif rb>ra: l+=1
        else: t+=1
n=max(1,w+l+t)
print(json.dumps({"p":params,"mean":round(sum(tot)/len(tot)),"min":min(tot),"win":round(w/n,3),"w":w,"l":l,"t":t}))
