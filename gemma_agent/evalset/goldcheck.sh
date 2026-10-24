#!/bin/bash
# usage: goldcheck.sh DATA_DIR ID [ID...]   (gold + empty patch through the official verifier, per-task wheels)
set -u
# Prototype (local) version; the Kaggle pipeline uses goldcheck.py (per-task TMPDIR, 2 rounds, no F2P fields).
S=${EVALSET_SP:-/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad}
PY=${EVALSET_HPY:-$S/wh31/venv/bin/python}
OFFICIAL=${EVALSET_OFFICIAL:-$(cd "$(dirname "$0")/.." && pwd)/official/run_official.py}
C=${EVALSET_COMPDATA:-$S/compdata}
D=$1; shift
for id in "$@"; do
  dt=$D/per_task/$id; mkdir -p $dt/sandbox $dt/tmp
  ln -sfn $D/tasks.jsonl $dt/tasks.jsonl; ln -sfn $D/snapshots $dt/snapshots
  ln -sfn $D/wheels_by_task/$id $dt/wheels; ln -sfn $C/docker $dt/docker
  ln -sfn $C/image313 $dt/image313; cp -f $C/sandbox/setup.py $dt/sandbox/setup.py
  for mode in gold empty; do
    TMPDIR=$dt/tmp timeout 2400 $PY -I $OFFICIAL --phase2-only $mode \
      --deps image --no-graphs --data $dt --ids $id --results $D/goldcheck/$mode --workdir $dt/tmp > $dt/$mode.log 2>&1
  done
  rm -rf $dt/tmp/swegemma_s*
  echo "$id gold=$(grep -o "resolved=[A-Za-z]*" $dt/gold.log | head -1) empty=$(grep -o "resolved=[A-Za-z]*" $dt/empty.log | head -1)"
done
