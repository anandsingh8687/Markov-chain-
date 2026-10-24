"""async_frac.py SNAPSHOT_TGZ... : fraction of 'async def' among all def in .py files (hosts: private repos <= 1.8%)."""
import sys, tarfile, re
for p in sys.argv[1:]:
    a = s = 0
    with tarfile.open(p) as tf:
        for m in tf:
            if m.isfile() and m.name.endswith('.py') and '/.git/' not in m.name:
                t = tf.extractfile(m).read().decode('utf-8', 'replace')
                a += len(re.findall(r'^\s*async\s+def\s', t, re.M)); s += len(re.findall(r'^\s*def\s', t, re.M))
    print(f'{p.rsplit("/",1)[-1]:55s} async={a:5d} def={s:6d} frac={a/max(1,a+s):.3f}')
