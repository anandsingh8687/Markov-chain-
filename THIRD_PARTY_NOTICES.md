# Third-party notices

`main.py` (v10), `candidates/`, `benchmark/incumbent/main.py` and `benchmark/rival/main.py` are
derived from public Kaggle notebooks released under the Apache License, Version
2.0. Each file keeps its upstream attribution header and the full license text
unchanged. The v10 additions are appended at the end of `main.py` and described in `docs/V10.md`.

| File | Upstream | Changes here |
| --- | --- | --- |
| `main.py` (v13) | tetsutani, *Demand-Preserving Turn Sale Timing* (public Kaggle notebook, Apache-2.0, 2026-09-24; also republished as cha22, *Master Engine V3* and *Multi-Route Farming Agent*). Its lineage, credited inside the file, includes prvsiyan, thomastschinkel, yhay81, destbreso, aurax7, Ahmed Berat Ozer, Dmitrii Gluzdov, shiiin9, the pipe18 and 2695 authors and the kaggle-environments contributors. | Appended: level-2 counter D (from this repo's v8), the morning-hire reserve (from v9) and a guarded entrypoint. v11 changes the look-ahead of the base's lead-sellers from day 18 (`_LATE_*` constants); v12 retunes them and adds the RDX rival-dump layer; v13 adds the MDX peak-sell layer |
| `candidates/v10c`, `candidates/v10d`, `candidates/v11` | as `main.py` | v10c: hire reserve only. v10d is v10. `candidates/v11` is identical to `main.py` |
| `benchmark/incumbent/main.py` | v10, this account's previous submission (same upstream as `main.py`). Before that, v9 (prvsiyan, *Kaggriculture Frontier: The Soil Remembers Rain*, plus the v8/v9 layers; the buy-8/sell-3 opening is from arsgorynich, *Herd Safe v3 Experimental Risk Aware Feed*, Apache-2.0) | none |
| `benchmark/rival/main.py` | tetsutani, *Demand-Preserving Turn Sale Timing*: v10's base, unmodified | none |

`benchmark/ghosts/ladder_ghosts.json.gz` holds opponent actions taken from
this account's own public ladder replays on Kaggle.

Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0
