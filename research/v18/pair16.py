import json, sys
def ld(f): return {json.loads(l)['ep']: json.loads(l) for l in open(f)}
b = ld('v10/g16_u16L.jsonl')
sc = {r['ep']: r['score'] for r in json.load(open('bands12.json'))['v16']}
for n in sys.argv[1:]:
    a = ld(f'v10/g16_{n}.jsonl'); c = [e for e in a if e in b]
    d = [a[e]['m'] - b[e]['m'] for e in c]
    print(n, len(c), 'won', sum(a[e]['m'] > 0 for e in c), 'vs', sum(b[e]['m'] > 0 for e in c), 'paired', round(sum(d) / len(d)),
          'better', sum(x > 1 for x in d), 'worse', sum(x < -1 for x in d), 'LW', sum(a[e]['m'] > 0 >= b[e]['m'] for e in c), 'WL', sum(b[e]['m'] > 0 >= a[e]['m'] for e in c))
    for lo, hi in ((0, 2400), (2400, 2500), (2500, 2600), (2600, 3300)):
        dd = [a[e]['m'] - b[e]['m'] for e in c if sc.get(e) is not None and lo <= sc[e] < hi]
        w = sum(a[e]['m'] > 0 for e in c if sc.get(e) is not None and lo <= sc[e] < hi); w0 = sum(b[e]['m'] > 0 for e in c if sc.get(e) is not None and lo <= sc[e] < hi)
        if dd: print('   ', lo, hi, len(dd), 'wins', w0, '->', w, 'paired', round(sum(dd) / len(dd)), 'better', sum(x > 1 for x in dd), 'worse', sum(x < -1 for x in dd))
