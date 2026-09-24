"""Check that local verification reproduces the harness: gold patch passes, empty patch fails.

Usage: python -m gemma_agent.localeval.goldcheck TASKS.jsonl [--ids a b] [--jobs N] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .verify import resolved_given_env, verify


def check(task: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="gold_") as d:
        gold = verify(task, task["patch"], Path(d) / "gold")
        empty = verify(task, "", Path(d) / "empty")
    gold_failed = gold.get("failed", []) if gold.get("exit_code") in (0, 1) else None
    return {
        "instance_id": task["instance_id"],
        "gold": gold["resolved"],
        "gold_failed": gold_failed,
        "empty": resolved_given_env(empty, gold_failed),
        "valid": gold_failed is not None and not gold.get("error") and not resolved_given_env(empty, gold_failed),
        "gold_error": gold.get("error") or ("" if gold["resolved"] else gold.get("output", "")[-1500:]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", default="goldcheck.jsonl")
    a = ap.parse_args()
    tasks = [json.loads(l) for l in open(a.tasks)]
    if a.ids:
        tasks = [t for t in tasks if t["instance_id"] in a.ids]
    done = set()
    out = Path(a.out)
    if out.exists():
        done = {json.loads(l)["instance_id"] for l in out.read_text().splitlines()}
    tasks = [t for t in tasks if t["instance_id"] not in done]
    with ThreadPoolExecutor(a.jobs) as pool, open(out, "a") as fh:
        futs = {pool.submit(check, t): t for t in tasks}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as exc:  # noqa: BLE001
                r = {"instance_id": futs[f]["instance_id"], "valid": False, "gold_error": f"crash: {exc}"[-1500:]}
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            print(r["instance_id"], "valid" if r["valid"] else f"INVALID {r.get('gold_error', '')[-200:]!r}", flush=True)


if __name__ == "__main__":
    main()
