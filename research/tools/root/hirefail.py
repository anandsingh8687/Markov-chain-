import json, sys, collections
import kaggle_environments.envs.kaggriculture.kaggriculture as K
from ghostrun import ghost_agent
CUR = {}; EV = []
opm, oh = K._process_market, K._do_hire
def pm(state, env):
    CUR['state'] = state; return opm(state, env)
def dh(farm, private, board_size, mult=1):
    n = farm['hires_today']; before = len(farm['hands']); oh(farm, private, board_size, mult)
    st = CUR['state']; p = 0 if private is st[0].observation.private else 1
    EV.append((p, st[0].observation.get('step'), len(farm['hands']) > before))
K._process_market, K._do_hire = pm, dh
def run(ep):
    g = json.load(open(f"ghosts/{ep}.json")); me = g["names"].index("Anand Singh"); op = 1 - me
    from kaggle_environments import make
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": g["seed"]})
    EV.clear(); env.run([ghost_agent(g["acts"][0]), ghost_agent(g["acts"][1])])
    fu = [(s) for p, s, ok in EV if p == me and not ok]; fo = [s for p, s, ok in EV if p == op and not ok]
    return g, me, op, fu, fo
if __name__ == "__main__":
    for ep in open(sys.argv[1]).read().split():
        g, me, op, fu, fo = run(int(ep))
        m = g['r'][me] - g['r'][op]
        print(ep, g['names'][op][:16].ljust(16), f"{m:+7.0f}", 'failed hires us', len(fu), sorted(set(s//24 for s in fu))[:8], 'opp', len(fo))
