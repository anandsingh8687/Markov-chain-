import json, csv, glob
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiListSubmissionEpisodesRequest
api = KaggleApi(); api.authenticate()
lb = {}
f = sorted(glob.glob('lb4/*.csv'))[-1]
for i, r in enumerate(csv.DictReader(open(f, encoding='utf-8-sig'))): lb[int(r['TeamId'])] = (i + 1, float(r['Score']), r['TeamName'])
out = {}
for name, sid in (('v18a', 56618382), ('v18c', 56618384)):
    with api.build_kaggle_client() as k:
        req = ApiListSubmissionEpisodesRequest(); req.submission_id = sid
        eps = k.competitions.competition_api_client.list_submission_episodes(req).episodes
    rows = []
    for e in eps:
        me = [a for a in e.agents if a.submission_id == sid]; op = [a for a in e.agents if a.submission_id != sid]
        if not me or not op or me[0].reward is None or op[0].reward is None: continue
        rank, score, tname = lb.get(op[0].team_id, (None, None, op[0].team_name))
        rows.append({'ep': e.id, 'm': me[0].reward - op[0].reward, 'me': me[0].reward, 'opr': op[0].reward, 'opp': tname, 'score': score, 'self': op[0].submission_id in (56618382, 56618384)})
    out[name] = rows
    print(name, len(rows), 'W-L', sum(r['m'] > 0 for r in rows), sum(r['m'] < 0 for r in rows))
    for r in sorted(rows, key=lambda r: r['m']):
        if r['m'] < 0: print('   LOSS', r['ep'], (r['opp'] or '')[:22], r['score'], round(r['m']), round(r['me']), round(r['opr']), 'SELF' if r['self'] else '')
json.dump(out, open('v18live.json', 'w'))
for s in api.competition_submissions('kaggriculture')[:2]: print(s.ref, s.public_score)
