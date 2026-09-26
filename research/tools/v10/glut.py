import sys, os, collections, json
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, 'v10'); from sales import run
SH = {"BAKERY": ["EGG", "WHEAT"], "PIZZA_SHOP": ["MILK", "TOMATO", "WHEAT"], "BRUNCH_SPOT": ["EGG", "WHEAT", "STRAWBERRY"], "YARN_STORE": ["WOOL"],
      "ICE_CREAM_SHOP": ["STRAWBERRY", "MILK", "WHEAT"], "PET_CAFE": ["CARROT"], "SMOOTHIE_SHOP": ["STRAWBERRY", "MILK"], "FARMERS_MARKET": ["WHEAT", "CARROT", "TOMATO", "STRAWBERRY"]}
def job(a):
    seed, x, y = a
    s, r, LOG = run((seed, x, y))
    out = {'seed': seed, 'm': r[0] - r[1]}
    for item in ('STRAWBERRY', 'CARROT', 'MILK', 'EGG', 'MELON', 'WOOL', 'WHEAT'):
        for w, (lo, hi) in (('early', (0, 18)), ('late', (18, 30))):
            L = [p for pp, o, it, p, st in LOG if pp == 0 and o == 'SELL' and it == item and lo <= st // 24 < hi]
            out[f'{item}_{w}'] = (len(L), round(sum(L) / max(1, len(L))))
    return out
if __name__ == "__main__":
    seeds = [int(x) for x in open(sys.argv[1]).read().replace(',', ' ').split()]
    with ProcessPoolExecutor(4) as ex, open(sys.argv[4], 'w') as fh:
        for o in ex.map(job, [(s, sys.argv[2], sys.argv[3]) for s in seeds]):
            fh.write(json.dumps(o) + "\n"); fh.flush()
            print(o['seed'], ' '.join(f"{k[:5]}{k.split('_')[1][0]}:{v[0]}@{v[1]}" for k, v in o.items() if '_' in k))
