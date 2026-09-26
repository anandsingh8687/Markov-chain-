import sys
from kaggle_environments import make
a=sys.argv[1]; seed=int(sys.argv[2]) if len(sys.argv)>2 else 1
opp=sys.argv[3] if len(sys.argv)>3 else "pass"
env=make("kaggriculture",configuration={"episodeSteps":720,"seed":seed},debug=True)
env.run([a,opp])
for i,st in enumerate(env.steps):
    if i%24!=12: continue
    o=st[0]["observation"]; f=o["farms"][0]
    pr=st[0]["observation"]["private"]
    cnt={}
    for row in f["tiles"]:
        for t in row:
            if isinstance(t,dict):
                k = t["crop"] if t.get("kind")=="PLANT" else (t["animal"] if "animal" in t else t.get("kind"))
                cnt[k]=cnt.get(k,0)+1
    shed={k:v for k,v in pr["shed"].items() if v}
    carr={}
    for iv in pr["inventories"]:
        for k,v in iv.items(): carr[k]=carr.get(k,0)+v
    mi=o["market"]["inventory"]
    print(f"d{i//24:2d} $={f['money']:>8.0f} hands={len(f['hands']):2d} q={len(f['unlocked_quadrants'])} {cnt} shed={shed} carry={carr} mktEGG={mi['EGG']-10000} mktWH={mi['WHEAT']-10000} mktMEL={mi['MELON']-10000} mktCAR={mi['CARROT']-10000}")
print("FINAL", env.steps[-1][0]["reward"], env.steps[-1][1]["reward"])
