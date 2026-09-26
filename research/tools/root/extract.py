import json, os, re, sys, glob
root = sys.argv[1]
for nbdir in sorted(glob.glob(os.path.join(root, '*'))):
    nbs = glob.glob(os.path.join(nbdir, '*.ipynb'))
    if not nbs: continue
    nb = json.load(open(nbs[0]))
    out = os.path.join(nbdir, 'agent'); os.makedirs(out, exist_ok=True)
    written = []
    for cell in nb.get('cells', []):
        if cell.get('cell_type') != 'code': continue
        src = ''.join(cell.get('source', []))
        m = re.match(r'\s*%%writefile\s+(-a\s+)?(\S+)\s*\n', src)
        if not m: continue
        append, path = m.group(1), m.group(2)
        body = src[m.end():]
        dst = os.path.join(out, os.path.basename(path))
        with open(dst, 'a' if append else 'w') as fh:
            fh.write(body if body.endswith('\n') else body + '\n')
        written.append((os.path.basename(path), len(body.splitlines())))
    print('%-60s %s' % (os.path.basename(nbdir)[:60], written if written else 'NO %%writefile CELLS'))
