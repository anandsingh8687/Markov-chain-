"""Turn a replay (full JSON) into compact ghost files: ghosts/<ep>.json = {seed, names, r, acts:[seat0 list, seat1 list]}."""
import json, sys, os
def compact(d, ep):
    acts = [[d['steps'][t][i]['action'] for t in range(len(d['steps']))] for i in range(2)]
    return {"ep": ep, "seed": d['info'].get('seed'), "names": d['info']['TeamNames'],
            "r": d['rewards'], "acts": acts}
if __name__ == "__main__":
    for f in sys.argv[1:]:
        d = json.load(open(f)); ep = int(os.path.basename(f).split('-')[1])
        json.dump(compact(d, ep), open(f"ghosts/{ep}.json", "w"), separators=(",", ":"))
        print(ep, d['info'].get('seed'), d['info']['TeamNames'], d['rewards'])
