import json, sys
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiListSubmissionEpisodesRequest
api = KaggleApi(); api.authenticate()
for sid, name in ((56599604, 'v16'), (56605749, 'v17'), (56586316, 'v14')):
    with api.build_kaggle_client() as k:
        req = ApiListSubmissionEpisodesRequest(); req.submission_id = sid
        resp = k.competitions.competition_api_client.list_submission_episodes(req)
    rows = []
    for e in resp.episodes:
        me = [a for a in e.agents if a.submission_id == sid]; op = [a for a in e.agents if a.submission_id != sid]
        if not me or not op or me[0].reward is None or op[0].reward is None: continue
        rows.append((e.id, me[0].reward, op[0].reward, op[0].submission_id))
    json.dump(rows, open(f'ladder_{name}.json', 'w'))
    w = sum(r[1] > r[2] for r in rows); l = sum(r[1] < r[2] for r in rows)
    print(name, 'games', len(rows), 'W-L', w, l, 'mean margin', round(sum(r[1]-r[2] for r in rows)/max(1,len(rows))))
subs = api.competition_submissions('kaggriculture')
for s in subs[:8]:
    print(getattr(s, 'ref', None), getattr(s, 'description', '')[:40], getattr(s, 'public_score', None), getattr(s, 'status', None))
