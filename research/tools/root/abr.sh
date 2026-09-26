#!/bin/bash
SP=/tmp/claude-0/-home-user-Markov-chain-/c59b383c-dabb-5acd-ba5b-4226a73ed24a/scratchpad
cd /home/user/Markov-chain-
rm -rf $SP/abr_out; mkdir -p $SP/abr_out
i=0
while IFS= read -r P; do
  i=$((i+1))
  $SP/.venv/bin/python tools/_eval_params.py "$P" main.py "$OPP" "$SEEDS" > "$SP/abr_out/$i.txt" 2>&1 &
done < "$1"
wait
cat $SP/abr_out/*.txt
