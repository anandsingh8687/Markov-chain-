import json
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiListSubmissionEpisodesRequest
api = KaggleApi(); api.authenticate()
with api.build_kaggle_client() as k:
    req = ApiListSubmissionEpisodesRequest(); req.submission_id = 56560456
    resp = k.competitions.competition_api_client.list_submission_episodes(req)
eps = resp.episodes
rows = []
for e in eps:
    ags = e.agents
    me = [a for a in ags if a.submission_id == 56560456]
    if not me or e.type != 1 and str(e.type) not in ('EpisodeType.EPISODE_TYPE_PUBLIC', '1'): pass
    op = [a for a in ags if a.submission_id != 56560456]
    if not me or not op: continue
    rows.append((e.id, me[0].reward, op[0].reward, op[0].submission_id, str(e.state), str(e.type)))
json.dump(rows, open('ladder_v11.json', 'w'))
done = [r for r in rows if r[1] is not None and r[2] is not None]
w = sum(r[1] > r[2] for r in done); l = sum(r[1] < r[2] for r in done)
print('episodes', len(rows), 'scored', len(done), 'W-L', w, '-', l)
print('types', set(r[5] for r in rows))
