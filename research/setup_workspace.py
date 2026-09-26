"""Rebuild the research workspace the tools in research/tools/ expect.

    python research/setup_workspace.py WORKDIR

Creates WORKDIR/pool/<name>/main.py (our versions and the public benchmark
opponents, under the names the scripts use), WORKDIR/ghosts/<episode>.json
(recorded ladder games, from research/data/ladder_replays.json.gz), copies the
episode lists and the scripts, then run the tools from inside WORKDIR, e.g.

    cd WORKDIR && python v10/gb.py eps_v11_all.txt pool/v12/main.py out.jsonl

Needs `pip install kaggle-environments==1.32.7`. Downloading new ladder games
(fetchghost.py, v*status.py) also needs KAGGLE_API_TOKEN in the environment;
never commit a token.
"""
import gzip, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "workspace")

# names the scripts use -> files in the repo
POOL = {
    "my_v3": "versions/v3/main.py", "my_v6": "versions/v6/main.py", "my_v7": "versions/v7/main.py",
    "v8": "versions/v8/main.py", "v9_open8": "versions/v9/main.py", "v10d": "versions/v10/main.py",
    "v11i": "versions/v11/main.py", "c1": "versions/v12/main.py", "v12": "versions/v12/main.py",
    "v10c": "candidates/v10c/main.py",
}
for d in sorted(os.listdir(os.path.join(ROOT, "versions", "experimental"))):
    POOL[d] = f"versions/experimental/{d}/main.py"
for d in sorted(os.listdir(os.path.join(HERE, "opponents"))):
    POOL[d] = f"research/opponents/{d}/main.py"

os.makedirs(W, exist_ok=True)
for name, rel in POOL.items():
    src = os.path.join(ROOT, rel)
    if not os.path.exists(src):
        continue
    dst = os.path.join(W, "pool", name)
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(os.path.dirname(src)):
        shutil.copy(os.path.join(os.path.dirname(src), f), dst)

os.makedirs(os.path.join(W, "ghosts"), exist_ok=True)
with gzip.open(os.path.join(HERE, "data", "ladder_replays.json.gz"), "rt") as fh:
    pack = json.load(fh)
for ep, g in pack.items():
    with open(os.path.join(W, "ghosts", f"{ep}.json"), "w") as out:
        json.dump(g, out)

for f in os.listdir(os.path.join(HERE, "data", "episodes")):
    shutil.copy(os.path.join(HERE, "data", "episodes", f), W)
for f in ("s8.txt", "s16.txt", "s24b.txt", "fresh150.txt"):
    p = os.path.join(HERE, "data", "episodes", f)
    if os.path.exists(p):
        os.makedirs(os.path.join(W, "v10"), exist_ok=True); shutil.copy(p, os.path.join(W, "v10", f))
for sub in ("v10", "v12"):
    shutil.copytree(os.path.join(HERE, "tools", sub), os.path.join(W, sub), dirs_exist_ok=True)
for f in os.listdir(os.path.join(HERE, "tools", "root")):
    shutil.copy(os.path.join(HERE, "tools", "root", f), W)
print(f"workspace ready: {W}  ({len(POOL)} agents, {len(pack)} recorded games)")
