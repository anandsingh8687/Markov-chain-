while pgrep -f "[g]hostrun.py gb1" >/dev/null; do sleep 20; done
ONESIDE=1 .venv/bin/python field.py pool field_l2.jsonl c_l2min,c_l2l1,c_cxd44 c_cxd44,prv_rain,tetsu_demand $(cat seeds_l2.txt) > field_l2.log 2>&1
