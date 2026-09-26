import sys, importlib.util, collections
from kaggle_environments import make
path, seed = sys.argv[1], int(sys.argv[2])
spec = importlib.util.spec_from_file_location("pl", path); pl = importlib.util.module_from_spec(spec); spec.loader.exec_module(pl)
Pl = pl.Planner(); orders = collections.defaultdict(list)
def ag(o, c=None):
    a = Pl.act(o, c); orders[o['step'] // 24] += [m for m in a['market'] if m[0] != 'SELL']; return a
env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}); env.run([ag, 'pool/prv_rain/main.py'])
for d in range(0, 30, 1 if len(sys.argv) < 4 else int(sys.argv[3])):
    o = env.steps[d * 24 + 12][0]['observation']; f = o['farms'][0]
    tiles = [t for row in f['tiles'] for t in row]
    crops = collections.Counter(t['crop'] for t in tiles if isinstance(t, dict) and t.get('kind') == 'PLANT')
    an = collections.Counter(t['animal'] for t in tiles if isinstance(t, dict) and 'animal' in t)
    weeds = sum(1 for t in tiles if isinstance(t, dict) and t.get('kind') == 'WEED')
    S = Pl.S.get(0, {})
    print(f"d{d:2d} ${f['money']:7.0f} land {len(f['unlocked_quadrants'])} hands {len(f['hands']):2d} zones {len(S.get('zones', []))} crops {dict(crops)} animals {dict(an)} weeds {weeds} shed {{k:v for k,v in o['private']['shed'].items() if v}} buys {collections.Counter(m[0]+(':'+m[1] if len(m)>1 else '') for m in orders[d])}")
print('final', [env.steps[-1][i]['reward'] for i in (0, 1)])
