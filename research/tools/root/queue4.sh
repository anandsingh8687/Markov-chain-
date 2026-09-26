while pgrep -f "^sh queue3.sh" >/dev/null; do sleep 20; done
.venv/bin/python ghostrun.py gh1.jsonl v9_hire $(paste -sd, eps_v8.txt) > gh1.log 2>&1
ONESIDE=1 .venv/bin/python field.py pool field_hire.jsonl v9_hire v8,prv_rain,tetsu_demand,my_v7 $(cat seeds_v9.txt) > field_hire.log 2>&1
.venv/bin/python ghostrun.py gh2.jsonl v9_hire all > gh2.log 2>&1
