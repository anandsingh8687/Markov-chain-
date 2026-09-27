cd /tmp/claude-0/-home-user-Markov-chain-/c59b383c-dabb-5acd-ba5b-4226a73ed24a/scratchpad; until grep -q "^DONE" v10/v18eval.log; do sleep 20; done
for n in fr17 fr17L ld0 ld5 ldh ldh5; do .venv/bin/python v10/gb.py eps_v17_all.txt pool/$n/main.py v10/g17b_$n.jsonl >> v10/v18eval.log 2>/dev/null; done
echo LDDONE >> v10/v18eval.log
