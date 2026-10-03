"""Compile a bundle with the organizers' own libraries (swegemma + adk-submission).

Catches schema, templating and model errors that would otherwise surface only as
"Your notebook hit an unhandled error" after a day's submission slot is spent.

Usage (inside a venv with the wheelhouse installed, see README):
    python gemma_agent/official_check.py gemma_agent/bundle_v3
"""

from __future__ import annotations

import sys
from pathlib import Path

from adk_submission import compile_submission
from adk_submission.discovery import validate_directory
from swegemma.config import build_submission_limits
from swegemma.models import setup_gemma_model_registry
from swegemma.models.discovery import validate_single_declared_model


def _tool(name):
    def fn(**kwargs):  # the harness binds real sandboxed tools; names are what matter here
        return "{}"
    fn.__name__ = name
    return fn


TOOLS = {n: _tool(n) for n in (
    "run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch",
    "search_similar_code", "get_code_neighbors", "get_code_subgraph")}


def walk(agent, depth=0):
    kind = type(agent).__name__
    model = getattr(agent, "model", "")
    tools = [getattr(t, "name", type(t).__name__) for t in getattr(agent, "tools", []) or []]
    print("  " * depth + f"{kind} {agent.name} model={getattr(model, 'model', model)!s} tools={tools}")
    cfg = getattr(agent, "generate_content_config", None)
    if cfg is not None and depth == 0:
        print("  " * depth + f"  generate_content_config: {cfg}")
    for sub in getattr(agent, "sub_agents", []) or []:
        walk(sub, depth + 1)


def main() -> None:
    bundle = Path(sys.argv[1]).resolve()
    limits, gen_constraints = build_submission_limits()
    validate_directory(bundle, limits) if validate_directory.__code__.co_argcount > 1 else validate_directory(bundle)
    print("model:", validate_single_declared_model(bundle))
    agent = compile_submission(
        submission_dir=bundle, tool_registry=TOOLS, model_registry=setup_gemma_model_registry(),
        limits=limits, generation_constraints=gen_constraints,
    )
    walk(agent)
    print("OK: compiled with the official harness libraries")


if __name__ == "__main__":
    main()
