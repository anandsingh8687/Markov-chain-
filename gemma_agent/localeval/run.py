"""Evaluate an agent bundle on local tasks: agent phase, then verification.

Usage:
  OPENROUTER_API_KEY=... python -m gemma_agent.localeval.run TASKS.jsonl \
      --bundle gemma_agent/bundle --results runs/v1 [--ids ...] [--sample N] [--jobs 4] [--gold goldcheck.jsonl]

Results (resumable): results/task_results.jsonl, patches/, traces/, summary.json.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import tools
from .runner import run_task
from .verify import resolved_given_env, verify

LOCK = threading.Lock()


def evaluate_one(task: dict, bundle: Path, results: Path, budget: tools.Budget, gold: dict) -> dict:
    work = Path(tempfile.mkdtemp(prefix=f"le_{task['instance_id']}_"))
    try:
        run = run_task(task, bundle, work / "agent", budget)
        (results / "patches" / f"{task['instance_id']}.patch").write_text(run["patch"])
        trace = run.pop("trace")
        (results / "traces" / f"{task['instance_id']}.json").write_text(json.dumps(trace, indent=1))
        if run["patch"].strip():
            v = verify(task, run["patch"], work / "verify")
        else:
            v = {"resolved": False, "error": "empty patch"}
        g = gold.get(task["instance_id"], {})
        run.update(
            resolved=v["resolved"],
            resolved_env=resolved_given_env(v, g.get("gold_failed")),
            verify_error=v.get("error", ""),
            failed_tests=v.get("failed", [])[:30],
        )
        (results / "test_outputs" / f"{task['instance_id']}.log").write_text(v.get("output", v.get("error", "")))
        run.pop("patch")
        return run
    finally:
        shutil.rmtree(work, ignore_errors=True)


def summarize(results: Path, ids: set[str]) -> dict:
    rows = [json.loads(l) for l in (results / "task_results.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["instance_id"] in ids]
    n = len(rows) or 1
    by_repo = Counter()
    ok_repo = Counter()
    for r in rows:
        repo = r["instance_id"].rsplit("_", 1)[0]
        by_repo[repo] += 1
        ok_repo[repo] += bool(r.get("resolved_env"))
    s = {
        "tasks": len(rows),
        "resolved_strict": sum(bool(r.get("resolved")) for r in rows) / n,
        "resolved": sum(bool(r.get("resolved_env")) for r in rows) / n,
        "submitted": sum(bool(r.get("submitted")) for r in rows) / n,
        "end_reasons": Counter(r["end_reason"].split(":")[0] for r in rows).most_common(),
        "by_repo": {k: f"{ok_repo[k]}/{v}" for k, v in by_repo.items()},
        "avg_tool_calls": sum(r.get("tool_calls", 0) for r in rows) / n,
        "avg_seconds": sum(r.get("seconds", 0) for r in rows) / n,
        "max_prompt_tokens": max((r.get("usage", {}).get("max_prompt", 0) for r in rows), default=0),
        "total_tokens": sum(r.get("usage", {}).get("prompt", 0) + r.get("usage", {}).get("completion", 0)
                            for r in rows),
    }
    (results / "summary.json").write_text(json.dumps(s, indent=1))
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks")
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--gold", type=Path)
    ap.add_argument("--time-minutes", type=float, default=60.0)
    ap.add_argument("--tool-calls", type=int)
    a = ap.parse_args()

    tasks = [json.loads(l) for l in open(a.tasks)]
    gold = {}
    if a.gold and a.gold.exists():
        gold = {g["instance_id"]: g for g in map(json.loads, a.gold.read_text().splitlines())}
        tasks = [t for t in tasks if gold.get(t["instance_id"], {}).get("valid")]
    if a.ids:
        tasks = [t for t in tasks if t["instance_id"] in a.ids]
    if a.sample:
        tasks = random.Random(a.seed).sample(tasks, min(a.sample, len(tasks)))
    for sub in ("patches", "traces", "test_outputs"):
        (a.results / sub).mkdir(parents=True, exist_ok=True)
    out = a.results / "task_results.jsonl"
    done = {json.loads(l)["instance_id"] for l in out.read_text().splitlines()} if out.exists() else set()
    todo = [t for t in tasks if t["instance_id"] not in done]
    budget = tools.Budget(time_minutes=a.time_minutes, tool_calls=a.tool_calls)
    print(f"{len(tasks)} tasks, {len(todo)} to run", flush=True)
    with ThreadPoolExecutor(a.jobs) as pool:
        futs = {pool.submit(evaluate_one, t, a.bundle, a.results, budget, gold): t for t in todo}
        for f in as_completed(futs):
            t = futs[f]
            try:
                r = f.result()
            except Exception as exc:  # noqa: BLE001
                r = {"instance_id": t["instance_id"], "end_reason": f"harness_crash: {exc}"[:1000],
                     "resolved": False, "resolved_env": False}
            with LOCK, open(out, "a") as fh:
                fh.write(json.dumps(r) + "\n")
            print(f"{r['instance_id']:28} {'PASS' if r.get('resolved_env') else 'fail'}  "
                  f"{r['end_reason'][:60]:60} calls={r.get('tool_calls')} {r.get('seconds')}s", flush=True)
    print(json.dumps(summarize(a.results, {t["instance_id"] for t in tasks}), indent=1))


if __name__ == "__main__":
    main()
