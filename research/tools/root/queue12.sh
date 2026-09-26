while pgrep -f "gb.py eps_hi.txt pool/p1" >/dev/null; do sleep 15; done
for n in r1 r2; do .venv/bin/python v10/gb.py eps_hi.txt pool/$n/main.py v10/ghi_$n.jsonl >> v10/v14r.log 2>/dev/null; done
echo DONE >> v10/v14r.log
