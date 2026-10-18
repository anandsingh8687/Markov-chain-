"""CPU self-test of the lab tooling (make_lab.py, labworker.py, timepred.py, stats.py). No GPU, no model.

    python -I gemma_agent/lab/selftest.py --data EVALSET_DATA --competition COMPDATA --work SCRATCH_DIR \
        [--py313 /usr/bin/python3.13] [--image COMPDATA/image313] [--ids ID ID] [--skip-e2e]

Runs with the official harness wheels importable (e.g. the wheelhouse venv's python):
  1. unit checks: data-dir resolution, the three wheel layouts and their wheel-set keys, job extras, patch
     file parsing, exact McNemar, paired bootstrap, timepred trace parsing on synthetic traces (prompt-drop
     compaction, agent_tool container, two overlapping ParallelAgent branches, 8-minute cap);
  2. make_lab kernels: new-mode and --phase2-only kernels parse, carry the options, CPU metadata;
  3. phase 2 end to end (labworker.run_pool, docker-like sandbox, per-task wheel sets with separate TMPDIRs):
     the gold patch passes and the empty patch fails on each --ids task; the TMPDIRs are removed afterwards;
  4. agent end to end against a scripted fake OpenAI endpoint whose latency follows timepred's own step model:
     a single agent (real and virtual clock), a lead + agent_tool solver, and a lead + agent_tool ParallelAgent
     with two workers that leave /tmp/a.diff and /tmp/b.diff (graded via extra_patches). Checks: solved,
     trace call counts = harness llm_calls, sub-agent calls visible in the trace with a container parent,
     the two workers detected as one parallel group, timepred within 8% of the measured agent seconds on the
     real-clock runs, stats.py reads the results (two-attempt A/B/oracle/picked).
Exit code 0 when every check passes. Temporary files live under --work and are deleted at the end
(--keep to keep them).
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import labworker  # noqa: E402
import stats  # noqa: E402
import timepred  # noqa: E402

FAILS: list = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


# ------------------------------------------------------------------ 1. unit checks

def synth_trace(path: Path, steps: list) -> None:
    path.write_text(json.dumps({"schema_version": "ATIF-v1.7", "steps": steps, "final_metrics": {}}))


def step(author, ts, ct, pt, tool=None, t_obs=None):
    s = {"source": "agent", "metrics": {"prompt_tokens": pt, "completion_tokens": ct},
         "extra": {"event_type": "thinking", "timestamp": ts, "author": author}}
    if tool:
        s["tool_calls"] = [{"function_name": tool, "extra": {"timestamp": ts}}]
        s["observation"] = {"content": "", "extra": {"timestamp": t_obs if t_obs is not None else ts + 0.1}}
    return s


def unit(work: Path) -> None:
    root = work / "u"
    (root / "inp" / "notebooks" / "me" / "evalset-merge" / "evalset").mkdir(parents=True)
    d = root / "inp" / "notebooks" / "me" / "evalset-merge" / "evalset"
    (d / "tasks.jsonl").write_text("{}\n")
    check(labworker.resolve_data_dir(str(d)) == d, "resolve_data_dir: plain path")
    check(labworker.resolve_data_dir(str(root / "inp" / "*" / "*" / "evalset-merge" / "evalset")) == d, "resolve_data_dir: glob")
    check(labworker.resolve_data_dir("evalset-merge/evalset", roots=(str(root / "inp"),)) == d,
          "resolve_data_dir: name searched under the input root")
    check(labworker.resolve_data_dir(None, d) == d, "resolve_data_dir: default")
    # wheel layouts
    for name in ("a-1.0-py3-none-any.whl", "b-2.0-py3-none-any.whl", "c-3.0-py3-none-any.whl"):
        (d / "wheels_pool").mkdir(exist_ok=True)
        (d / "wheels_pool" / name).write_bytes(b"x")
    (d / "wheels").mkdir()
    (d / "wheels" / "z-1.0-py3-none-any.whl").write_bytes(b"x")
    (d / "wheels_by_task" / "t1").mkdir(parents=True)
    (d / "wheels_by_task" / "t1" / "a-1.0-py3-none-any.whl").write_bytes(b"x")
    (d / "wheels_manifest").mkdir()
    (d / "wheels_manifest" / "t2.txt").write_text("a-1.0-py3-none-any.whl\nb-2.0-py3-none-any.whl\n")
    (d / "wheels_manifest" / "t3.txt").write_text("a-1.0-py3-none-any.whl\nc-3.0-py3-none-any.whl\n")
    w1, p1 = labworker.resolve_task_wheels(d, "t1", root / "links")
    w2, p2 = labworker.resolve_task_wheels(d, "t2", root / "links")
    w3, p3 = labworker.resolve_task_wheels(d, "t3", root / "links")
    w4, p4 = labworker.resolve_task_wheels(d, "t4", root / "links")
    check(p1 and w1 == d / "wheels_by_task" / "t1", "wheels_by_task layout")
    check(p2 and sorted(x.name for x in w2.glob("*.whl")) == ["a-1.0-py3-none-any.whl", "b-2.0-py3-none-any.whl"]
          and all(x.is_symlink() for x in w2.glob("*.whl")), "wheels_manifest + wheels_pool -> symlink dir")
    check(not p4 and w4 == d / "wheels", "shared wheels fallback")
    keys = {labworker.wheel_set_key(w) for w in (w1, w2, w3)}
    check(len(keys) == 3, "different wheel sets -> different TMPDIR keys")
    ex = labworker.job_extras(d, "t2", {"per_task_wheels": True, "work_root": str(root / "w")}, {})
    check(ex["tmpdir"].endswith(labworker.wheel_set_key(w2)) and ex["cleanup_tmpdir"]
          and ex["wheels_dir"] == str(root / "w" / "wheels" / "t2"),
          "job_extras: per-task wheels -> own TMPDIR, cleanup on")
    ex4 = labworker.job_extras(d, "t4", {"per_task_wheels": True, "work_root": str(root / "w")}, {})
    check("tmpdir" not in ex4, "job_extras: shared wheels -> no TMPDIR (harness default)")
    ex_off = labworker.job_extras(d, "t2", {"per_task_wheels": False, "work_root": str(root / "w")}, {})
    check("tmpdir" not in ex_off, "job_extras: --no-per-task-wheels")
    # patch files, stats
    pt = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n"
    check(labworker.patch_files(pt) == ["x.py"] and stats.timepred_patch_files("--- a/y.py\n+++ b/y.py\n") == ["y.py"],
          "patch file parsing (git and plain unified headers)")
    check(abs(stats.mcnemar_exact(5, 3) - 0.7265625) < 1e-9 and stats.mcnemar_exact(0, 0) == 1.0
          and abs(stats.mcnemar_exact(0, 6) - 0.03125) < 1e-9, "exact McNemar")
    arm_a = {f"t{i}": [i < 10] for i in range(20)}
    arm_b = {f"t{i}": [i < 5] for i in range(20)}
    res = stats.paired(arm_a, arm_b, 2000, 1)
    check(res["diff_tasks"] == 5 and res["a_only"] == 5 and res["b_only"] == 0 and res["ci95_tasks"][0] > 0,
          "paired bootstrap: +5 of 20, CI above 0")
    check(stats.is_test_path("tests/test_a.py") and stats.is_test_path("pkg/conftest.py") and not stats.is_test_path("pkg/a.py"),
          "test-file filter for the gold metric")
    # timepred on synthetic traces
    c = timepred.CONSTS
    t0 = 1000.0
    st = [{"source": "user", "extra": {"event_type": "task_prompt", "timestamp": t0}},
          step("fixer", t0 + 2, 100, 4000, "run_command", t0 + 3), step("fixer", t0 + 6, 50, 9000, "run_command", t0 + 7),
          step("fixer", t0 + 40, 50, 5000, "run_command", t0 + 41)]
    synth_trace(root / "t_comp.json", st)
    tr = timepred.parse_trace(str(root / "t_comp.json"))
    check([d_["comp"] for d_ in tr["calls"]] == [False, False, True] and tr["calls"][1]["unc"] == 5000,
          "timepred: compaction = prompt drop below 0.7x; uncached = prompt growth")
    p = timepred.predict_trace(tr, c, None)
    exp = 3 * c["per_call"] + c["per_token"] * 200 + c["per_kuncached"] * 9.0 + c["per_compaction"] + 3 * 1.0
    check(abs(p["pred_agent_s"] - round(exp + c["per_task"], 1)) < 0.11, "timepred: serial step sum")
    # agent_tool: lead calls solver (container 1..20), solver steps inside
    st = [{"source": "user", "extra": {"event_type": "task_prompt", "timestamp": t0}},
          step("lead", t0 + 1, 20, 3000, "solver", t0 + 20),
          step("solver", t0 + 3, 100, 2000, "run_command", t0 + 4), step("solver", t0 + 8, 100, 2500, "edit_file", t0 + 9),
          step("lead", t0 + 21, 10, 3500, "submit_patch", t0 + 21.5)]
    synth_trace(root / "t_at.json", st)
    tr = timepred.parse_trace(str(root / "t_at.json"))
    calls = tr["calls"]
    check(calls[0]["tools"][0]["container"] and calls[1]["parent"] is not None and calls[0]["tool_s"] == 0.0
          and abs(sum(d_["tool_s"] for d_ in calls) - 2.5) < 1e-6,
          "timepred: agent_tool call is a container (its span is not tool time); inner calls have a parent")
    check(calls[1]["unc"] == 2000 and calls[3]["unc"] == 500, "timepred: per-stream prompt growth across a container")
    # two overlapping workers inside a container
    st = [{"source": "user", "extra": {"event_type": "task_prompt", "timestamp": t0}},
          step("lead", t0 + 1, 20, 3000, "attempts", t0 + 60)]
    for k in range(5):
        st.append(step("wa", t0 + 2 + 10 * k, 200, 2000 + 100 * k, "run_command", t0 + 3 + 10 * k))
        st.append(step("wb", t0 + 4 + 10 * k, 100, 2000 + 100 * k, "run_command", t0 + 5 + 10 * k))
    st.append(step("lead", t0 + 61, 10, 4000, "submit_patch", t0 + 61.2))
    synth_trace(root / "t_par.json", st)
    tr = timepred.parse_trace(str(root / "t_par.json"))
    p = timepred.predict_trace(tr, c, None)
    check(sorted(map(sorted, p["parallel_groups"])) == [["wa", "wb"]], "timepred: overlapping workers = one parallel group")
    wa = sum(timepred.call_cost(d_, c) for d_ in tr["calls"] if d_["author"] == "wa")
    lead = sum(timepred.call_cost(d_, c) for d_ in tr["calls"] if d_["author"] == "lead")
    tools = sum(d_["tool_s"] for d_ in tr["calls"])
    check(abs(p["pred_agent_s"] - (lead + wa * timepred.PARALLEL_SLOWDOWN[2] + tools + c["per_task"])) < 0.2,
          "timepred: parallel group costs max(branch sums) x 1.11")
    # cap
    st = [{"source": "user", "extra": {"event_type": "task_prompt", "timestamp": t0}}] + \
        [step("fixer", t0 + 30 * k, 1000, 4000 + 10 * k, "run_command", t0 + 30 * k + 0.5) for k in range(1, 30)]
    synth_trace(root / "t_cap.json", st)
    p = timepred.predict_trace(timepred.parse_trace(str(root / "t_cap.json")), c, 480.0)
    check(p["timeout"] and p["pred_agent_s"] == 480.0, "timepred: 8-minute cap and timeout flag")


# ------------------------------------------------------------------ 2. make_lab kernels

def kernels(work: Path) -> None:
    ml = HERE / "make_lab.py"
    bdir = HERE.parent / "bundle_v29"
    out = work / "k_new"
    subprocess.run([sys.executable, str(ml), "--bundles", f"v29={bdir}", "--tasks", "t1", "t2", "--out", str(out),
                    "--data-dir", "evalset-merge", "--extra-kernel-sources", "me/evalset-merge", "--sandbox", "docker-like",
                    "--grade-extra-patches", "/tmp/a.diff,/tmp/b.diff"], check=True, capture_output=True)
    code = (out / "lab.py").read_text()
    meta = json.loads((out / "kernel-metadata.json").read_text())
    import ast
    ast.parse(code)
    check("labworker.job_extras(DATA_DIR, tid, DATA_OPTS, SANDBOX_ENV)" in code and "'docker-like'" in code
          and "'/tmp/a.diff'" in code and "VllmServer(" in code, "make_lab: data-dir kernel carries the options")
    check(meta["kernel_sources"] == ["me/evalset-merge"] and meta["enable_gpu"] is True and meta["is_private"] is True,
          "make_lab: --extra-kernel-sources in metadata, private")
    out2 = work / "k_p2"
    subprocess.run([sys.executable, str(ml), "--tasks", "t1", "--out", str(out2), "--data-dir", "evalset-merge",
                    "--phase2-only", "gold,empty", "--sandbox", "docker-like"], check=True, capture_output=True)
    code2 = (out2 / "lab.py").read_text()
    meta2 = json.loads((out2 / "kernel-metadata.json").read_text())
    ast.parse(code2)
    check("VllmServer(" not in code2 and "MODES = ['gold', 'empty']" in code2 and "torch" not in code2.split("MODES")[0][-3000:],
          "make_lab: --phase2-only kernel has no vLLM/model code")
    check(meta2["enable_gpu"] is False and "machine_shape" not in meta2 and meta2["model_sources"] == []
          and meta2["enable_tpu"] is False and meta2["is_private"] is True, "make_lab: --phase2-only metadata is CPU-only, private")


# ------------------------------------------------------------------ 3. phase 2 end to end

def phase2(work: Path, data: Path, comp: Path, ids: list, py313: str, image: str) -> None:
    out = work / "p2"
    opts = {"per_task_wheels": True, "sandbox": "docker-like", "py313": py313, "image_dir": image,
            "work_root": str(work / "p2work"), "no_graphs": True}
    env = labworker.prepare_sandbox_env(data, opts, print, comp)
    check(env.get("sandbox_dir") == str(comp / "sandbox"), "setup.py fallback to the competition sandbox dir")
    jobs = []
    for tid in ids:
        for mode in ("gold", "empty"):
            job = dict(bundle=mode, replicate=0, task_id=tid, bundle_dir=None, results_dir=str(out / mode / "r0"),
                       data_dir=str(data), api_base=None, served_model="none", clock="real")
            job.update(labworker.job_extras(data, tid, opts, env))
            job["phase2_only"] = mode
            jobs.append(job)
    keys = {j.get("wheels_key") for j in jobs}
    check(len(keys) == len(ids) and None not in keys, f"per-task wheel sets: {len(keys)} keys for {len(ids)} tasks")
    rows = labworker.run_pool(jobs, 2, out, lambda *a: None, kill_after=1800)
    by = {(r["id"], r["bundle"]): r for r in rows}
    for tid in ids:
        g, e = by.get((tid, "gold"), {}), by.get((tid, "empty"), {})
        check(g.get("resolved_kaggle_env") is True, f"phase2 gold passes: {tid} ({g.get('task_seconds')} s) {str(g.get('error'))[:200]}")
        check(e.get("resolved_kaggle_env") is False and not str(e.get("error", "")).startswith("CRASH"),
              f"phase2 empty fails: {tid}")
    left = [p for p in (work / "p2work" / "tmp").glob("*")] if (work / "p2work" / "tmp").exists() else []
    check(not left, f"per wheel-set TMPDIRs removed after the last job ({len(left)} left)")


# ------------------------------------------------------------------ 4. agent end to end (fake model)

LATENCY = dict(timepred.CONSTS)


class FakeOpenAI(http.server.BaseHTTPRequestHandler):
    """Scripted chat endpoint. Role from the system prompt ('ROLE:<name>'), step = assistant messages so far.
    Sleeps per_call + per_token x ct (timepred's step model without the prefill term; streams do not slow each
    other down, so the check uses PARALLEL_SLOWDOWN 1)."""
    gold: dict = {}

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "gemma-4-31b-it-qat-w4a16-ct", "object": "model"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(n) or b"{}")
        msgs = req.get("messages", [])
        txt = lambda c: "".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else (c or "")  # noqa: E731
        system = "\n".join(txt(m.get("content")) for m in msgs if m.get("role") == "system")
        allu = "\n".join(txt(m.get("content")) for m in msgs)
        role = system.split("ROLE:", 1)[1].split()[0] if "ROLE:" in system else "other"
        repo = next(iter(self.gold), None)  # one task per self-test run
        gold = self.gold.get(repo, "")
        i = sum(1 for m in msgs if m.get("role") == "assistant")
        apply_gold = "cd /workspace && git apply --whitespace=nowarn <<'SWEPATCH'\n" + gold + "\nSWEPATCH\necho applied"
        write_a = "cat > /tmp/a.diff <<'SWEPATCH'\n" + gold + "\nSWEPATCH\necho saved"
        S = {
            "solo": [("run_command", {"command": "git ls-files | head -5"}), ("run_command", {"command": apply_gold}),
                     ("run_command", {"command": "git diff --stat"}), ("submit_patch", {}), ("text", "Done.")],
            "lead": [("solver", {"request": "go"}), ("submit_patch", {}), ("text", "DONE")],
            "solver": [("run_command", {"command": "git ls-files | head -3"}), ("run_command", {"command": apply_gold}),
                       ("text", "Applied the fix.")],
            "plead": [("attempts", {"request": "go"}), ("run_command", {"command": "cd /workspace && git apply /tmp/a.diff && git diff --stat"}),
                      ("submit_patch", {}), ("text", "DONE")],
            "wa": [("run_command", {"command": "git ls-files | head -3"}), ("run_command", {"command": write_a}),
                   ("run_command", {"command": "wc -l /tmp/a.diff"}), ("text", "A ready.")],
            "wb": [("run_command", {"command": "git ls-files | head -2"}), ("run_command", {"command": "true > /tmp/b.diff"}),
                   ("run_command", {"command": "echo b"}), ("run_command", {"command": "echo b2"}), ("text", "B found nothing.")],
        }
        steps = S.get(role, [("text", "ok")])
        action = steps[i] if i < len(steps) else ("text", "Done.")
        pt = len(json.dumps(msgs)) // 4
        ct = 60 + 40 * (i % 3)
        time.sleep(LATENCY["per_call"] + LATENCY["per_token"] * ct)  # no prefill term, no contention
        if action[0] == "text":
            message = {"role": "assistant", "content": action[1]}
            finish = "stop"
        else:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                "function": {"name": action[0], "arguments": json.dumps(action[1])}}]}
            finish = "tool_calls"
        self._send({"id": "chatcmpl-" + uuid.uuid4().hex[:8], "object": "chat.completion", "created": int(time.time()),
                    "model": req.get("model", "fake"), "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}})


class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def write_bundles(root: Path) -> dict:
    sampling = "temperature: 0.2\nmax_output_tokens: 2048\n"
    ev = "evaluation:\n  timeout_seconds: 120\n  max_tool_calls: 20\n  max_time_minutes: 4\n  max_turns: 40\n"
    common = {"configs/sampling.yaml": sampling, "eval_config.yaml": ev}
    b = {
        "solo": {**common, "prompts/system.md": "ROLE:solo You fix the issue.\n",
                 "agent.yaml": "name: fixer\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: solo\n"
                               "instruction: !include prompts/system.md\ntools:\n  - run_command\n  - submit_patch\n"
                               "generate_content_config: !include configs/sampling.yaml\n"},
        "at": {**common, "prompts/lead.md": "ROLE:lead Call solver, then submit_patch.\n",
               "prompts/solver.md": "ROLE:solver Fix: {problem_description}\n",
               "agent.yaml": "name: lead\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: lead\n"
                             "instruction: !include prompts/lead.md\ntools:\n  - agent_tool:\n      config_path: sub_agents/solver.yaml\n"
                             "  - submit_patch\ngenerate_content_config: !include configs/sampling.yaml\n",
               "sub_agents/solver.yaml": "name: solver\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: Solves the issue.\n"
                                         "instruction: !include ../prompts/solver.md\ntools:\n  - run_command\n"
                                         "generate_content_config: !include ../configs/sampling.yaml\n"},
        "par": {**common, "prompts/lead.md": "ROLE:plead Call attempts, apply A, submit.\n",
                "prompts/wa.md": "ROLE:wa Attempt A: {problem_description}\n", "prompts/wb.md": "ROLE:wb Attempt B: {problem_description}\n",
                "agent.yaml": "name: lead\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: lead\n"
                              "instruction: !include prompts/lead.md\ntools:\n  - agent_tool:\n      config_path: sub_agents/attempts.yaml\n"
                              "  - run_command\n  - submit_patch\ngenerate_content_config: !include configs/sampling.yaml\n",
                "sub_agents/attempts.yaml": "name: attempts\nagent_class: ParallelAgent\ndescription: Two attempts at once.\n"
                                            "sub_agents:\n  - config_path: wa.yaml\n  - config_path: wb.yaml\n",
                "sub_agents/wa.yaml": "name: wa\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: attempt A\n"
                                      "instruction: !include ../prompts/wa.md\ntools:\n  - run_command\n"
                                      "generate_content_config: !include ../configs/sampling.yaml\n",
                "sub_agents/wb.yaml": "name: wb\nmodel: gemma-4-31b-it-qat-w4a16-ct\ndescription: attempt B\n"
                                      "instruction: !include ../prompts/wb.md\ntools:\n  - run_command\n"
                                      "generate_content_config: !include ../configs/sampling.yaml\n"},
    }
    dirs = {}
    for name, files in b.items():
        d = root / name
        for rel, text in files.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text)
        dirs[name] = d
    return dirs


def e2e(work: Path, data: Path, comp: Path, tid: str, py313: str, image: str) -> None:
    tasks = {}
    for line in (data / "tasks.jsonl").read_text().splitlines():
        if line.strip():
            t = json.loads(line)
            tasks[t["instance_id"]] = t
    FakeOpenAI.gold = {tasks[tid]["repo"]: tasks[tid]["patch"]}
    srv = ThreadingServer(("127.0.0.1", 0), FakeOpenAI)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    bundles = write_bundles(work / "bundles")
    # kernel-like layout so timepred finds bundles/<name>/eval_config.yaml (cap)
    out = work / "e2e" / "lab"
    shutil.copytree(work / "bundles", work / "e2e" / "bundles")
    opts = {"per_task_wheels": True, "sandbox": "docker-like", "py313": py313, "image_dir": image,
            "work_root": str(work / "e2ework"), "no_graphs": True}
    env = labworker.prepare_sandbox_env(data, opts, print, comp)
    jobs = []
    for name, clock in (("solo", "real"), ("solo", "virtual"), ("at", "real"), ("par", "real")):
        bname = name if clock == "real" else name + "_vc"
        if clock != "real":
            shutil.copytree(bundles[name], work / "e2e" / "bundles" / bname, dirs_exist_ok=True)
        job = dict(bundle=bname, replicate=0, task_id=tid, bundle_dir=str(bundles[name]),
                   results_dir=str(out / bname / "r0"), data_dir=str(data), api_base=f"http://127.0.0.1:{port}/v1",
                   served_model="gemma-4-31b-it-qat-w4a16-ct", alias="gemma-4-31b-it-qat-w4a16-ct", clock=clock,
                   per_call=None, per_token=None, real_factor=3.0, wall_scale=1.0, tool_seconds=True)
        job.update(labworker.job_extras(data, tid, dict(opts, extra_patches=["/tmp/a.diff", "/tmp/b.diff"] if name == "par" else None), env))
        jobs.append(job)
    rows = labworker.run_pool(jobs, 2, out, lambda *a: None, kill_after=900)
    srv.shutdown()
    by = {r["bundle"]: r for r in rows}
    for b in ("solo", "solo_vc", "at", "par"):
        r = by.get(b, {})
        check(r.get("resolved_kaggle_env") is True, f"e2e {b}: gold applied by the fake model is resolved "
                                                   f"(calls {r.get('llm_calls')}, {r.get('task_seconds')} s) {str(r.get('error'))[:300]}")
    ex = (by.get("par") or {}).get("extra_patches") or {}
    check(ex.get("a", {}).get("resolved") is True and ex.get("b", {}).get("chars") == 0,
          f"e2e par: extra patch a graded resolved, b empty ({json.dumps({k: {kk: v.get(kk) for kk in ('chars', 'resolved')} for k, v in ex.items()})})")
    check(by.get("solo_vc", {}).get("clock") == "virtual" and by["solo_vc"].get("vc_llm_calls") == by["solo_vc"].get("llm_calls"),
          "e2e solo_vc: virtual clock charged every harness-counted call")
    check(by.get("par", {}).get("vc_llm_calls") == by.get("par", {}).get("llm_calls"),
          f"e2e par: worker calls reach the harness counter (llm_calls {by.get('par', {}).get('llm_calls')}, "
          f"branches {by.get('par', {}).get('vc_branch_calls')})")
    rws = timepred.load_rows(str(work / "e2e"))
    saved = dict(timepred.PARALLEL_SLOWDOWN)
    timepred.PARALLEL_SLOWDOWN.update({2: 1.0, 3: 1.0})
    try:
        preds = {r["bundle"]: timepred.predict_row(r, {"per_kuncached": 0.0}) for r in rws}
    finally:
        timepred.PARALLEL_SLOWDOWN.update(saved)
    for b in ("solo", "at", "par"):
        p = preds.get(b, {})
        r = by.get(b, {})
        check(p.get("n_calls") == r.get("llm_calls"), f"timepred {b}: trace calls {p.get('n_calls')} = harness llm_calls {r.get('llm_calls')}")
        if p.get("meas_agent_s"):
            err = (p["pred_agent_s"] - p["meas_agent_s"]) / p["meas_agent_s"]
            check(abs(err) < 0.08, f"timepred {b}: pred {p['pred_agent_s']} s vs measured {p['meas_agent_s']} s ({100 * err:+.1f}%)")
    pa = preds.get("at", {}).get("by_author", {})
    check(pa.get("solver", {}).get("calls", 0) >= 3 and pa.get("lead", {}).get("calls", 0) >= 3,
          f"timepred at: agent_tool solver calls visible in the trace ({pa})")
    check(sorted(map(sorted, preds.get("par", {}).get("parallel_groups") or [])) == [["wa", "wb"]],
          f"timepred par: workers detected as one parallel group ({preds.get('par', {}).get('parallel_groups')})")
    r = subprocess.run([sys.executable, str(HERE / "stats.py"), str(work / "e2e"), "--boot", "200"], capture_output=True, text=True)
    check(r.returncode == 0 and "TWO-ATTEMPT" in r.stdout and "a=1" in r.stdout and "oracle=1" in r.stdout,
          "stats.py: reads the e2e run, two-attempt A/B/oracle/picked")
    print(r.stdout[-1500:])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="competition-format data with per-task wheels")
    ap.add_argument("--competition", type=Path, required=True, help="competition data (sandbox/setup.py, docker/)")
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--py313", default="/usr/bin/python3.13")
    ap.add_argument("--image", default=None, help="prepared image venv (default <competition>/image313)")
    ap.add_argument("--ids", nargs="+", default=["marshmallow-code__marshmallow-2925_interface", "macbre__sql-metadata-625_interface"])
    ap.add_argument("--skip-e2e", action="store_true")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    a.work = a.work.resolve()
    a.work.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="labselftest_", dir=a.work))
    image = a.image or str(a.competition / "image313")
    try:
        unit(work)
        kernels(work)
        if not a.skip_e2e:
            phase2(work, a.data.resolve(), a.competition.resolve(), a.ids, a.py313, image)
            e2e(work, a.data.resolve(), a.competition.resolve(), a.ids[0], a.py313, image)
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f"\n{len(FAILS)} failure(s)" + ("".join("\n  - " + f for f in FAILS) if FAILS else ""))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
