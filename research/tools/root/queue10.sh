until grep -q DONE v10/v13mdx3.log 2>/dev/null; do sleep 20; done
.venv/bin/python v10/gb.py eps_v11_all.txt pool/p1/main.py v10/g11_p1.jsonl >> v10/v13mdx4.log 2>/dev/null
for n in n6 n5 p1; do .venv/bin/python v10/gb.py eps_v10_127.txt pool/$n/main.py v10/g10_$n.jsonl >> v10/v13mdx4.log 2>/dev/null; done
echo DONE >> v10/v13mdx4.log
