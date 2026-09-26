"""Replay a top team's recorded tape raw, on its own seed, against a live opponent."""
import json, sys, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
M = json.load(open('top_meta.json')); tops = set(k for k in M if k != 'eps')
def run(a):
    ep, opp = a
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{ep}.json"))
    T = [i for i in (0, 1) if g['names'][i] in tops]
    if not T: return None
    ti = T[0]; acts = g['acts'][ti]
    def tape(o, c=None):
        t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
    ag = [None, None]; ag[ti] = tape; ag[1 - ti] = f'{SP}/pool/{opp}/main.py'
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']}); env.run(ag)
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    return ep, g['names'][ti], g['r'][ti], r[ti], r[1 - ti]
if __name__ == "__main__":
    eps = [e for e in M['eps'] if os.path.exists(f'ghosts/{e}.json')][:int(sys.argv[2])]
    with ProcessPoolExecutor(4) as ex:
        for res in ex.map(run, [(e, sys.argv[1]) for e in eps]):
            if res: print(f"{res[0]} {res[1][:14]:14s} recorded bank {res[2]:9,.0f} | replayed vs {sys.argv[1]}: tape {res[3]:9,.0f}  opp {res[4]:9,.0f}  margin {res[3]-res[4]:+8,.0f}")
