"""gbtop.py SPEC AGENT OUT: replay recorded games with AGENT in a chosen seat.
SPEC lines: "<ep> <seat>" (seat = index our agent takes; the other side replays its record)."""
import json, sys, os
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def run(a):
    ep, seat, path = a
    from kaggle_environments import make
    g = json.load(open(f"{SP}/ghosts/{ep}.json")); op = 1 - seat
    ns = {'__name__': 'x'}; exec(compile(open(path).read(), path, 'exec'), ns)
    fn = [v for v in ns.values() if callable(v)][-1]
    acts = g['acts'][op]
    def ghost(o, c=None):
        t = o['step'] + 1; x = acts[t] if t < len(acts) else None; return x or {}
    ag = [None, None]; ag[seat] = fn; ag[op] = ghost
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g['seed']})
    env.run(ag)
    r = [env.steps[-1][i]['reward'] for i in (seat, op)]
    return {'ep': ep, 'seat': seat, 'opp': g['names'][op], 'replaced': g['names'][seat],
            'orig': g['r'][seat] - g['r'][op], 'm': r[0] - r[1], 'bank': r[0], 'opp_bank': r[1]}
if __name__ == "__main__":
    spec = [tuple(map(int, l.split())) for l in open(sys.argv[1]) if l.strip()]
    path = sys.argv[2]; out = sys.argv[3]
    with ProcessPoolExecutor(int(os.environ.get('NP', 4))) as ex, open(out, 'w') as fh:
        res = list(ex.map(run, [(e, s, path) for e, s in spec]))
        for r in res: fh.write(json.dumps(r) + "\n")
    w = sum(r['m'] > 0 for r in res)
    print(f"{os.path.basename(os.path.dirname(path))}: won {w}/{len(res)} (replaced side orig {sum(r['orig'] > 0 for r in res)}), mean {sum(r['m'] for r in res)/len(res):+.0f}, bank {sum(r['bank'] for r in res)/len(res):.0f} vs opp {sum(r['opp_bank'] for r in res)/len(res):.0f}")
