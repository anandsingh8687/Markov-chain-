while pgrep -f "[g]hostrun.py gb1" >/dev/null; do sleep 20; done
.venv/bin/python ident.py ident1.jsonl prv_rain,tetsu_demand,guru_master3,thomas_2945,thomas_metav4,ahmed_v48,salem_2900,boat_v16rc5,fr_v3,fr_v5,my_v7,my_v6,my_v3 $(cat eps_v7.txt) > ident1.log 2>&1
.venv/bin/python ghostrun.py gr105.jsonl c_rt@107,c_rt@126,c_rt@103,c_rt@100 $(cat eps_r105.txt) > gr105.log 2>&1
.venv/bin/python ghostrun.py gr9.jsonl c_rt@128,c_rt@0,c_rt@12,c_rt@11 $(cat eps_r9.txt) > gr9.log 2>&1
