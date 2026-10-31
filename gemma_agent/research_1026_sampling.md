# 10-26: sampling (temperature/top_k) evidence and repeat-draw data

Source: forum (all 263 topics), 35+ public notebooks, datasets muhammedidris28/gemma4-agent-runs,
dariushafshar/gemma-4-agent-public-config-draws, dmitriigluzdov LB observations. Read-only research.

## Temperature 1.0 / top_k 64 vs 0.2, thinking ON
- Idris (0.24 team): v19 (T 0.2) 0.18 -> v24 (T 1.0, top_k 64) 0.24; ONLY sampling differs (diff -r).
  One draw each; 3 tasks = ~1.4 SD of a difference (p ~0.17). His local runs never test T 1.0 on 31B.
- Ayush (746250), local 129 tasks, single runs: T0.2 48, T0.0 47, T0.4 51, T1.0 51; T1.0 summaries off 35;
  thinking off 23. Same-config repeats at T1.0: 55 vs 48.
- yiyu (747696), local 31 tasks: thinking ON v23 T0.2 18/31 vs v24 T1.0+top_k64 15/31 (single runs).
  Thinking OFF: T0.2 13,13 -> T1.0 17,17 (replicated), fewer empty patches.
- dmitriigluzdov LB draws, same bundle: T0.2 0.18 then 0.12 (identical); T0.4 0.12; T0 0.15.
- Other T1.0 LB draws (not isolated): zhukovoleksiy 0.15, lambdaderta 0.13 (low confidence).
- No source compares tokens/time by temperature with thinking on. No evidence of harm.
- Verified here: top_k reaches vLLM (extra_body.top_k merged with chat_template_kwargs and
  thinking_token_budget) - request capture of the compiled bundle.

## Repeat-draw variance (same bundle, LB)
- Budget-Fit V5, 10 draws: 10,10,11,9,11,10,11,8,11,9 (mean 10.0/58). Pooled within-config SD 1.56 tasks.
- Budget-aware V10 files: 13 then 7,7,8,9,10,10,10 (later mean 8.7). SuperAgent V8: 8,11,8,12.
- A team's best draw averages 2.72 tasks above its other draws. 0.24 teams: median 15.5 submissions.
- Our v29: 11, 9, 9; v30 9; v32 8.

## 0.24 teams
- Yurnero (17 subs, best ~Oct 1-2): no method disclosed; "~$1000 compute" for top 5-10.
- Yike Xu (7 subs, best ~Oct 7): nothing public. SAVE (19 subs, best ~Oct 20): nothing public.
- Idris (17 subs): all published (above); LoRA adapters lost locally (13 and 9 vs 18 of 46).
