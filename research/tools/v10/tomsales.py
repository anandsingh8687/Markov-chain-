import sys, os, collections
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, 'v10'); from sales import run
if __name__ == "__main__":
    seeds = [int(x) for x in sys.argv[1].split(',')]
    with ProcessPoolExecutor(4) as ex:
        for seed, r, LOG in ex.map(run, [(s, sys.argv[2], sys.argv[3]) for s in seeds]):
            out = []
            for p in (0, 1):
                L = [(price, step) for pp, o, item, price, step in LOG if pp == p and o == 'SELL' and item == 'TOMATO']
                out.append(f"p{p} {len(L)}u ${sum(x for x,_ in L)/max(1,len(L)):.0f} first d{min((s for _,s in L), default=0)//24} max ${max((x for x,_ in L), default=0)}")
            print(seed, f"m {r[0]-r[1]:+.0f}", ' | '.join(out))
