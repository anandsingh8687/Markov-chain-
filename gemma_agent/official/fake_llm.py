"""A fake OpenAI-compatible chat endpoint that returns scripted tool calls, for smoke-testing bundles
through the real harness (run_official.py) without a GPU.

    python gemma_agent/official/fake_llm.py --port 8931 --scenario b_wins [--delay 2.5] [--log FILE]

It serves POST /v1/chat/completions (and GET /v1/models). The agent is recognised from its system
instruction (bundle_v24: "You are attempt A", "You are attempt B", "Two attempts have worked"); the step is
the number of assistant messages already in the request, so the stub is stateless and several tasks can
run at once. Generic rules come first:
  * the previous assistant call was submit_patch          -> reply with one line of text (ends the task)
  * the last tool output contains the FINAL line          -> call submit_patch
  * the last tool output starts with NOT FINAL (finisher) -> reply with one line of text
Otherwise the scenario's script for that agent gives the next action; when it runs out, its last action
repeats. Each response waits --delay seconds (a stand-in for model latency). Token usage is reported
small, so the harness never compacts. Prints no secrets; accepts any API key.
"""

import argparse
import http.server
import json
import re
import sys
import threading
import time
import uuid

FINAL = "FINAL PATCH IS IN /workspace"
REPRO = "import {pkg}\nassert getattr({pkg}, 'SWE_MARK', 0) == 1, 'mark missing'\nprint('mark ok')\n"


def tool(name, **args):
    return ("tool", name, args)


def cmd(c):
    return tool("run_command", command=c)


def text(t):
    return ("text", t)


def append_mark(pkg_init, value, where="a"):
    line = "SWE_MARK = %d" % value
    if where == "a":
        return cmd("printf '\\n%s\\n' >> %s" % (line, pkg_init))
    return cmd("python3 /tmp/b/t/sh.py <<'EOF'\nprintf '\\n%s\\n' >> %s\nEOF" % (line, pkg_init))


def script(scenario, agent, pkg, pkg_init):
    ia = tool("run_skill_script", skill_name="swe-tools-a", file_path="scripts/install_a.py")
    ib = tool("run_skill_script", skill_name="swe-tools-b", file_path="scripts/install_b.py")
    ra = cmd("python3 .swetools/run.py /tmp/a/repro.py <<'EOF'\n%sEOF" % REPRO.format(pkg=pkg))
    rb = cmd("python3 /tmp/b/t/run.py /tmp/b/repro.py <<'EOF'\n%sEOF" % REPRO.format(pkg=pkg))
    ca = cmd("python3 .swetools/check.py --repro /tmp/a/repro.py")
    cb = cmd("python3 /tmp/b/t/check.py --repro /tmp/b/repro.py")
    sa = cmd("python3 .swetools/status.py")
    sb = cmd("python3 /tmp/b/t/status.py")
    fin = [cmd("python3 .swetools/pick_patch.py --finisher")]
    S = {
        # B passes the GATE first; A only looks around
        "b_wins": {"a": [ia, ra, sa], "b": [ib, append_mark(pkg_init, 1, "b"), rb, cb, sb]},
        # A passes the GATE first; B only looks around
        "a_wins": {"a": [ia, append_mark(pkg_init, 1), ra, ca, sa], "b": [ib, rb, sb]},
        # nobody passes: A's value is wrong, B never checks; the deadline pick must choose B's patch
        "deadline": {"a": [ia, append_mark(pkg_init, 5), ra, ca, sa], "b": [ib, append_mark(pkg_init, 1, "b"), rb, sb]},
        # no helper call after the edits: the harness timeout fires mid-attempt; fallback = A's tree
        "timeout": {"a": [ia, append_mark(pkg_init, 7), cmd("echo waiting")], "b": [ib, append_mark(pkg_init, 1, "b"),
                                                                               cmd("echo waiting")]},
        # B calls submit_patch early (before FINAL), then replies with text
        "stray_submit": {"a": [ia, append_mark(pkg_init, 3), ra, sa], "b": [ib, sb, sb, tool("submit_patch")]},
        # both attempts stop early with text; the finisher agent picks and submits
        "finisher": {"a": [ia, append_mark(pkg_init, 1), ra, text("DONE")], "b": [ib, text("DONE")]},
        # both stop early with NO change: the finisher says NOT FINAL, the harness nudge re-runs the root and
        # the attempts continue; A then passes the GATE
        "nudge": {"a": [ia, text("DONE"), append_mark(pkg_init, 1), ra, ca, sa], "b": [ib, text("DONE"), sb]},
    }
    if agent == "finisher":
        return fin
    return S[scenario][agent]


def agent_of(system):
    if "You are attempt A" in system or "attempt A of two" in system:
        return "a"
    if "You are attempt B" in system or "attempt B of two" in system:
        return "b"
    if "Two attempts have worked" in system:
        return "finisher"
    return "other"


def _text(content):
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


class Handler(http.server.BaseHTTPRequestHandler):
    scenario = "b_wins"
    delay = 2.5
    log = None
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
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
        system = "\n".join(_text(m.get("content")) for m in msgs if m.get("role") == "system")
        user = "\n".join(_text(m.get("content")) for m in msgs if m.get("role") == "user")
        agent = agent_of(system)
        m = re.search(r"for repository (\S+?)\.\s", user)
        repo = m.group(1) if m else ""
        pkg = {"Textualize/rich": "rich", "fastapi/fastapi": "fastapi", "psf/requests": "requests"}.get(repo, "rich")
        pkg_init = {"requests": "src/requests/__init__.py"}.get(pkg, pkg + "/__init__.py")
        assistants = [mm for mm in msgs if mm.get("role") == "assistant"]
        last_tool = next((_text(mm.get("content")) for mm in reversed(msgs) if mm.get("role") == "tool"), "")
        prev_calls = [tc["function"]["name"] for tc in (assistants[-1].get("tool_calls") or [])] if assistants else []
        if "submit_patch" in prev_calls:
            action = text("Submitted the chosen patch.")
        elif FINAL in last_tool:
            action = tool("submit_patch")
        elif agent == "finisher" and "NOT FINAL" in last_tool:
            action = text("Not final; the attempts continue.")
        elif agent == "other":
            action = text("ok")
        else:
            steps = script(self.scenario, agent, pkg, pkg_init)
            i = len(assistants)
            action = steps[i] if i < len(steps) else steps[-1]
        time.sleep(self.delay)
        if action[0] == "text":
            message = {"role": "assistant", "content": action[1]}
            finish = "stop"
        else:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                "function": {"name": action[1], "arguments": json.dumps(action[2])}}]}
            finish = "tool_calls"
        if self.log:
            with self.lock, open(self.log, "a") as fh:
                fh.write(json.dumps({"t": time.time(), "agent": agent, "repo": repo, "step": len(assistants),
                                     "action": action[1] if action[0] == "tool" else "TEXT",
                                     "args": action[2] if action[0] == "tool" else action[1],
                                     "last_tool": last_tool[:2000]}) + "\n")
        self._send({"id": "chatcmpl-" + uuid.uuid4().hex[:12], "object": "chat.completion", "created": int(time.time()),
                    "model": req.get("model", "fake"),
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8931)
    ap.add_argument("--scenario", default="b_wins")
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--log", default=None)
    a = ap.parse_args()
    Handler.scenario, Handler.delay, Handler.log = a.scenario, a.delay, a.log
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print("fake LLM on 127.0.0.1:%d scenario=%s" % (a.port, a.scenario), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
