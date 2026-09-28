import json, sys
for n in sys.argv[1:]:
    R = [json.loads(l) for l in open(f'v10/gt_{n}.jsonl')]
    k = len(R)
    w_live = sum(r['me'] > r['top_live'] for r in R); w_rec = sum(r['me'] > r['top_rec'] for r in R)
    top10 = [r for r in R if r['score'] >= 2870]
    mb = sorted(r['me'] for r in R)[k // 2]
    print(f"{n:10s} n={k}  beat top live {w_live} ({100*w_live/k:.0f}%)  beat top recorded bank {w_rec} ({100*w_rec/k:.0f}%)  "
          f"median bank {mb:,.0f}  mean(me-top_rec) {sum(r['me']-r['top_rec'] for r in R)/k:+,.0f}  | top-10 teams: {sum(r['me']>r['top_rec'] for r in top10)}/{len(top10)}")
