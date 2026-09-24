"""Run a declarative agent bundle on one task, the way swegemma's agent_runner does.

Mirrors HARNESS_README section 5: session state templating, the harness's
initial prompt, AgentTool sub-agents (skip_summarization ends the parent's
turn), continuation nudges (max 3 without a tool call), termination on
submit_patch, and fallback patch extraction. The 32k context ceiling is
enforced exactly as vLLM does: prompt + max_output_tokens > 32768 kills the
session (the harness does not retry a 400).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import env, llm, tools

NUDGE_CUT_TOOL_CALL = (
    "Your previous response reached the token limit before the tool call finished closing (<|tool_call|> was cut "
    "off). Do NOT repeat your prior reasoning in thought—emit your next tool call immediately, and if calling "
    "edit_file or write_file, split the change into smaller incremental edits.")
NUDGE_MAX_TOKENS = (
    "Your previous response reached the token limit while thinking before a tool call was completed. Do NOT "
    "repeat your analysis in thought—keep reasoning under a few sentences and emit your next tool call "
    "immediately, or call submit_patch when you have completed and verified your changes.")
NUDGE_CONTINUE = ("Please continue your work using the available tools, or call submit_patch when you have "
                  "completed and verified your changes.")


# ------------------------------------------------------------------ bundle

@dataclass
class Agent:
    name: str
    description: str
    instruction: str
    gen: dict
    tools: list[str]
    agent_tools: list[tuple["Agent", bool]] = field(default_factory=list)


def _load(path: Path, root: Path):
    def include(loader, node):
        target = (path.parent / loader.construct_scalar(node)).resolve()
        if target.suffix in (".yaml", ".yml"):
            return _load(target, root)
        return target.read_text()

    loader = type("L", (yaml.SafeLoader,), {})
    loader.add_constructor("!include", include)
    return yaml.load(path.read_text(), Loader=loader)


def compile_bundle(bundle: Path, cfg_path: Path | None = None) -> Agent:
    bundle = bundle.resolve()
    if cfg_path is None:
        cfg_path = next(bundle / n for n in ("agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml")
                        if (bundle / n).exists())
    cfg = _load(cfg_path, bundle)
    names, subs = [], []
    for t in cfg.get("tools") or []:
        if isinstance(t, str):
            names.append(t)
        else:
            spec = t["agent_tool"]
            subs.append((compile_bundle(bundle, bundle / spec["config_path"]), bool(spec.get("skip_summarization"))))
    return Agent(cfg["name"], cfg.get("description", ""), cfg.get("instruction", ""),
                 cfg.get("generate_content_config") or {}, names, subs)


# ------------------------------------------------------------------ prompt

def workspace_layout(ws: Path) -> str:
    r = env.sh("find . -maxdepth 3 -not -path './.git*' -not -name '__pycache__' -not -path '*/__pycache__/*' "
               "-not -name '*.pyc' | head -150", cwd=ws)
    return r.stdout


def build_agent_prompt(task: dict, ctx: tools.Context) -> str:
    b = ctx.budget
    parts = [f"You are evaluating a software engineering task for repository {task['repo']}.\n\n"
             f"Problem Statement:\n{task['problem_statement']}"]
    if (task.get("hints_text") or "").strip():
        parts.append(f"## Hints:\n{task['hints_text']}")
    lines = [f"- Time allowance: {b.time_minutes:.1f} minutes"]
    if b.tool_calls:
        lines.append(f"- Tool calls allowance: {b.tool_calls} calls")
    lines.append(f"- Max loop iterations: {b.turns} turns")
    parts.append("## Task Budget (Session terminates when any budget is exhausted)\n" + "\n".join(lines))
    parts.append(
        "## Execution Environment Rules\n"
        f"- Single command timeout: {tools.COMMAND_TIMEOUT} seconds (commands exceeding this fail without ending "
        "the session)\n"
        f"- Command output limit: {tools.MAX_STDOUT} characters\n"
        f"- File view limit: {tools.MAX_FILE_LINES} lines per read_file call\n"
        f"- File character limit: {tools.MAX_FILE_CHARS} characters per read_file call\n"
        "- Environment is offline (no network/PyPI access). All repository and test dependencies are ALREADY "
        "pre-installed. Do NOT attempt to run pip install or download packages.")
    parts.append(
        "## Instructions\n"
        "0. Work strictly inside /workspace, which contains the repository.\n"
        "1. Inspect the existing code and follow its conventions.\n"
        "2. Make the minimal source changes that resolve the problem statement.\n"
        "3. Prefer quick inline checks such as python3 -c \"...\" assertions over full test sweeps.\n"
        "4. When you are done, call submit_patch.\n"
        "5. Then reply with a short final summary.")
    if ctx.graph_available:
        parts.append(
            "## Code Intelligence Tools\nThis repository has pre-built code graph and embedding data. Use these "
            "tools for fast, targeted navigation:\n"
            "- `search_similar_code(query)`: Find semantically similar functions/classes by keyword.\n"
            "- `get_code_neighbors(node)`: Find callers, callees, and definitions related to a symbol.\n"
            "- `get_code_subgraph(nodes)`: Get the induced subgraph for a set of symbols.")
    parts.append("## Workspace Layout\n" + workspace_layout(ctx.ws))
    return "\n\n".join(parts)


def render(instruction: str, state: dict) -> str:
    def sub(m):
        key = m.group(1).rstrip("?")
        if key in state:
            return str(state[key])
        if m.group(1).endswith("?"):
            return ""
        raise KeyError(f"Context variable not found: `{key}`.")
    return re.sub(r"\{+([A-Za-z_][A-Za-z0-9_]*\??)\}+", sub, instruction)


# ------------------------------------------------------------------ loop

class SessionEnd(Exception):
    pass


@dataclass
class Trace:
    events: list = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"prompt": 0, "completion": 0, "calls": 0, "max_prompt": 0})

    def add(self, **kw):
        kw["t"] = round(time.time(), 2)
        self.events.append(kw)


def _declarations(agent: Agent) -> list[dict]:
    decls = [tools.declaration(n) for n in agent.tools if n in tools.TOOLS]
    for sub, _ in agent.agent_tools:
        decls.append({"type": "function", "function": {
            "name": sub.name, "description": sub.description,
            "parameters": {"type": "object", "properties": {"request": {"type": "string"}}, "required": ["request"]}}})
    return decls


def run_turn(agent: Agent, messages: list[dict], ctx: tools.Context, state: dict, trace: Trace,
             depth: int = 0) -> dict:
    """One ADK run_async: call the model until it answers without tool calls (or a turn-ending event).

    Returns {'text', 'had_tool_call', 'finish_reason', 'cut_tool_call'}.
    """
    system = render(agent.instruction, state)
    decls = _declarations(agent)
    subs = {s.name: (s, skip) for s, skip in agent.agent_tools}
    had_tool_call = False
    while True:
        if ctx.exhausted():
            raise SessionEnd(f"budget:{ctx.exhausted()}")
        ctx.turns_used += 1
        try:
            resp = llm.complete([{"role": "system", "content": system}] + messages, decls, agent.gen)
        except llm.ContextOverflow as exc:
            trace.add(agent=agent.name, depth=depth, kind="context_overflow", detail=str(exc))
            raise SessionEnd(f"context_overflow in {agent.name}: {exc}") from None
        u = resp["usage"]
        trace.usage["prompt"] += u.get("prompt_tokens", 0)
        trace.usage["completion"] += u.get("completion_tokens", 0)
        trace.usage["calls"] += 1
        trace.usage["max_prompt"] = max(trace.usage["max_prompt"], u.get("prompt_tokens", 0))
        msg = resp["message"]
        content = msg.get("content") or ""
        calls = msg.get("tool_calls") or []
        trace.add(agent=agent.name, depth=depth, kind="model", content=content,
                  tool_calls=[{"name": c["function"]["name"], "args": c["function"].get("arguments")} for c in calls],
                  finish=resp["finish_reason"], prompt_tokens=u.get("prompt_tokens"))
        assistant = {"role": "assistant", "content": content}
        if calls:
            assistant["tool_calls"] = calls
        messages.append(assistant)
        if not calls:
            cut = "<|tool_call" in content
            return {"text": content, "had_tool_call": had_tool_call, "finish_reason": resp["finish_reason"],
                    "cut_tool_call": cut}
        had_tool_call = True
        end_turn = False
        for c in calls:
            name = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = None
            if args is None:
                out = json.dumps({"status": "error", "error_type": "ValidationError",
                                  "error_message": "Tool arguments were not valid JSON."})
            elif name in subs:
                sub, skip = subs[name]
                out = run_subagent(sub, str(args.get("request", "")), ctx, state, trace, depth + 1)
                end_turn = end_turn or skip
            elif name in agent.tools and name in tools.TOOLS:
                out = tools.call(ctx, name, args)
            else:
                out = json.dumps({"status": "error", "error_type": "UnknownTool",
                                  "error_message": f"Tool '{name}' is not available."})
            trace.add(agent=agent.name, depth=depth, kind="tool", name=name, args=args, result=out[:3000])
            messages.append({"role": "tool", "tool_call_id": c.get("id", name), "content": out})
        if ctx.patch_submitted and depth == 0:
            raise SessionEnd("submitted")
        if end_turn:
            return {"text": "", "had_tool_call": True, "finish_reason": "skip_summarization", "cut_tool_call": False}


def run_subagent(agent: Agent, request: str, ctx: tools.Context, state: dict, trace: Trace, depth: int) -> str:
    """AgentTool: a fresh session with the parent's state; returns the sub-agent's final text."""
    messages = [{"role": "user", "content": request or "Proceed."}]
    trace.add(agent=agent.name, depth=depth, kind="subagent_start", request=request)
    result = run_turn(agent, messages, ctx, state, trace, depth)
    return result["text"]


def run_task(task: dict, bundle: Path, workdir: Path, budget: tools.Budget) -> dict:
    ws = env.make_workspace(task, workdir / "workspace")
    tmp = workdir / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    venv = env.task_venv(env.venv_for(task, ws), ws, workdir / "venv")
    ctx = tools.Context(ws=ws, tmp=tmp, venv=venv, budget=budget)
    root = compile_bundle(bundle)
    state = {"problem_description": task["problem_statement"]}
    if (task.get("hints_text") or "").strip():
        state["hints"] = task["hints_text"].strip()
    trace = Trace()
    messages = [{"role": "user", "content": build_agent_prompt(task, ctx)}]
    ctx.start = time.time()
    end_reason, nudges = "", 0
    try:
        while True:
            r = run_turn(root, messages, ctx, state, trace)
            if ctx.patch_submitted:
                end_reason = "submitted"
                break
            nudges = 0 if r["had_tool_call"] else nudges + 1
            if nudges > 3:
                end_reason = "max_nudges"
                break
            if r["cut_tool_call"]:
                nudge = NUDGE_CUT_TOOL_CALL
            elif str(r["finish_reason"]).upper() in ("LENGTH", "MAX_TOKENS"):
                nudge = NUDGE_MAX_TOKENS
            else:
                nudge = NUDGE_CONTINUE
            messages.append({"role": "user", "content": nudge})
            trace.add(agent="harness", depth=0, kind="nudge", content=nudge)
    except SessionEnd as exc:
        end_reason = str(exc)
    except Exception as exc:  # noqa: BLE001 - an agent error still yields the fallback patch
        end_reason = f"agent_error: {type(exc).__name__}: {exc}"[:2000]
    patch = ctx.submitted_patch if ctx.patch_submitted else tools._git_diff(ctx)
    return {
        "instance_id": task["instance_id"],
        "end_reason": end_reason,
        "submitted": ctx.patch_submitted,
        "patch": patch,
        "tool_calls": ctx.tool_calls_used,
        "turns": ctx.turns_used,
        "seconds": round(time.time() - ctx.start, 1),
        "usage": trace.usage,
        "trace": trace.events,
    }
