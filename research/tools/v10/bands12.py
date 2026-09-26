import json, csv, glob, collections, sys
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiListSubmissionEpisodesRequest
api = KaggleApi(); api.authenticate()
lb = {}
f = sorted(glob.glob('lb4/*.csv'))[-1]
for i, r in enumerate(csv.DictReader(open(f, encoding='utf-8-sig'))): lb[int(r['TeamId'])] = (i + 1, float(r['Score']), r['TeamName'])
SUBS = {'v12': 56575662, 'v11': 56560456, 'v10': 56540053}
out = {}
for name, sub in SUBS.items():
    with api.build_kaggle_client() as k:
        req = ApiListSubmissionEpisodesRequest(); req.submission_id = sub
        eps = k.competitions.competition_api_client.list_submission_episodes(req).episodes
    rows = []
    for e in eps:
        me = [a for a in e.agents if a.submission_id == sub]; op = [a for a in e.agents if a.submission_id != sub]
        if not me or not op or me[0].reward is None or op[0].reward is None: continue
        rank, score, tname = lb.get(op[0].team_id, (None, None, op[0].team_name))
        rows.append({'ep': e.id, 'm': me[0].reward - op[0].reward, 'opp': tname, 'rank': rank, 'score': score,
                     'end': str(getattr(e, 'end_time', '') or getattr(e, 'create_time', ''))})
    out[name] = rows
json.dump(out, open('bands12.json', 'w'))
for name, rows in out.items():
    B = collections.defaultdict(list)
    for r in rows:
        s = r['score']; b = 'unknown' if s is None else ('>=2700' if s >= 2700 else '2600-2700' if s >= 2600 else '2500-2600' if s >= 2500 else '2400-2500' if s >= 2400 else '<2400')
        B[b].append(r['m'])
    print(name, 'games', len(rows), 'W-L', sum(r['m'] > 0 for r in rows), '-', sum(r['m'] < 0 for r in rows))
    for b in ('>=2700', '2600-2700', '2500-2600', '2400-2500', '<2400', 'unknown'):
        L = B.get(b, [])
        if L: print(f"   {b:10s} games {len(L):3d}  W-L {sum(x>0 for x in L)}-{sum(x<0 for x in L)}  mean {sum(L)/len(L):+7.0f}  close losses(>-1000) {sum(-1000<x<0 for x in L)}  big losses(<-3000) {sum(x<-3000 for x in L)}")
