import sys
base, layer, out = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(base).read(); lay = open(layer).read()
mark = '# ==== v9 morning-hire reserve ===='
i = src.index(mark); src = src[:i] + lay.lstrip('\n') + '\n\n' + src[i:]
old = """        _STX_REPORT['stx_errors'] += 1
"""
assert src.count(old) == 1
src = src.replace(old, old + """    try:
        action = _rnc_apply(observation, action)
    except Exception:
        _RNC_REPORT['rnc_errors'] += 1
""")
open(out, 'w').write(src)
