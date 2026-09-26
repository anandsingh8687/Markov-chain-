"""mkvar.py BASE OUT NAME=VALUE ... : set module-level constants (last definition wins)."""
import sys, re
base, out = sys.argv[1], sys.argv[2]
src = open(base).read().split('\n')
for kv in sys.argv[3:]:
    name, val = kv.split('=', 1)
    idx = [i for i, l in enumerate(src) if re.match(rf'^{re.escape(name)}\s*=', l)]
    assert idx, name
    i = idx[-1]
    src[i] = f"{name} = {val}"
open(out, 'w').write('\n'.join(src))
