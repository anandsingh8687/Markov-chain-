"""Coordinate search over the agent's tunables. Cloud-only; 4-way parallel."""
import json, subprocess, sys, itertools, os, time
SP = os.path.dirname(os.path.abspath(__file__))
PY_ = SP + "/.venv/bin/python"
AG = sys.argv[1] if len(sys.argv) > 1 else "v10/main.py"
OPP = sys.argv[2] if len(sys.argv) > 2 else "v7/main.py"
SEEDS = sys.argv[3] if len(sys.argv) > 3 else "1,2,3,4"
ROUNDS = int(sys.argv[4]) if len(sys.argv) > 4 else 2

GRID = [
    ("PLACE_FIX", [0, 1]),
    ("FERT_USE", [0, 1]),
    ("SELL_SLOTS", [4, 6, 9]),
    ("HIRE_FRAC", [0.10, 0.16, 0.22, 0.32]),
    ("MAX_HANDS", [11, 12, 13, 14, 15]),
    ("HIRE_OFF", [0, 1, 2]),
    ("RUNWAY", [2.0, 3.0, 4.0, 6.0, 9.0]),
    ("OVERSUPPLY", [1.0, 1.35, 1.8, 2.5]),
    ("BUY_RATE", [2, 4, 7]),
    ("LAND_OPEN", [5, 8, 14, 22]),
    ("CARRY_DROP", [7, 11, 16, 24]),
    ("PER_RANCHER", [3.5, 5.5, 8.0]),
    ("ACT_ANIMAL", [2.2, 2.9, 3.8]),
    ("ACT_CROP", [0.85, 1.15, 1.5]),
    ("MOVE", [1.5, 1.85, 2.3]),
    ("WEED_W", [3.0, 6.0, 7.5, 11.0]),
    ("ANIM_MARGIN", [0.6, 1.0, 1.5]),
    ("LAND_LABOR", [0.4, 1.0, 2.0]),
]


def run_batch(param_list):
    procs = []
    for p in param_list:
        procs.append((p, subprocess.Popen(
            [PY_, SP + "/eval_params.py", json.dumps(p), AG, OPP, SEEDS],
            cwd=SP, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)))
    out = []
    for p, pr in procs:
        so, _ = pr.communicate()
        try:
            r = json.loads(so.decode().strip().splitlines()[-1])
            if "err" in r:
                out.append((p, -1e9, r))
            else:
                out.append((p, r["mean"], r))
        except Exception:
            out.append((p, -1e9, {"err": "parse"}))
    return out


best = {}
res = run_batch([dict(best)])
bestval = res[0][1]
print("base", bestval, flush=True)
for rnd in range(ROUNDS):
    for key, vals in GRID:
        cands = []
        for v in vals:
            if best.get(key) == v:
                continue
            c = dict(best); c[key] = v
            cands.append(c)
        allres = []
        for i in range(0, len(cands), 4):
            allres += run_batch(cands[i:i + 4])
        allres.sort(key=lambda x: -x[1])
        if allres and allres[0][1] > bestval + 250:
            best = allres[0][0]; bestval = allres[0][1]
            print(f"r{rnd} {key} -> {best.get(key)}  mean={bestval:.0f}  {json.dumps(best)}", flush=True)
        else:
            print(f"r{rnd} {key} keep (best cand {allres[0][1]:.0f} vs {bestval:.0f})", flush=True)
print("BEST", json.dumps(best), bestval)
