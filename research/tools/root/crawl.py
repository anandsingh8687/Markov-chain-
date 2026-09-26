import json, time, collections
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiGetLeaderboardRequest
api = KaggleApi(); api.authenticate()
with api.build_kaggle_client() as k:
    req = ApiGetLeaderboardRequest(); req.competition_name = 'kaggriculture'; req.page_size = 30
    lb = [s.to_dict() for s in k.competitions.competition_api_client.get_leaderboard(req).submissions]
TOP = {d['teamName']: float(d['score']) for d in lb[:30]}
rank = {d['teamName']: i + 1 for i, d in enumerate(lb[:30])}
print('top30 loaded', len(TOP))
sub_team = {}; sub_eps = {}; seen = set()
frontier = [56503612]
found = collections.defaultdict(set)
calls = 0
def eps_of(sid):
    global calls
    for attempt in range(6):
        try:
            calls += 1
            return api.competition_list_episodes(sid)
        except Exception as e:
            if '429' in str(e): time.sleep(10 * (attempt + 1)); continue
            return []
    return []
# priority: prefer submissions of teams in top list, then others (BFS)
import heapq
pq = [(0, 56503612)]
while pq and calls < 250:
    pr, sid = heapq.heappop(pq)
    if sid in seen: continue
    seen.add(sid)
    E = eps_of(sid); time.sleep(0.5)
    sub_eps[sid] = []
    for e in E:
        A = [a.to_dict() for a in e.agents]
        sub_eps[sid].append({'ep': e.id, 't': str(e.create_time), 'agents': A})
        for a in A:
            t, s = a['teamName'], a['submissionId']
            sub_team[s] = t
            if t in TOP: found[t].add(s)
            if s not in seen:
                heapq.heappush(pq, (-(TOP.get(t, 0)), s))
    top10 = [t for t, r in rank.items() if r <= 10]
    have = [t for t in top10 if any(s in seen for s in found[t])]
    if calls % 10 == 0: print('calls', calls, 'top10 teams with crawled subs', len(have), flush=True)
    if len(have) == 10: break
json.dump({'lb': lb, 'sub_team': {str(k): v for k, v in sub_team.items()}, 'found': {k: sorted(v) for k, v in found.items()},
           'sub_eps': {str(k): v for k, v in sub_eps.items()}}, open('crawl.json', 'w'))
for t in sorted(found, key=lambda t: rank[t]):
    print(rank[t], t, TOP[t], sorted(found[t]), [len(sub_eps.get(s, [])) for s in sorted(found[t])])
