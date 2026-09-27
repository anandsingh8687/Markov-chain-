"""hdiag8.py PLANNER T0 OPP N: per-product revenue gap (planner minus v14) summed over N seeds."""
import sys, os, re, collections, subprocess
from concurrent.futures import ProcessPoolExecutor
SP = os.getcwd()
def one(seed):
    out = subprocess.run([f'{SP}/.venv/bin/python', 'v12/hdiag.py', str(seed), sys.argv[1], sys.argv[2], sys.argv[3]],
                         capture_output=True, text=True, cwd=SP, env=dict(os.environ, HD_OUT=f'hd_{seed}.out'))
    return open(f'hd_{seed}.out').read()
if __name__ == '__main__':
    seeds = [int(x) for x in open('v10/s8.txt').read().replace(',', ' ').split()][:int(sys.argv[4])]
    with ProcessPoolExecutor(4) as ex: R = list(ex.map(one, seeds))
    tot = collections.Counter(); banks = []
    for txt in R:
        L = txt.split('\n')
        def parse(line):
            d = {}
            for m in re.finditer(r'(\w+):(\w+) (\d+)u avg (\d+)', line): d[(m.group(1), m.group(2))] = (int(m.group(3)), int(m.group(4)))
            return d
        a, b = parse(L[1]), parse(L[3])
        banks.append((float(L[0].split()[2]), float(L[2].split()[2])))
        for k in set(a) | set(b):
            ua, pa = a.get(k, (0, 0)); ub, pb = b.get(k, (0, 0)); sg = -1 if k[0].startswith('BUY') else 1
            tot[k] += sg * (ub * pb - ua * pa)
    n = len(R)
    print('mean bank v14 %.0f plan %.0f gap %+.0f' % (sum(x[0] for x in banks) / n, sum(x[1] for x in banks) / n, sum(x[1] - x[0] for x in banks) / n))
    for k, v in sorted(tot.items(), key=lambda kv: kv[1]): print(f"  {k[0][:4]}:{k[1]:10s} {v / n:+8.0f}/game")
