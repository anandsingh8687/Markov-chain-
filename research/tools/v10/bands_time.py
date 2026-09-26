import json, csv, glob, collections, datetime
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiListSubmissionEpisodesRequest
api = KaggleApi(); api.authenticate()
lb = {}
for i, r in enumerate(csv.DictReader(open(glob.glob('lb3/*.csv')[0], encoding='utf-8-sig'))): lb[int(r['TeamId'])] = float(r['Score'])
out = {}
for name, sub in (('v10', 56540053), ('v11', 56560456)):
    with api.build_kaggle_client() as k:
        req = ApiListSubmissionEpisodesRequest(); req.submission_id = sub
        eps = k.competitions.competition_api_client.list_submission_episodes(req).episodes
    rows = []
    for e in eps:
        me = [a for a in e.agents if a.submission_id == sub]; op = [a for a in e.agents if a.submission_id != sub]
        if not me or not op or me[0].reward is None: continue
        rows.append((e.create_time, me[0].reward - op[0].reward, lb.get(op[0].team_id)))
    out[name] = rows
t0 = min(r[0] for r in out['v11'])
for name, rows in out.items():
    recent = [r for r in rows if r[0] >= t0]
    print(f"{name}: games since v11 started {len(recent)}")
    for lo, hi in ((2500, 9999), (2400, 2500), (2300, 2400), (0, 2300)):
        L = [m for t, m, s in recent if s is not None and lo <= s < hi]
        if L: print(f"   opp {lo}-{hi}: {sum(x>0 for x in L)}-{sum(x<0 for x in L)}  mean {sum(L)/len(L):+.0f}")
