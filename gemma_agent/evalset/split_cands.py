"""split_cands.py CANDIDATES_JSON OUT_DIR [--parts 4] [--seed 20261018] [--frac-a 0.6] [--pilot 10]

Repo-disjoint splits of the candidate list:
  part{1..P}.json   build shards (no repo in two parts; greedy balance of candidate counts over shuffled repos)
  pilot.json        a small mixed shard for the end-to-end pilot kernel (subset of part1)
  split_manifest.json  {seed, frac_a, repos: {repo: {split, part}}, tasks: {instance_id: {repo, split, part, src}}}
A (~60% of repos, for tuning) / B (~40%, sealed: nobody reads its trajectories) is drawn by repo with a seeded RNG,
so it does not depend on which candidates later survive the gold check.
"""
import argparse, collections, json, random
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('cands'); ap.add_argument('out')
ap.add_argument('--parts', type=int, default=4); ap.add_argument('--seed', type=int, default=20261018)
ap.add_argument('--frac-a', type=float, default=0.6); ap.add_argument('--pilot', type=int, default=10)
a = ap.parse_args()
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
cands = json.load(open(a.cands))
by_repo = collections.defaultdict(list)
for c in cands:
    by_repo[c['repo'].lower()].append(c)
repos = sorted(by_repo)
rng = random.Random(a.seed)
rng.shuffle(repos)
n_a = round(a.frac_a * len(repos))
split = {r: ('A' if i < n_a else 'B') for i, r in enumerate(repos)}
load = [0] * a.parts
part = {}
for r in sorted(repos, key=lambda r: (-len(by_repo[r]), repos.index(r))):
    k = min(range(a.parts), key=lambda i: (load[i], i))
    part[r] = k + 1
    load[k] += len(by_repo[r])
shards = {k: [] for k in range(1, a.parts + 1)}
for r in repos:
    for c in by_repo[r]:
        shards[part[r]].append(dict(c, split=split[r], part=part[r]))
for k, rows in shards.items():
    rows.sort(key=lambda c: (c['repo'].lower(), c['instance_id']))
    (out / f'part{k}.json').write_text(json.dumps(rows, indent=0))
# pilot: first candidates of part1 mixing sources (2 known-valid pilot repos are included when present)
p1 = shards[1]
known = [c for c in p1 if c['instance_id'] in {'pycqa__isort-2491', 'mpmath__mpmath-992', 'BrianPugh__cyclopts-633',
                                               'pdm-project__pdm-3575', 'neurodatawithoutborders__pynwb-2060'}]
pilot = known[:3]
for src in ('lb', 'v2', 'rb', 'lb', 'v2', 'lb', 'v2', 'lb', 'v2', 'lb', 'v2'):
    for c in p1:
        if len(pilot) >= a.pilot: break
        if c['src'] == src and c not in pilot and c['repo'].lower() not in {x['repo'].lower() for x in pilot}:
            pilot.append(c); break
(out / 'pilot.json').write_text(json.dumps(pilot, indent=0))
man = dict(seed=a.seed, frac_a=a.frac_a, parts=a.parts, source=str(a.cands),
           repos={r: dict(split=split[r], part=part[r], n_candidates=len(by_repo[r])) for r in sorted(repos)},
           tasks={c['instance_id']: dict(repo=c['repo'], split=split[c['repo'].lower()], part=part[c['repo'].lower()],
                                         src=c['src'], created_at=c['created_at']) for c in cands})
(out / 'split_manifest.json').write_text(json.dumps(man, indent=1, sort_keys=True))
cnt = collections.Counter((part[r], split[r]) for r in repos)
print('repos', len(repos), 'A', sum(v == 'A' for v in split.values()), 'B', sum(v == 'B' for v in split.values()))
for k in range(1, a.parts + 1):
    rows = shards[k]
    print(f'part{k}: {len(rows)} cands, {len({c["repo"].lower() for c in rows})} repos, '
          f'A={sum(c["split"] == "A" for c in rows)} B={sum(c["split"] == "B" for c in rows)}, '
          f'src={dict(collections.Counter(c["src"] for c in rows))}')
print('pilot', len(pilot), [c['instance_id'] for c in pilot])
