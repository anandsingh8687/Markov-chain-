"""Validate the agent bundle and package it as submission.zip.

Usage: python gemma_agent/build.py [--bundle DIR] [--out PATH]

The checks mirror the harness contract, so a bundle that would be rejected at
scoring time (and burn the one submission a day) fails here instead.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT_CONFIGS = ("agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml")
ALLOWED_SUFFIXES = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}
HARNESS_TOOLS = {
    "run_command", "read_file", "edit_file", "write_file", "get_status",
    "submit_patch", "search_similar_code", "get_code_neighbors", "get_code_subgraph",
}
MAX_BYTES = 3 * 2**30
CONTEXT_TOKENS = 32_768


class IncludeLoader(yaml.SafeLoader):
    """SafeLoader that resolves !include the way the harness does."""


def _resolve(base: Path, target: str) -> Path:
    if target.startswith("/") or "\0" in target:
        raise ValueError(f"illegal include path {target!r}")
    return (base / target).resolve()


def load_config(path: Path, bundle: Path, depth: int = 0):
    if depth > 10:
        raise ValueError(f"{path}: include depth over 10")

    def include(loader, node):
        target = loader.construct_scalar(node)
        resolved = _resolve(path.parent, target)
        if not resolved.is_relative_to(bundle.resolve()):
            raise ValueError(f"{path.name}: include {target!r} escapes the bundle")
        if not resolved.is_file():
            raise FileNotFoundError(f"{path.name}: missing include {target!r}")
        if resolved.suffix in (".yaml", ".yml"):
            return load_config(resolved, bundle, depth + 1)
        return resolved.read_text(encoding="utf-8")

    loader_cls = type("Loader", (IncludeLoader,), {})
    loader_cls.add_constructor("!include", include)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=loader_cls)


def check_agent(path: Path, bundle: Path, models: set, seen: set) -> None:
    if path in seen:
        return
    seen.add(path)
    cfg = load_config(path, bundle)
    rel = path.relative_to(bundle)
    if cfg.get("agent_class") in ("SequentialAgent", "ParallelAgent", "LoopAgent"):
        assert cfg.get("name") and cfg.get("sub_agents"), f"{rel}: workflow agent needs name and sub_agents"
        for sub in cfg["sub_agents"]:
            sub_path = bundle / sub["config_path"]
            assert sub_path.is_file(), f"{rel}: sub-agent {sub['config_path']} missing"
            check_agent(sub_path, bundle, models, seen)
        print(f"  {rel}: {cfg['agent_class']} with {len(cfg['sub_agents'])} stages")
        return
    assert cfg.get("include_contents", "default") in ("default", "none"), f"{rel}: bad include_contents"
    for key in ("name", "model", "instruction", "tools"):
        assert cfg.get(key), f"{rel}: missing {key}"
    assert isinstance(cfg["instruction"], str) and cfg["instruction"].strip(), f"{rel}: empty instruction"
    models.add(cfg["model"])
    if "adapter" in cfg:
        adapter = bundle / "adapters" / cfg["adapter"]
        assert (adapter / "adapter_model.safetensors").is_file(), f"{rel}: adapter {cfg['adapter']} not shipped"
        assert (adapter / "adapter_config.json").is_file(), f"{rel}: adapter config missing"
    gen = cfg.get("generate_content_config") or {}
    assert gen.get("max_output_tokens", 0) <= 32_768, f"{rel}: max_output_tokens over 32768"
    for tool in cfg["tools"]:
        if isinstance(tool, str):
            assert tool in HARNESS_TOOLS, f"{rel}: unknown tool {tool!r}"
        else:
            (kind, spec), = tool.items()
            assert kind == "agent_tool", f"{rel}: unknown tool entry {kind!r}"
            sub = bundle / spec["config_path"]
            assert sub.is_file(), f"{rel}: sub-agent {spec['config_path']} missing"
            check_agent(sub, bundle, models, seen)
    tokens = len(cfg["instruction"]) // 4
    assert tokens < 0.15 * CONTEXT_TOKENS, f"{rel}: prompt ~{tokens} tokens is too large for a 32k context"
    print(f"  {rel}: model={cfg['model']} tools={len(cfg['tools'])} prompt~{tokens} tok")


def validate(bundle: Path) -> list[Path]:
    files = sorted(p for p in bundle.rglob("*") if p.is_file())
    roots = [n for n in ROOT_CONFIGS if (bundle / n).is_file()]
    assert len(roots) == 1, f"need exactly one root config, found {roots}"
    assert not any(p.is_symlink() for p in bundle.rglob("*")), "symlinks are rejected"
    bad = [str(p.relative_to(bundle)) for p in files if p.suffix not in ALLOWED_SUFFIXES]
    assert not bad, f"disallowed file types: {bad}"
    total = sum(p.stat().st_size for p in files)
    assert total < MAX_BYTES, "bundle over 3 GiB unpacked"
    models: set = set()
    check_agent(bundle / roots[0], bundle, models, set())
    assert len(models) == 1, f"one base model per submission, found {models}"
    for p in files:
        if p.suffix in (".yaml", ".yml"):
            for target in re.findall(r"!include\s+(\S+)", p.read_text(encoding="utf-8")):
                assert (p.parent / target).is_file(), f"{p.name}: missing include {target}"
    ec = bundle / "eval_config.yaml"
    if ec.is_file():
        ev = (yaml.safe_load(ec.read_text()) or {}).get("evaluation", {})
        minutes = float(ev.get("max_time_minutes", 60))
        assert minutes <= 30, f"eval_config max_time_minutes={minutes}: ~120 tasks must fit in 12h"
        print(f"  eval_config.yaml: {ev}")
    else:
        print("  WARNING: no eval_config.yaml -> 60 min/task default; v1 exceeded the 12h runtime this way")
    print(f"OK: {len(files)} files, {total:,} bytes, model {models.pop()}")
    return files


def package(bundle: Path, out: Path, files: list[Path]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(bundle).as_posix())
    names = zipfile.ZipFile(out).namelist()
    assert any(n in ROOT_CONFIGS for n in names) and not any(n.endswith("/") for n in names)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    for n in names:
        print("  ", n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, default=HERE / "bundle")
    ap.add_argument("--out", type=Path, default=HERE / "dist" / "submission.zip")
    args = ap.parse_args()
    files = validate(args.bundle)
    package(args.bundle, args.out, files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
