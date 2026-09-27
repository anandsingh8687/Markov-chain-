"""Hybrid v17 harness: v14 (the tape agent) plays until turn T0, the planner from then on.

Usage from a bench:  make_agent(v14_path, planner_path, t0) -> agent(observation, configuration)
The planner module must expose class Planner with act(observation, configuration).
"""
import importlib.util


def _load_agent(path):
    ns = {'__name__': 'v14'}
    exec(compile(open(path).read(), path, 'exec'), ns)
    return [v for v in ns.values() if callable(v)][-1], ns


def _load_planner(path):
    spec = importlib.util.spec_from_file_location('v17planner', path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def make_agent(v14_path, planner_path, t0):
    tape_agent, _ = _load_agent(v14_path)
    mod = _load_planner(planner_path)
    planner = mod.Planner()

    def agent(obs, cfg=None):
        step = int(obs['step'])
        if step < t0:
            return tape_agent(obs, cfg)
        if step == t0 and hasattr(planner, 'takeover'):
            planner.takeover(obs)
        return planner.act(obs, cfg)
    agent.planner = planner
    return agent
