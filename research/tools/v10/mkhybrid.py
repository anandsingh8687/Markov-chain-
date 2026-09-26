"""Build a single-file hybrid: v9 for step < SWITCH, the scratch planner after."""
import sys, base64, zlib
v9 = open(sys.argv[1]).read(); planner = open(sys.argv[2]).read(); switch = int(sys.argv[3]); out = sys.argv[4]
def blob(s): return base64.b64encode(zlib.compress(s.encode(), 9)).decode()
src = f'''# hybrid experiment: v9 until step {switch}, then planner
import base64 as _hb64, zlib as _hz
_HY_V9 = {{"__name__": "_hy_v9"}}
exec(compile(_hz.decompress(_hb64.b64decode({blob(v9)!r})).decode(), "v9", "exec"), _HY_V9)
_HY_PL = {{"__name__": "_hy_pl"}}
exec(compile(_hz.decompress(_hb64.b64decode({blob(planner)!r})).decode(), "planner", "exec"), _HY_PL)
_HY_A = _HY_V9["agent"]
_HY_B = _HY_PL["agent"]
_HY_SWITCH = {switch}


def agent(observation, configuration=None):
    step = int(observation.get("step", 0))
    if step < _HY_SWITCH:
        return _HY_A(observation, configuration)
    try:
        return _HY_B(observation, configuration)
    except Exception:
        return {{"farmer": ["PASS"], "hands": [], "market": []}}
'''
open(out, 'w').write(src)
