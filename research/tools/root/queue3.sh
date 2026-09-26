ONESIDE=1 .venv/bin/python field.py pool field_v9.jsonl v9_car15,v9_car15l25,v9_race46,v9_race42,v9_bud2k v8 $(cat seeds_v9.txt) > field_v9.log 2>&1
.venv/bin/python ghostrun.py gv9.jsonl v9_car15,v9_car15l25,v9_race46,v9_race42,v9_bud2k $(paste -sd, eps_v8.txt) > gv9.log 2>&1
.venv/bin/python ghostrun.py gv9b.jsonl v9_car15,v9_car15l25,v9_race46,v9_race42,v9_bud2k $(cat eps_v7lost.txt) > gv9b.log 2>&1
