until grep -q DONE v10/v14r.log 2>/dev/null; do sleep 15; done
for n in t1 t2 t4 t5 t6; do .venv/bin/python v10/gb.py eps_v12_all.txt pool/$n/main.py v10/g12_$n.jsonl >> v10/v14t.log 2>/dev/null; .venv/bin/python v10/gb.py eps_hi.txt pool/$n/main.py v10/ghi_$n.jsonl >> v10/v14t.log 2>/dev/null; done
echo DONE >> v10/v14t.log
