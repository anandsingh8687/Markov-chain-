"""Build hybrid: v9 until SWITCH, Foreman after. Usage: mkfm.py SWITCH OUT [PARAMS_JSON]"""
import sys, base64, zlib, json
switch = int(sys.argv[1]); out = sys.argv[2]; params = sys.argv[3] if len(sys.argv) > 3 else "{}"
v9 = open('pool/v9_open8/main.py').read(); fm = open('v10/foreman.py').read()
def blob(s): return base64.b64encode(zlib.compress(s.encode(), 9)).decode()
src = f'''# v10 experiment: v9 until step {switch}, then Foreman
import base64 as _hb64, zlib as _hz, json as _hj
_HY_V9 = {{"__name__": "_hy_v9"}}
exec(compile(_hz.decompress(_hb64.b64decode({blob(v9)!r})).decode(), "v9", "exec"), _HY_V9)
_HY_FM = {{"__name__": "_hy_fm"}}
exec(compile(_hz.decompress(_hb64.b64decode({blob(fm)!r})).decode(), "foreman", "exec"), _HY_FM)
_HY_FM["P"].update(_hj.loads({params!r}))
_HY_A = _HY_V9["agent"]
_HY_F = _HY_FM["Foreman"]()
_HY_SWITCH = {switch}
_HY_ERR = [0]


def agent(observation, configuration=None):
    step = int(observation.get("step", 0))
    if step < _HY_SWITCH:
        return _HY_A(observation, configuration)
    try:
        return _HY_F.act(observation, configuration)
    except Exception:
        _HY_ERR[0] += 1
        import os
        if os.environ.get("FM_STRICT"):
            raise
        return {{"farmer": ["PASS"], "hands": [], "market": []}}
'''
open(out, 'w').write(src)
