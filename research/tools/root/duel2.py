import sys, time
from kaggle_environments import make
def one(a,b,seed):
    env=make("kaggriculture",configuration={"episodeSteps":720,"seed":seed},debug=False)
    env.run([a,b]); last=env.steps[-1]
    return [s["reward"] for s in last],[s["status"] for s in last]
if __name__=="__main__":
    A,B=sys.argv[1],sys.argv[2]; seeds=[int(x) for x in sys.argv[3].split(",")]
    w=l=t=0; sa=[]; sb=[]
    for s in seeds:
        for (x,y,flip) in ((A,B,False),(B,A,True)):
            r,st=one(x,y,s)
            ra,rb=(r[1],r[0]) if flip else (r[0],r[1])
            sa.append(ra); sb.append(rb)
            if ra>rb: w+=1
            elif rb>ra: l+=1
            else: t+=1
            print(f"seed={s} flip={int(flip)} A={ra} B={rb} {st}",flush=True)
    n=w+l+t
    print(f"RESULT A(win/loss/tie)={w}/{l}/{t}  winrate={w/n:.3f}  meanA={sum(sa)/len(sa):.0f} meanB={sum(sb)/len(sb):.0f}")
