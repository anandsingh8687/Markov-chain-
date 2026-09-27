cd /tmp/claude-0/-home-user-Markov-chain-/c59b383c-dabb-5acd-ba5b-4226a73ed24a/scratchpad; until grep -q "^LDDONE" v10/v18eval.log; do sleep 20; done
S=/tmp/claude-0/-home-user-Markov-chain-/c59b383c-dabb-5acd-ba5b-4226a73ed24a/scratchpad
cd $S
echo "18079083 179898902 504223386 568023273 633728104 843176862 1045055387 1111071839 1216726709 1317279285 1424585681 1591463529 1710794471 1921798139 2032355799 2055232390" > seeds16.txt
.venv/bin/python v10/h2h.py seeds16.txt fr17L fr16,fr17,x6,g_haideptry_2965_latest_20260927 v10/h2h_fr17L.jsonl
.venv/bin/python v10/h2h.py seeds16.txt fr17L,fr17,fr16 g_boatlee_v16_rc5_v2,g_kaito_v25_v2,g_rayk_top_meta_v18 v10/h2h_gold.jsonl
echo H2HDONE >> v10/v18eval.log
