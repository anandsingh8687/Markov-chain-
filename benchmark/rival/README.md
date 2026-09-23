# Rival benchmark

`main.py` is prvsiyan's public *The Soil Remembers Rain* (Apache-2.0),
unmodified. It is the strongest public agent found (1.000 in a 6-agent round
robin) and the base v8 is built on. A build that loses to its own parent is a
regression.

v8 against it: 4/4 on the gate seeds (median +$323) and 15/16 on fresh ladder
seeds (+$380 mean). See `docs/V8.md`.
