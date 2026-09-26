"""Download full replays for listed episodes and keep only the compact ghost (actions + seed)."""
import json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiGetEpisodeReplayRequest
from mkghost import compact
api = KaggleApi(); api.authenticate()
EPS = [int(x) for x in open(sys.argv[1]).read().split()]
def fetch(ep):
    if os.path.exists(f"ghosts/{ep}.json"): return "have"
    for attempt in range(10):
        try:
            with api.build_kaggle_client() as k:
                req = ApiGetEpisodeReplayRequest(); req.episode_id = ep
                resp = k.competitions.competition_api_client.get_episode_replay(req)
                buf = b"".join(resp.iter_content(1 << 20))
            d = json.loads(buf)
            json.dump(compact(d, ep), open(f"ghosts/{ep}.json.tmp", "w"), separators=(",", ":"))
            os.replace(f"ghosts/{ep}.json.tmp", f"ghosts/{ep}.json")
            time.sleep(1.0); return "ok"
        except Exception as e:
            if "429" in str(e): time.sleep(10 * (attempt + 1)); continue
            return "err " + str(e)[:80]
    return "throttled"
with ThreadPoolExecutor(max_workers=2) as ex:
    for i, (ep, s) in enumerate(zip(EPS, ex.map(fetch, EPS))):
        print(i, ep, s, flush=True)
