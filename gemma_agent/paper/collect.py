"""Collect per-task lab outcomes into paper/data/outcomes.csv (stdlib only).

Usage: python collect.py <dir with labNN{a,b}out/lab/results.jsonl subdirs> [timepred.jsonl]

The optional timepred.jsonl (python lab/timepred.py --json OUT <labNNout ...>) adds predicted_seconds: the
scorer-time model's sequential task seconds (31B constants; not calibrated for E4B rows).

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
    "lab23": ("evalset", "virtual"), "lab24": ("evalset", "virtual"), "lab28s": ("evalset", "virtual"),
}
MODEL = {"s1": "e4b", "s2": "e4b", "s3": "e4b", "s4": "e4b"}


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


# argument names of the harness tools (swegemma tools/execution.py, workspace.py, graph.py)
TOOL_ARGS = {
    "run_command": {"command"}, "read_file": {"filepath", "start_line", "end_line"},
    "edit_file": {"filepath", "old_string", "new_string", "allow_multiple"}, "write_file": {"filepath", "content"},
    "get_status": set(), "submit_patch": set(), "search_similar_code": {"query", "k"},
    "get_code_neighbors": {"node", "edge_type", "max_neighbors"}, "get_code_subgraph": {"nodes"},
}


def malformed(call):
    """A parsed tool call whose name or argument keys are not the tool's own (broken <|"|> delimiting)."""
    a = call.get("arguments") or {}
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            return True
    name = call.get("function_name")
    return name not in TOOL_ARGS or not set(a) <= TOOL_ARGS[name]


def trace_fields(path):
    """LLM-step index of the first history compaction (prompt < 0.7 x previous) and of the first edit."""
    if not path.exists():
        return {"llm_steps": "", "first_compaction_step": "", "first_edit_step": "", "traced_calls": "", "malformed_calls": ""}
    d = json.load(open(path))
    prev = comp = edit = None
    k = n_calls = n_bad = 0
    for st in d["steps"]:
        for t in st.get("tool_calls") or []:
            n_calls += 1
            n_bad += malformed(t)
        pt = (st.get("metrics") or {}).get("prompt_tokens")
        if pt:
            k += 1
            if prev and pt < 0.7 * prev and comp is None:
                comp = k
            prev = pt
        for t in st.get("tool_calls") or []:
            if t.get("function_name") in ("edit_file", "write_file") and edit is None:
                edit = k
    return {"llm_steps": k, "first_compaction_step": comp or "", "first_edit_step": edit or "",
            "traced_calls": n_calls, "malformed_calls": n_bad}


root = Path(sys.argv[1])
pred = {}
if len(sys.argv) > 2:
    for line in open(sys.argv[2]):
        p = json.loads(line)
        pred[(p["run"].removesuffix("out"), p["bundle"], p["id"], p.get("replicate", 0))] = p.get("pred_task_s", "")
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
            "predicted_seconds": pred.get((lab, r["bundle"], tid, r.get("replicate", 0)), ""),
            **trace_fields(root / f"{lab}out" / "lab" / r["bundle"] / f"r{r.get('replicate', 0)}" / "traces" / f"trace_{tid}.json"),
        })
out = HERE / "data" / "outcomes.csv"
with out.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(len(rows), "rows ->", out)
