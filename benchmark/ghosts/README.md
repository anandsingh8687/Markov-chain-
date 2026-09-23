# Ghost opponents

`ladder_ghosts.json.gz` is a list of this account's own ladder episodes. Each
entry has `ep`, `seed`, `seat` (ours), `version`, `opponent`, `bank` (ours,
theirs) and `actions` (the opponent's recorded action for every turn). There
are 367 episodes:

* all v7 losses (110) and ties (39)
* 61 v7 wins
* about 40 losses each from v3, v4, v5 and v6

Games against our own other submission were dropped.

Replay them with `tools/ghost_bench.py`, and refresh them with
`tools/fetch_ghosts.py`.
