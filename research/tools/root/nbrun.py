"""Execute a notebook cell-by-cell until it writes a compilable main.py."""
import json, os, re, sys, glob, io, contextlib
nbdir = sys.argv[1]
nb = json.load(open(glob.glob(os.path.join(nbdir, '*.ipynb'))[0]))
work = os.path.join(nbdir, 'run'); os.makedirs(work, exist_ok=True); os.chdir(work)
ns = {'__name__': '__nbrun__'}
def done():
    if os.path.exists('main.py'):
        src = open('main.py', 'rb').read()
        try:
            compile(src, 'main.py', 'exec'); return True
        except SyntaxError:
            return False
    return False
for i, c in enumerate(nb['cells']):
    if c['cell_type'] != 'code': continue
    src = ''.join(c['source'])
    m = re.match(r'\s*%%writefile\s+(-a\s+)?(\S+)\s*\n', src)
    if m:
        with open(os.path.basename(m.group(2)), 'a' if m.group(1) else 'w') as fh:
            fh.write(src[m.end():])
    else:
        lines = [l for l in src.splitlines() if not l.lstrip().startswith(('!', '%'))]
        code = '\n'.join(lines)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                exec(compile(code, 'cell%d' % i, 'exec'), ns)
        except SystemExit:
            pass
        except Exception as e:
            print('cell%d raised %s: %s' % (i, type(e).__name__, str(e)[:90]))
    if done():
        n = len(open('main.py').read().splitlines())
        print('OK main.py from cell %d (%d lines)' % (i, n)); sys.exit(0)
print('NO main.py produced')
