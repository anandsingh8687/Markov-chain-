cd /tmp/claude-0/-home-user-Markov-chain-/c59b383c-dabb-5acd-ba5b-4226a73ed24a/scratchpad
until [ $(wc -l < v10/field3.jsonl) -ge 192 ]; do sleep 30; done
.venv/bin/python v10/fieldsum.py v10/field3.jsonl
NP=4 .venv/bin/python v10/h2h.py v10/s8.txt v10c prv_rain,p_herd-safe-v3-experimental-ri,tetsu_demand,p_kaggriculture-v40-challenger,p_pioneers-of-kaggle-town-cand,q_kaggriculture-7-turn-rescue-,q_kaggriculture-population-rob,q_kaggriculture-2887-score-fie,v9_open8,q_demand-preserving-turn-sale-,q_kaggriculture-harvest-ledger v10/field3c.jsonl
.venv/bin/python v10/fieldsum.py v10/field3.jsonl v10/field3c.jsonl
