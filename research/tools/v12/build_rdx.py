import sys
base, layer, out = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(base).read(); lay = open(layer).read()
mark = '# ==== v9 morning-hire reserve ===='
i = src.index(mark); src = src[:i] + lay.lstrip('\n') + '\n\n' + src[i:]
old = """    try:
        action = _V10_INNER(observation, configuration)
    except Exception:
        return {"farmer": ["PASS"], "hands": [], "market": []}
"""
assert old in src
src = src.replace(old, old + """    try:
        action = _rdx_apply(observation, action)
    except Exception:
        _RDX_REPORT['rdx_errors'] += 1
""")
open(out, 'w').write(src)
