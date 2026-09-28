"""Screen every downloaded notebook agent: one game vs V18d (seed 7) — keep the ones that run and score high."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(c):
    try:
        from kaggle_environments import make
        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 1045055387})
        env.run([f'{SP}/nb4/{c}/main.py', f'{SP}/pool/u16sHw/main.py'])
        st = [env.steps[-1][i]['status'] for i in (0, 1)]
        return c, env.steps[-1][0]['reward'], env.steps[-1][1]['reward'], st[0]
    except Exception as e:
        return c, -1, -1, 'EXC'
cands = sorted(d for d in os.listdir(f"{SP}/nb4") if os.path.exists(f"{SP}/nb4/{d}/main.py"))
with ProcessPoolExecutor(4) as ex:
    res = list(ex.map(run, cands))
json.dump(res, open('v12/nbscreen.json', 'w'))
res.sort(key=lambda x: -(x[1] - x[2]))
for c, a, b, s in res[:40]: print(f'{a - b:+9.0f} {a:9.0f} {b:9.0f} {s} {c}')
print('ran ok', sum(1 for r in res if r[3] == 'DONE'), 'of', len(res))
