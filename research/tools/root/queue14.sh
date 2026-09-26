for n in x1 x2 x3 x4 x5; do .venv/bin/python v10/gb.py eps_v12_all.txt pool/$n/main.py v10/g12_$n.jsonl >> v10/v14x.log 2>/dev/null; done
for n in x1; do .venv/bin/python v10/gb.py eps_hi.txt pool/$n/main.py v10/ghi_$n.jsonl >> v10/v14x.log 2>/dev/null; done
echo DONE >> v10/v14x.log
