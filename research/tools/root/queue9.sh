until grep -q DONE v10/v13mdx2.log 2>/dev/null; do sleep 20; done
for n in m10 m11; do .venv/bin/python v10/gb.py eps_v11_all.txt pool/$n/main.py v10/g11_$n.jsonl >> v10/v13mdx3.log 2>/dev/null; done
echo DONE >> v10/v13mdx3.log
