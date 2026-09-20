# Incumbent benchmark

`main.py` here is the agent from PR #1 (`cursor/global-optima-agent-2233`), kept
so the strength gate can answer the only question that matters before a
submission slot is spent: **is this an improvement or a regression?**

Beating the built-in `starter` is table stakes -- it finishes around $3.5k and
says nothing about ladder position. This incumbent finishes around $13k and was
the strongest agent this repository had produced before the current `main.py`.
Do not delete it: without a fixed reference point, "the new agent scored more"
is unfalsifiable, because both players draw from the same order book and a
score is only meaningful relative to who was on the other side of it.
