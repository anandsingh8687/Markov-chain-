#!/usr/bin/env python3
"""Refresh benchmark/ghosts from this account's own ladder episodes.

Needs KAGGLE_API_TOKEN in the environment (a KGAT_ token; the legacy
KAGGLE_USERNAME/KAGGLE_KEY pair does not authenticate it). Nothing is written
to disk except the compact ghost file: a replay is ~32 MB, and only the
opponent's action tape, the seed, our seat and the final banks are kept.

    KAGGLE_API_TOKEN=... python tools/fetch_ghosts.py --submission 56398661 \\
        --label v8 --team "Anand Singh" --only-lost

The API throttles (HTTP 429) above roughly one replay a second, so this uses two
threads and backs off.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

DATA = os.path.join("benchmark", "ghosts", "ladder_ghosts.json.gz")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", type=int, required=True)
    ap.add_argument("--label", required=True, help="version label stored with each ghost")
    ap.add_argument("--team", required=True, help="our team name as it appears in replays")
    ap.add_argument("--only-lost", action="store_true")
    ap.add_argument("--data", default=DATA)
    args = ap.parse_args()

    from kaggle.api.kaggle_api_extended import KaggleApi
    from kagglesdk.competitions.types.competition_api_service import ApiGetEpisodeReplayRequest
    api = KaggleApi()
    api.authenticate()

    have = []
    if os.path.exists(args.data):
        with gzip.open(args.data, "rt") as fh:
            have = json.load(fh)
    seen = {g["ep"] for g in have}
    eps = [getattr(e, "id", None) for e in api.competition_list_episodes(args.submission)]
    todo = [e for e in eps if e and e not in seen]
    print("episodes: {} listed, {} new".format(len(eps), len(todo)))

    def fetch(ep):
        for attempt in range(10):
            try:
                with api.build_kaggle_client() as k:
                    req = ApiGetEpisodeReplayRequest()
                    req.episode_id = ep
                    resp = k.competitions.competition_api_client.get_episode_replay(req)
                    d = json.loads(b"".join(resp.iter_content(1 << 20)))
                time.sleep(1.0)
                break
            except Exception as e:  # noqa: BLE001
                if "429" in str(e):
                    time.sleep(10 * (attempt + 1))
                    continue
                print("  {}: {}".format(ep, str(e)[:80]))
                return None
        else:
            return None
        names = d["info"]["TeamNames"]
        if names.count(args.team) != 1 or d.get("statuses") != ["DONE", "DONE"]:
            return None
        me = names.index(args.team)
        bank = [d["rewards"][me], d["rewards"][1 - me]]
        if args.only_lost and bank[0] >= bank[1]:
            return None
        return {"ep": ep, "seed": d["info"].get("seed"), "seat": me, "version": args.label,
                "opponent": names[1 - me], "bank": bank,
                "actions": [d["steps"][t][1 - me]["action"] for t in range(len(d["steps"]))]}

    with ThreadPoolExecutor(max_workers=2) as ex:
        new = [g for g in ex.map(fetch, todo) if g]
    with gzip.open(args.data, "wt", compresslevel=9) as fh:
        json.dump(have + new, fh, separators=(",", ":"))
    print("added {} ghosts; {} total".format(len(new), len(have) + len(new)))


if __name__ == "__main__":
    main()
