for n in b1 b2 b3 b4 b5 b6 b7; do .venv/bin/python v10/gb.py eps_v11_all.txt pool/$n/main.py v10/g11_$n.jsonl >> v10/v13sweep2.log 2>/dev/null; done
.venv/bin/python v10/gb.py eps_v10_127.txt pool/b1/main.py v10/g10_b1.jsonl >> v10/v13sweep2.log 2>/dev/null
echo DONE >> v10/v13sweep2.log
