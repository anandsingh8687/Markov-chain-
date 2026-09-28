"""Crawl recent episodes of current 2600+ submissions (BFS from our opponents)."""
import json, time, collections, heapq
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiGetLeaderboardRequest
api = KaggleApi(); api.authenticate()
with api.build_kaggle_client() as k:
    req = ApiGetLeaderboardRequest(); req.competition_name = 'kaggriculture'; req.page_size = 200
    lb = [s.to_dict() for s in k.competitions.competition_api_client.get_leaderboard(req).submissions]
SC = {d['teamName']: float(d['score']) for d in lb}
print('leaderboard rows', len(lb), 'cut 2600 count', sum(v >= 2600 for v in SC.values()), flush=True)
seeds = set()
for n, rows in json.load(open('bands12.json')).items():
    pass
# seed submissions: opponents' submission ids from our recent episodes
def eps_of(sid):
    for attempt in range(6):
        try:
            return api.competition_list_episodes(sid)
        except Exception as e:
            if '429' in str(e): time.sleep(10 * (attempt + 1)); continue
            return []
    return []
start = [56599604, 56605749, 56618382, 56618384, 56586316]
seen = set(); pq = [(0, s) for s in start]; calls = 0
EPS = {}; SUBTEAM = {}; SUBSCORE = collections.Counter()
while pq and calls < 260:
    pr, sid = heapq.heappop(pq)
    if sid in seen: continue
    seen.add(sid); calls += 1
    for e in eps_of(sid):
        A = [a.to_dict() for a in e.agents]
        if len(A) != 2: continue
        rec = {'ep': e.id, 't': str(e.create_time), 'agents': [(a.get('teamName'), a.get('submissionId'), a.get('reward')) for a in A]}
        EPS[e.id] = rec
        for t, s, r in rec['agents']:
            SUBTEAM[s] = t
            if s not in seen and SC.get(t, 0) >= 2600:
                heapq.heappush(pq, (-SC.get(t, 0), s))
    time.sleep(0.4)
    if calls % 20 == 0: print('calls', calls, 'episodes', len(EPS), 'queue', len(pq), flush=True)
json.dump({'SC': SC, 'EPS': list(EPS.values()), 'SUBTEAM': {str(k): v for k, v in SUBTEAM.items()}}, open('crawl26.json', 'w'))
top = [e for e in EPS.values() if any(SC.get(t, 0) >= 2600 for t, s, r in e['agents']) and all(r is not None for t, s, r in e['agents'])]
print('episodes with a 2600+ side', len(top))
