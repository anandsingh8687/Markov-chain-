"""Raw replay of a top-team tape on other seeds vs an opponent (no repair layers)."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = json.load(open(f"{SP}/top_meta.json"))
def tape_of(ep):
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); team = M['eps'][str(ep)][0]; T = g['names'].index(team)
    return g['acts'][T], g['seed'], team
def play(job):
    ep, seed, opp = job
    acts, s0, team = tape_of(ep)
    from kaggle_environments import make
    def ag(o, c=None):
        t = o['step'] + 1; a = acts[t] if t < len(acts) else None; return a or {}
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    agents = [ag, f"{SP}/pool/{opp}/main.py"] if opp != 'v9' else [ag, f"{SP}/pool/v9_open8/main.py"]
    env.run(agents)
    r = [env.steps[-1][i]['reward'] for i in (0, 1)]
    return {'ep': ep, 'team': team, 'src_seed': s0, 'seed': seed, 'opp': opp, 'r': r}
if __name__ == "__main__":
    eps = [int(x) for x in sys.argv[1].split(',')]; seeds = [int(x) for x in sys.argv[2].split(',')]; opp = sys.argv[3]; out = sys.argv[4]
    jobs = [(e, s, opp) for e in eps for s in seeds]
    with open(out, 'w') as fh, ProcessPoolExecutor(4) as ex:
        for r in ex.map(play, jobs): fh.write(json.dumps(r) + "\n"); fh.flush(); print(r['team'][:14], r['seed'], r['r'], flush=True)
