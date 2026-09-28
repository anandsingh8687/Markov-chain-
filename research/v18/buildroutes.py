"""buildroutes.py BASE OUT TEAMS(comma|ALL6) : V16 chassis with route library replaced by current top-team tapes."""
import json, sys, zlib, base64, collections
base, out, teams = sys.argv[1], sys.argv[2], sys.argv[3]
FAM = ['M & M & P & Q', 'DSM', 'Vadim Vasilenko', 'DECEM', 'Unknown Mother-Goose', 'mtmr_s1']
T = FAM if teams == 'ALL6' else teams.split(',')
M = json.load(open('top10_meta.json'))
best = {}
for m in M:
    if m['team'] not in T or not m['first']: continue
    margin = m['bank'] - m['oppbank']
    if m['first'] not in best or margin > best[m['first']][0]:
        best[m['first']] = (margin, m)
routes = {}; selected = {}
for i, (shop, (mg, m)) in enumerate(sorted(best.items())):
    g = json.load(open(f"ghosts/{m['ep']}.json"))
    routes[str(i)] = g['acts'][m['seat']][1:]
    selected[shop] = i
    print(shop, m['team'], m['ep'], 'margin', round(mg), 'bank', round(m['bank']))
# opening: the tape of the most common first shop is fine for steps < 72 (identical opening family)
opening = selected[max(best, key=lambda s: best[s][0])]
blob = base64.b64encode(zlib.compress(json.dumps({'routes': routes, 'selected': selected, 'opening_route': opening}).encode(), 9)).decode()
layer = f'''

# ==== V19 route library: current top-team tapes (public replays, Competition Data, Apache-2.0 terms) ====
_V19_DATA = _v16_json.loads(_v16_zlib.decompress(_v16_b64.b64decode("{blob}")))
_V19_OFFSET = 5000
for _k, _v in _V19_DATA["routes"].items():
    _IMPL.chassis.routes[_V19_OFFSET + int(_k)] = _v
_V16_ROUTE_OFFSET = _V19_OFFSET
_V16_OPENING_ROUTE = int(_V19_DATA["opening_route"])
_V16_SELECTED = {{str(k): int(v) for k, v in _V19_DATA["selected"].items()}}
'''
src = open(base).read()
i = src.index('_IMPL.chassis.router = _v16_first_shop_router')
src = src[:i] + layer + '\n' + src[i:]
open(out, 'w').write(src)
