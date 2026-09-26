cd /tmp/claude-0/-home-user-Markov-chain-/c59b383c-dabb-5acd-ba5b-4226a73ed24a/scratchpad
until [ $(wc -l < v10/g2.jsonl) -ge 300 ]; do sleep 30; done
.venv/bin/python -c "
import json
S=sorted({r['seed'] for r in map(json.loads,open('v10/g2.jsonl')) if sum(s in('PIZZA_SHOP','FARMERS_MARKET') for s in r['s18'])==2})
open('v10/g2seeds.txt','w').write(','.join(map(str,S)));print(len(S))"
.venv/bin/python v10/h2h.py v10/g2seeds.txt v9_open8 prv_rain v10/g2base.jsonl
.venv/bin/python v10/g2eval.py
