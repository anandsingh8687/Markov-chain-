"""Planner bench: planner (optionally after v11's tape until `switch`) vs an opponent."""
import json, sys, importlib.util, collections, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(args):
    seed, fmpath, opp, switch, params = args
    from kaggle_environments import make
    spec = importlib.util.spec_from_file_location("fm", fmpath); fm = importlib.util.module_from_spec(spec); spec.loader.exec_module(fm)
    if hasattr(fm, 'P'): fm.P.update(params)
    F = fm.Foreman()
    base = None
    if switch > 0:
        ns = {'__name__': 'x'}; exec(compile(open(f'{SP}/pool/v11i/main.py').read(), 'v11', 'exec'), ns); base = ns['agent']
    def ag(o, c=None):
        return base(o, c) if o['step'] < switch else F.act(o, c)
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed})
    env.run([ag, f'{SP}/pool/{opp}/main.py'])
    st = env.steps[-1]
    return {'seed': seed, 'r': [st[i]['reward'] for i in (0, 1)], 'status': [st[i]['status'] for i in (0, 1)]}
if __name__ == "__main__":
    seeds = [int(x) for x in open(sys.argv[1]).read().replace(',', ' ').split()]
    fmpath, opp, switch = sys.argv[2], sys.argv[3], int(sys.argv[4])
    params = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(run, [(s, fmpath, opp, switch, params) for s in seeds]))
    print(os.path.basename(fmpath), 'switch', switch, 'bank', round(sum(r['r'][0] for r in res) / len(res)), 'opp', round(sum(r['r'][1] for r in res) / len(res)),
          'W', sum(r['r'][0] > r['r'][1] for r in res), '/', len(res), 'status', set(tuple(r['status']) for r in res))
