"""The swegemma tool set, reimplemented from HARNESS_README section 6.

Same names, arguments, JSON response shapes, truncation limits and budget
accounting, so an agent bundle sees the same world here as in the harness.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import env

MAX_STDOUT = 5000
MAX_FILE_LINES = 150
MAX_FILE_CHARS = 10000
COMMAND_TIMEOUT = 300


@dataclass
class Budget:
    time_minutes: float = 60.0
    tool_calls: int | None = None
    turns: int = 500


@dataclass
class Context:
    """Per-task sandbox state shared by the root agent and its sub-agents."""

    ws: Path
    tmp: Path
    venv: Path
    budget: Budget
    start: float = field(default_factory=time.time)
    tool_calls_used: int = 0
    turns_used: int = 0
    patch_submitted: bool = False
    submitted_patch: str = ""
    graph_available: bool = False

    def remaining_seconds(self) -> float:
        return self.budget.time_minutes * 60 - (time.time() - self.start)

    def remaining_calls(self) -> int | None:
        if self.budget.tool_calls is None:
            return None
        return self.budget.tool_calls - self.tool_calls_used

    def exhausted(self) -> str | None:
        if self.remaining_seconds() <= 0:
            return "time"
        if self.remaining_calls() is not None and self.remaining_calls() <= 0:
            return "tool_calls"
        if self.turns_used >= self.budget.turns:
            return "turns"
        return None

    # Path mapping between the agent's view (/workspace, /tmp) and the host.
    def to_host(self, text: str) -> str:
        return re.sub(r"(?<![\w./-])/(workspace|var/tmp|tmp)(?=/|\b|$)",
                      lambda m: str(self.ws) if m.group(1) == "workspace" else str(self.tmp), text)

    def to_agent(self, text: str) -> str:
        return text.replace(str(self.ws), "/workspace").replace(str(self.tmp), "/tmp")


def _err(kind: str, message: str, **details) -> str:
    return json.dumps({"status": "error", "error_type": kind, "error_message": message, "details": details})


def _truncate(s: str) -> str:
    return s if len(s) <= MAX_STDOUT else s[:MAX_STDOUT]


def _resolve(ctx: Context, filepath: str) -> Path:
    fp = filepath.strip()
    for prefix in ("/workspace/", "/workspace"):
        if fp.startswith(prefix):
            fp = fp[len(prefix):]
            break
    fp = fp.lstrip("/")
    if ".." in Path(fp).parts:
        raise ValueError(f"path traversal is not allowed: {filepath}")
    return ctx.ws / fp


# ---------------------------------------------------------------- tools

def run_command(ctx: Context, command: str) -> str:
    timeout = min(COMMAND_TIMEOUT, max(5, int(ctx.remaining_seconds())))
    try:
        r = env.run_sandboxed(ctx.to_host(command), ctx.ws, env.command_env(ctx.venv, ctx.tmp), timeout)
    except TimeoutError:
        return _err("TimeoutExceeded", f"Command timed out after {timeout} seconds")
    out, err = _truncate(ctx.to_agent(r.stdout)), _truncate(ctx.to_agent(r.stderr))
    if r.returncode == 0:
        return json.dumps({"status": "ok", "stdout": out, "exit_code": 0})
    return _err("CommandError", f"Command failed with exit code {r.returncode}",
                stdout=out, stderr=err, exit_code=r.returncode)


def _git_diff(ctx: Context) -> str:
    env.sh("git add -N .", cwd=ctx.ws)
    return env.sh("git diff HEAD", cwd=ctx.ws).stdout


def submit_patch(ctx: Context) -> str:
    patch = _git_diff(ctx)
    ctx.submitted_patch = patch
    ctx.patch_submitted = True
    files = len(re.findall(r"^diff --git ", patch, re.M))
    return json.dumps({"status": "ok", "patch_size": len(patch), "files_changed": files})


def get_status(ctx: Context) -> str:
    rem = ctx.remaining_calls()
    return json.dumps({
        "tool_calls_used": ctx.tool_calls_used,
        "patch_submitted": ctx.patch_submitted,
        "patch_size": len(_git_diff(ctx)),
        "tool_calls_remaining": rem,
        "max_tool_calls": ctx.budget.tool_calls,
        "time_seconds_remaining": round(ctx.remaining_seconds(), 1),
        "max_time_minutes": ctx.budget.time_minutes,
        "agent_elapsed_seconds": round(time.time() - ctx.start, 1),
        "max_turns": ctx.budget.turns,
        "command_timeout_seconds": COMMAND_TIMEOUT,
    })


def read_file(ctx: Context, filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
    try:
        path = _resolve(ctx, filepath)
    except ValueError as exc:
        return _err("ValidationError", str(exc))
    if not path.is_file():
        return _err("FileNotFoundError", f"File not found: {filepath}")
    lines = path.read_text(errors="replace").splitlines(keepends=True)
    total = len(lines)
    start = max(1, int(start_line or 1))
    end = min(total, int(end_line) if end_line else total)
    chunk, chars, truncated = [], 0, False
    for i in range(start - 1, end):
        if len(chunk) >= MAX_FILE_LINES or chars + len(lines[i]) > MAX_FILE_CHARS:
            truncated = True
            break
        chunk.append(lines[i])
        chars += len(lines[i])
    return json.dumps({
        "status": "ok", "filepath": str(path.relative_to(ctx.ws)), "content": "".join(chunk),
        "start_line": start, "end_line": start + len(chunk) - 1, "total_lines": total,
        "is_truncated": truncated,
    })


def _flexible(text: str, old: str, new: str) -> tuple[str, int] | None:
    t_lines, o_lines = text.split("\n"), old.strip("\n").split("\n")
    stripped = [l.strip() for l in o_lines]
    hits = [i for i in range(len(t_lines) - len(o_lines) + 1)
            if [l.strip() for l in t_lines[i:i + len(o_lines)]] == stripped]
    if not hits:
        return None
    base = re.match(r"\s*", t_lines[hits[0]]).group(0)
    old_base = re.match(r"\s*", o_lines[0]).group(0)
    new_lines = []
    for l in new.strip("\n").split("\n"):
        new_lines.append(base + l[len(old_base):] if l.startswith(old_base) else (base + l.lstrip() if l.strip() else l))
    out = t_lines[:]
    for i in reversed(hits):
        out[i:i + len(o_lines)] = new_lines
    return "\n".join(out), len(hits)


def _regex(text: str, old: str, new: str) -> tuple[str, int] | None:
    tokens = [t for t in re.split(r"(\s+|[()\[\]{}:<>=])", old) if t and not t.isspace()]
    if not tokens:
        return None
    pattern = r"\s*".join(re.escape(t) for t in tokens)
    matches = list(re.finditer(pattern, text))
    if not matches:
        return None
    return re.sub(pattern, lambda m: new, text), len(matches)


def edit_file(ctx: Context, filepath: str, old_string: str, new_string: str, allow_multiple: bool = False) -> str:
    try:
        path = _resolve(ctx, filepath)
    except ValueError as exc:
        return _err("ValidationError", str(exc))
    if not path.is_file():
        return _err("FileEditError", f"File not found: {filepath}")
    text = path.read_text(errors="replace").replace("\r\n", "\n")
    if not text:
        return _err("FileEditError", "File is empty")
    if not old_string:
        return _err("FileEditError", "old_string must not be empty")
    old, new = old_string.replace("\r\n", "\n"), new_string.replace("\r\n", "\n")
    result, strategy = None, None
    n = text.count(old)
    if n:
        if n > 1 and not allow_multiple:
            return _err("FileEditError", f"old_string matches {n} occurrences; make it unique or set allow_multiple",
                        occurrences=n)
        result, strategy = (text.replace(old, new), n), "exact"
    for name, fn in (("flexible", _flexible), ("regex", _regex)):
        if result is None:
            got = fn(text, old, new)
            if got:
                if got[1] > 1 and not allow_multiple:
                    return _err("FileEditError", f"old_string matches {got[1]} occurrences; make it unique",
                                occurrences=got[1])
                result, strategy = got, name
    if result is None:
        return _err("FileEditError", "old_string not found in file")
    new_text, occurrences = result
    path.write_text(new_text)
    rel = str(path.relative_to(ctx.ws))
    diff = "".join(difflib.unified_diff(text.splitlines(True), new_text.splitlines(True), f"a/{rel}", f"b/{rel}"))
    return json.dumps({"status": "ok", "filepath": rel, "occurrences": occurrences, "strategy": strategy,
                       "diff": _truncate(diff), "is_truncated": len(diff) > MAX_STDOUT})


def write_file(ctx: Context, filepath: str, content: str) -> str:
    try:
        path = _resolve(ctx, filepath)
    except ValueError as exc:
        return _err("ValidationError", str(exc))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return json.dumps({"status": "ok", "filepath": str(path.relative_to(ctx.ws)), "size": len(content)})


def _no_graph(ctx: Context, **_) -> str:
    return _err("GraphUnavailable", "No code graph data is available for this repository.")


# name -> (function, counts toward tool budget, JSON schema, description)
TOOLS = {
    "run_command": (run_command, True, {"command": {"type": "string"}}, ["command"],
                    "Execute a shell command with bash -c inside /workspace and return stdout/stderr and the exit code."),
    "submit_patch": (submit_patch, False, {}, [],
                     "Submit the current working-tree changes (git diff HEAD, including new files) as the final patch. "
                     "Ends the session once the current turn completes."),
    "get_status": (get_status, False, {}, [], "Return live budget consumption and patch status."),
    "read_file": (read_file, True,
                  {"filepath": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
                  ["filepath"], "Read a file from /workspace with optional 1-indexed inclusive line range "
                                "(max 150 lines / 10000 chars per call)."),
    "edit_file": (edit_file, True,
                  {"filepath": {"type": "string"}, "old_string": {"type": "string"},
                   "new_string": {"type": "string"}, "allow_multiple": {"type": "boolean"}},
                  ["filepath", "old_string", "new_string"],
                  "Replace old_string with new_string in an existing file in /workspace."),
    "write_file": (write_file, True, {"filepath": {"type": "string"}, "content": {"type": "string"}},
                   ["filepath", "content"], "Create or overwrite a file in /workspace."),
    "search_similar_code": (_no_graph, True, {"query": {"type": "string"}, "k": {"type": "integer"}}, ["query"],
                            "Find functions/classes similar to a symbol name using pre-computed embeddings."),
    "get_code_neighbors": (_no_graph, True,
                           {"node": {"type": "string"}, "edge_type": {"type": "string"},
                            "max_neighbors": {"type": "integer"}}, ["node"],
                           "Find callers, callees and definitions related to a symbol in the code graph."),
    "get_code_subgraph": (_no_graph, True, {"nodes": {"type": "array", "items": {"type": "string"}}}, ["nodes"],
                          "Get the induced subgraph for a set of symbols."),
}


def declaration(name: str) -> dict:
    _, _, props, required, desc = TOOLS[name]
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


def call(ctx: Context, name: str, args: dict) -> str:
    fn, counts, props, _, _ = TOOLS[name]
    if counts:
        if ctx.exhausted():
            return _err("BudgetExceeded", f"Budget exhausted: {ctx.exhausted()}")
        ctx.tool_calls_used += 1
    try:
        clean = {k: v for k, v in args.items() if k in props}
        out = fn(ctx, **clean)
    except TypeError as exc:
        return _err("ValidationError", f"Bad arguments for {name}: {exc}")
    except Exception as exc:  # noqa: BLE001 - tools never raise into the agent
        return _err(type(exc).__name__, str(exc)[:1000])
    rem = ctx.remaining_calls()
    if counts and ctx.budget.tool_calls and ctx.budget.tool_calls >= 20 and rem is not None and rem <= 10:
        data = json.loads(out)
        data["budget_warning"] = (f"Only {rem} tool call(s) remaining ({ctx.tool_calls_used}/{ctx.budget.tool_calls} "
                                  "used). Finalize your edits and call submit_patch soon.")
        out = json.dumps(data)
    return out
