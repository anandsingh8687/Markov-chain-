"""Collect per-task lab outcomes into paper/data/outcomes.csv (stdlib only).

Usage: python collect.py <dir with labNN{a,b}out/lab/results.jsonl subdirs>

One row per (lab, bundle, task). Labs 17-19 ran on the older public-repo dev tasks; labs 20-24 ran on
eval set v1 (split from evalset/v1/ids_A.txt, ids_B.txt). In lab 23 the vLLM server hung at 12:33 UTC
(tool-parser infinite loop, see lab/parser_hang); runs that started after it made no model call and
are marked outcome=server_hang and excluded from every comparison.
"""
import csv
import glob
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE.parent / "evalset" / "v1"
split = {}
for s in "AB":
    for tid in (EV / f"ids_{s}.txt").read_text().split():
        split[tid] = s
interface = set((EV / "ids_interface.txt").read_text().split())

LABS = {  # lab -> (task set, clock)
    "lab17a": ("dev", "real"), "lab17b": ("dev", "real"), "lab19": ("dev", "real"),
    "lab18a": ("dev", "virtual"), "lab18b": ("dev", "virtual"),
    "lab20a": ("evalset", "virtual"), "lab20b": ("evalset", "virtual"), "lab21": ("evalset", "virtual"),
    "lab22a": ("evalset", "virtual"), "lab22b": ("evalset", "virtual"),
    "lab23": ("evalset", "virtual"), "lab24": ("evalset", "virtual"),
}
MODEL = {"s1": "e4b", "s2": "e4b"}


def outcome(r):
    if r.get("resolved_kaggle_env"):
        return "solved"
    err = r.get("error") or ""
    if "session timeout" in err:
        if r.get("llm_calls", 0) == 0:
            return "server_hang"
        return "timeout"
    if "turns budget" in err:
        return "turn_limit"
    if (r.get("patch_chars") or 0) == 0:
        return "empty"
    return "wrong"


root = Path(sys.argv[1])
rows = []
for lab, (taskset, clock) in LABS.items():
    f = root / f"{lab}out" / "lab" / "results.jsonl"
    if not f.exists():
        print("missing", f)
        continue
    for line in f.open():
        r = json.loads(line)
        tid = r["id"]
        rows.append({
            "lab": lab, "task_set": taskset, "clock": clock,
            "split": split.get(tid, "") if taskset == "evalset" else "",
            "interface_task": int(tid in interface),
            "bundle": r["bundle"], "model": MODEL.get(r["bundle"], "31b"), "task_id": tid,
            "resolved": int(bool(r.get("resolved_kaggle_env"))), "outcome": outcome(r),
            "tool_calls": r.get("tool_calls", ""), "llm_calls": r.get("llm_calls", ""),
            "completion_tokens": r.get("vc_completion_tokens", ""),
            "virtual_seconds": r.get("virtual_seconds", ""),
            "real_seconds": r.get("task_seconds", "") if clock == "real" else r.get("real_agent_seconds", ""),
            "patch_chars": r.get("patch_chars", 0),
        })
out = HERE / "data" / "outcomes.csv"
with out.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(len(rows), "rows ->", out)
