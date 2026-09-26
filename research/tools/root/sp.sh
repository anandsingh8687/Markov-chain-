#!/bin/bash
SP=/tmp/claude-0/-home-user-Markov-chain-/c59b383c-dabb-5acd-ba5b-4226a73ed24a/scratchpad
cd /home/user/Markov-chain-
rm -rf $SP/sp_out; mkdir -p $SP/sp_out
i=0
while IFS= read -r P; do
  i=$((i+1))
  $SP/.venv/bin/python tools/selfplay_ab.py "$P" main.py $SP/champion.py "$SEEDS" > "$SP/sp_out/$i.txt" 2>&1 &
done < "$1"
wait
cat $SP/sp_out/*.txt
