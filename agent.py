"""Convenience alias.

The Kaggle evaluator loads the archive-root ``main.py``; this module exists so
the agent can also be imported as ``agent`` by tooling and notebooks. The
submission itself ships ``main.py`` only -- see docs/ARCHITECTURE.md.
"""

from main import KaggricultureAgent, Econ, agent  # noqa: F401

__all__ = ["agent", "KaggricultureAgent", "Econ"]
