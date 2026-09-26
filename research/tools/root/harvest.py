"""Fetch the result header of every ladder episode for every submission.

Replays are ~32 MB, but keys are alphabetical, so info/rewards/statuses precede
the huge `steps` array. Stream until '"steps":' and stop."""
import json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from kaggle.api.kaggle_api_extended import KaggleApi
from kagglesdk.competitions.types.competition_api_service import ApiGetEpisodeReplayRequest
OUT = sys.argv[1]
SUBS = {"v3": 56327971, "v4": 56337503, "v5": 56352174, "v6": 56369266,
        "v7": 56398661, "v12": 56317258, "v16": 56321861}
api = KaggleApi(); api.authenticate()
lock = threading.Lock()

def header(ep):
    with api.build_kaggle_client() as k:
        req = ApiGetEpisodeReplayRequest(); req.episode_id = ep
        resp = k.competitions.competition_api_client.get_episode_replay(req)
        buf = b""
        for chunk in resp.iter_content(65536):
            buf += chunk
            i = buf.find(b'"steps"')
            if i >= 0:
                buf = buf[:i]; break
            if len(buf) > 4_000_000: break
        try: resp.close()
        except Exception: pass
    txt = buf.decode("utf-8", "replace").rstrip().rstrip(",") + "}"
    d = json.loads(txt)
    return {"names": d["info"]["TeamNames"], "seed": d["info"].get("seed"),
            "r": d.get("rewards"), "st": d.get("statuses")}

def job(args):
    import time
    ver, ep = args
    h = None
    for attempt in range(8):
        try:
            h = header(ep); h.update({"ver": ver, "ep": ep}); break
        except Exception as e:
            if "429" in str(e):
                time.sleep(5 * (attempt + 1)); continue
            h = {"ver": ver, "ep": ep, "err": str(e)[:100]}; break
    if h is None:
        return None                      # still throttled: leave for a later pass
    with lock, open(OUT, "a") as fh:
        fh.write(json.dumps(h) + "\n")
    time.sleep(0.4)
    return h

todo = []
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        try: done.add(json.loads(l)["ep"])
        except Exception: pass
for ver, sid in SUBS.items():
    eps = api.competition_list_episodes(sid)
    for e in eps:
        eid = getattr(e, "id", None) or getattr(e, "_id", None)
        if eid and eid not in done: todo.append((ver, eid))
print("episodes to fetch:", len(todo), flush=True)
with ThreadPoolExecutor(max_workers=2) as ex:
    for i, _ in enumerate(ex.map(job, todo)):
        if i % 100 == 0: print("fetched", i, flush=True)
print("done", flush=True)
