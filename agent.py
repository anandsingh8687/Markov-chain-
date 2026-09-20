"""Import alias for tooling. The Kaggle evaluator loads archive-root main.py."""

from main import KaggricultureAgent, Econ, agent  # noqa: F401

__all__ = ["agent", "KaggricultureAgent", "Econ"]
