import sys
base, layer, out = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(base).read(); lay = open(layer).read()
mark = '# ==== v9 morning-hire reserve ===='
i = src.index(mark); src = src[:i] + lay.lstrip('\n') + '\n\n' + src[i:]
old = """        _RDX_REPORT['rdx_errors'] += 1
"""
assert src.count(old) == 1
src = src.replace(old, old + """    try:
        action = _tms_apply(observation, action)
    except Exception:
        _TMS_REPORT['tms_errors'] += 1
""")
src = src.replace('MDX_ITEMS = ("STRAWBERRY", "MILK", "WOOL")', 'MDX_ITEMS = ("STRAWBERRY", "MILK", "WOOL", "TOMATO")', 1)
a = "    if obs['private']['seeds'].get('TOMATO',0) or obs['private']['shed'].get('TOMATO',0):\n        return False"
assert src.count(a) == 1
src = src.replace(a, a.replace("    if obs", "    if not _TMS_STATE.get(obs['player'], {}).get('swapped') and (obs").replace("0):\n", "0)):\n"))
b = "    if any(isinstance(t,dict) and t.get('crop')=='TOMATO' for row in farm['tiles'] for t in row):\n        return False"
assert src.count(b) == 1
src = src.replace(b, b.replace("    if any(", "    if not _TMS_STATE.get(obs['player'], {}).get('swapped') and any("))
open(out, 'w').write(src)
