"""Benchmark opponent: the agent currently on the ladder (economy_v16).

Present only so the CI gate can prove a candidate actually beats what is
already deployed. Not part of the submission payload.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from economy_v16 import agent  # noqa: E402,F401

__all__ = ["agent"]
