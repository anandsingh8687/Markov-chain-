for n in fr17L w18m w18rm w18rsm; do .venv/bin/python v10/gb.py eps_v17_all.txt pool/$n/main.py v10/g17_$n.jsonl >> v10/v18eval.log 2>/dev/null; done
for n in v18m v18rm v18rsm v18sm; do .venv/bin/python v10/gb.py eps_v16_all.txt pool/$n/main.py v10/g16_$n.jsonl >> v10/v18eval.log 2>/dev/null; done
echo DONE >> v10/v18eval.log
