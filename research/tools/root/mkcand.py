"""Build a candidate agent = base main.py + appended module-level overrides.

Refuses to write a candidate whose loader-resolved entrypoint would change."""
import os, sys
POOL = sys.argv[1]; base = sys.argv[2]; name = sys.argv[3]; code = sys.argv[4]
src = open(os.path.join(POOL, base, "main.py")).read()
def last_callable(s):
    env = {}; exec(compile(s, "main.py", "exec"), env)
    return [k for k, v in env.items() if callable(v)][-1]
before = last_callable(src)
new = src.rstrip("\n") + "\n\n# ---- v8 candidate overrides ----\n" + code.replace("\\n", "\n") + "\n"
after = last_callable(new)
if before != after:
    raise SystemExit(f"entrypoint changed {before} -> {after}; refusing")
os.makedirs(os.path.join(POOL, name), exist_ok=True)
open(os.path.join(POOL, name, "main.py"), "w").write(new)
print(f"{name}: entrypoint={after}")
