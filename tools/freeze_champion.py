#!/usr/bin/env python3
"""Freeze main.py into a champion copy that ignores KG_PARAMS.

Self-play A/B needs the two sides to differ. Both would read the same
KG_PARAMS environment override, so the champion is written out with that hook
disabled and its parameters baked in as they stand.
"""
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "agents/scratch/main.py"
DST = sys.argv[2] if len(sys.argv) > 2 else "champion.py"
s = open(SRC).read()
needle = 'if _os.environ.get("KG_PARAMS"):'
if needle not in s:
    raise SystemExit("KG_PARAMS hook not found in " + SRC)
s = s.replace(needle, 'if False:  # frozen champion: ignores KG_PARAMS')
open(DST, "w").write(s)
print("froze {} -> {} ({} bytes)".format(SRC, DST, os.path.getsize(DST)))
