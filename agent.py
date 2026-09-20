"""Import alias.

The Kaggle evaluator loads the archive-root ``main.py``; this module exists so
the same agent can be imported as ``agent`` from notebooks and tooling. The
submission itself ships ``main.py`` only -- see docs/ARCHITECTURE.md.
"""

from main import agent, _decide, price_at, drain_rates, PLAN, RATE  # noqa: F401

__all__ = ["agent", "_decide", "price_at", "drain_rates", "PLAN", "RATE"]
