"""make_graph.py WORKSPACE_DIR REPO_KEY OUT_GRAPH_JSON OUT_NPZ
Approximate the hosts' code graph: nodes = sync functions/methods/classes (dotted module path, source text),
edges = 'calls' (caller->callee resolved by name, plus callee->caller and class<->method), 256-d embeddings
(hashed token bag + fixed random projection, smoothed over neighbours, L2-normalised)."""
import ast, json, sys, hashlib, collections
from pathlib import Path
import numpy as np
ws, key, out_g, out_e = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
nodes, calls, by_short = {}, collections.defaultdict(set), collections.defaultdict(list)
for p in sorted(ws.rglob('*.py')):
    rel = p.relative_to(ws)
    if any(part.startswith('.') or part in ('build', 'dist', 'venv', 'node_modules') for part in rel.parts):
        continue
    try:
        src = p.read_text(errors='replace'); tree = ast.parse(src)
    except Exception:
        continue
    mod = '.'.join(rel.with_suffix('').parts)
    if mod.endswith('.__init__'): mod = mod[:-9]
    def visit(body, prefix, parent):
        for n in body:
            for fld in ('body', 'orelse', 'finalbody', 'handlers'):
                if isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While, ast.ExceptHandler)) and getattr(n, fld, None):
                    visit(getattr(n, fld), prefix, parent)
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                name = f'{prefix}.{n.name}'
                nodes[name] = ast.get_source_segment(src, n) or ''
                by_short[n.name].append(name)
                if parent: calls[parent].add(name)
                for c in ast.walk(n):
                    if isinstance(c, ast.Call):
                        f = c.func
                        nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                        if nm: calls[name].add(('?', nm))
                visit(n.body, name if isinstance(n, ast.ClassDef) else prefix, name if isinstance(n, ast.ClassDef) else parent)
    visit(tree.body, mod, None)
edges = set()
for s, targets in calls.items():
    for t in targets:
        cands = by_short.get(t[1], []) if isinstance(t, tuple) else [t]
        if isinstance(t, tuple) and len(cands) > 5: continue  # too ambiguous
        for c in cands:
            if c != s and c in nodes and s in nodes: edges.add((s, c)); edges.add((c, s))
g = dict(directed=True, multigraph=True, graph={'repo_name': key},
         nodes=[dict(name=n, text=t, id=n) for n, t in nodes.items()],
         edges=[dict(type='calls', source=s, target=t, key=0) for s, t in sorted(edges)])
json.dump(g, open(out_g, 'w'))
rng = np.random.default_rng(0); D = 256; H = 4096
proj = rng.standard_normal((H, D)).astype(np.float32)
import re
def vec(text):
    v = np.zeros(H, np.float32)
    for tok in re.findall(r'[A-Za-z_][A-Za-z0-9_]+', text):
        v[int(hashlib.md5(tok.lower().encode()).hexdigest()[:8], 16) % H] += 1
    return np.log1p(v) @ proj
names = list(nodes); E = np.stack([vec(n.replace('.', ' ') + ' ' + nodes[n]) for n in names]) if names else np.zeros((0, D), np.float32)
idx = {n: i for i, n in enumerate(names)}; nb = collections.defaultdict(list)
for s, t in edges: nb[s].append(idx[t])
E2 = np.stack([E[i] + 0.5 * E[nb[n]].mean(0) if nb[n] else E[i] for i, n in enumerate(names)]) if names else E
E2 /= np.linalg.norm(E2, axis=1, keepdims=True) + 1e-9
np.savez_compressed(out_e, **{n: E2[i].astype(np.float32) for i, n in enumerate(names)})
print(len(nodes), 'nodes', len(edges), 'edges')
