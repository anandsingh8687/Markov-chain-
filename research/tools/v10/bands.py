import json, csv, glob, collections
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiListSubmissionEpisodesRequest
api = KaggleApi(); api.authenticate()
lb = {}
f = glob.glob('lb2/*.csv')[0]
for i, r in enumerate(csv.DictReader(open(f, encoding='utf-8-sig'))): lb[int(r['TeamId'])] = (i + 1, float(r['Score']), r['TeamName'])
rows = []
for sub in (56540053,):
    with api.build_kaggle_client() as k:
        req = ApiListSubmissionEpisodesRequest(); req.submission_id = sub
        eps = k.competitions.competition_api_client.list_submission_episodes(req).episodes
    for e in eps:
        me = [a for a in e.agents if a.submission_id == sub]; op = [a for a in e.agents if a.submission_id != sub]
        if not me or not op or me[0].reward is None: continue
        rank, score, name = lb.get(op[0].team_id, (None, None, op[0].team_name))
        rows.append({'ep': e.id, 'm': me[0].reward - op[0].reward, 'opp': name, 'rank': rank, 'score': score})
json.dump(rows, open('v10_opp_bands.json', 'w'))
B = collections.defaultdict(list)
for r in rows:
    s = r['score']; b = 'unknown' if s is None else ('>=2700' if s >= 2700 else '2600-2700' if s >= 2600 else '2500-2600' if s >= 2500 else '2400-2500' if s >= 2400 else '<2400')
    B[b].append(r['m'])
for b in ('>=2700', '2600-2700', '2500-2600', '2400-2500', '<2400', 'unknown'):
    L = B.get(b, [])
    if L: print(f"{b:10s} games {len(L):3d}  W-L {sum(x>0 for x in L)}-{sum(x<0 for x in L)}  mean {sum(L)/len(L):+7.0f}  big losses(<-2000) {sum(x<-2000 for x in L)}")
