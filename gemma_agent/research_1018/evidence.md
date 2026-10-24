# Evidence review: what our experiments actually show (2026-10-18)

Bottom line: no prompt change we tested in the lab has a measurable effect. The lab's ranking of bundles also does not match the leaderboard's. Both of our real leaderboard gains came from adopting public, LB-measured recipes. The roughly 3-task gap to the 0.22 bundle most plausibly sits in how its prompt locates code. v29 was designed to remove that part, based on lab data.

Scripts and data are in `(scratchpad)/strat/evidence_review/`:
- `load.py` builds `rows.json` (every lab12–18 run, with the local regrade where one exists).
- `ana.py` does the paired comparisons, `pooled.py` the replicate-pooled ones.
- `ana2.py` and `cat.py` sort failures by comparing each patch with the gold patch; per-run results are in `per_run_cat.json`.
- `beh2.py` measures behaviour from the traces in `tokan/recs.json`.

Grades: **F** = verified from files, **I** = inference.

## 0. Score grid correction (F)

The score is computed as `int(k*10000//58)//100`, where k is tasks solved out of 58:

| Score | Tasks |
|---|---|
| 0.15 | 9 |
| 0.17 | 10 |
| 0.18 | 11 |
| 0.22 | 13 |
| 0.24 | 14 |
| 0.25 | 15 |
| 0.31 | 18 |

- **Our real mean:** the two v29 draws were 11 and 9 tasks, a mean of 10.0, not the 9.5 in context.md.
- **Distance to the targets:** the user's 0.25 needs +5 tasks. "0.30" really means 0.31 (18 tasks, +8), because 17 tasks gives 0.29.
- **Distance to the 0.22 bundle:** it averages about 13, so we are about 3 tasks behind.

## 1. Which claims hold up statistically

Paired results, as later minus earlier with a 95% bootstrap interval over tasks and an exact McNemar p-value. Single paired lab runs:

| Comparison | Tasks | Difference | Wins / losses | 95% CI | p |
|---|---|---|---|---|---|
| v27 vs v22 (lab12) | 48 | +4 | 4 / 0 | [+1, +8] | 0.12 |
| v28 vs v27 (lab13 vs lab12) | 48 | −5 | 0 / 5 | [−9, −1] | 0.06 |
| v28t vs v28 | 48 | +1 | | [−2, +5] | 1.0 |
| v29 vs v27 (holdout) | 25 | 0 | 1 / 1 | [−3, +3] | 1.0 |
| v29c36 vs v29 (lab16a) | 48 | +2 | 3 / 1 | [−2, +6] | 0.62 |
| v30 vs v29 (lab18) | 73 | −2 | 3 / 5 | [−8, +3] | 0.73 |

The same bundle run twice gives these swings, which is pure noise:

| Replicate | Tasks | Difference | Wins / losses | 95% CI |
|---|---|---|---|---|
| v27, lab14 vs lab12 | 48 | −3 | | [−7, +1] |
| v29, run 18 vs run 15 | 73 | 0 | 4 / 4 | [−5, +6] |
| v29 across three runs | 48 | 21 / 19 / 18 | | |
| v29 across two runs | holdout 25 | 11 / 14 | | |

Pooling all replicates per bundle, with a bootstrap over tasks:

| Comparison | Difference (tasks) | 95% CI |
|---|---|---|
| v29 − v27 (73 tasks) | +2.3 | [−0.8, +5.8] |
| v29c36 − v29 | +2.2 | [−1.2, +5.8] |
| v30 − v29 | −1.8 | [−6.7, +2.8] |
| v27 − v22 | +2.5 | [−0.5, +6.0] |
| v28 − v27 (48 tasks) | −3.5 | [−7.0, −0.5] |

**How sensitive the lab is (F):**
- **Smallest detectable effect:** between replicate runs of one bundle, about 8 of 73 tasks flip. That gives a noise SD for a paired difference of about 2.8 tasks. At 80% power the smallest detectable effect is about 8 tasks out of 73, or about 4 tasks with 4 replicates per arm.
- **Expected effects are smaller:** every prompt change we tested was predicted at +1 to +3.
- **Few tasks can move:** over about 9 runs of the native-tool bundles:
  - 34 of 73 tasks were never solved;
  - 20 were always solved;
  - only 19 can move at all.
- **One lab task passes with no change:** fastapi_14851 passes with an empty patch in every run.

**What the claims amount to:**
- **Supported, on the leaderboard:**
  - Native tools with thinking (the public config) beat our skill-script family: v29 at 11 and 9 tasks vs v22 at 6 and 6, v26t at 5 and v25 at 5. That is about +4 to 5 tasks.
  - The 0.22 bundle beats v29 by about 3 tasks: more than 20 teams sit at 13, against our 11 and 9.
- **Supported, in the lab only:** v28 is worse than v27, by −3.5 tasks [−7.0, −0.5]. This is the only lab result whose interval excludes zero. It is also the result that steered us away from the structure that wins on the leaderboard (see section 4).
- **Not supported by any data, lab or leaderboard:**
  - v29 > v27, v29c36 > v29, v30 < v29, v28t vs v28.
  - Every "this rule fixed task X" claim.
- **The lab does not predict the leaderboard (F):**

  | Bundles | Lab difference | Leaderboard difference |
  |---|---|---|
  | v25 vs v22 | +4 | −1 |
  | v26t vs v29 | 20 vs 21 (tie) | 5 vs 10 |

  - Only v22 < v29 agrees.
  - Our only leaderboard jumps came from public measured recipes. The step from 0.10 to 0.165 was the public 0.18 config.

## 2. Why we sit near 10/58 while the 0.22 bundle gets about 13 with the same YAML

**The public A/B (verified by diff, ideas only):** flexonafft's v2 notebook says its earlier SuperAgent adaptation scored 0.18 (reported, not verified). A difflib comparison against `matterhorn3838__gemma-4-superagent.txt` shows that only two things changed:
- the **Locate** section;
- the **edit-recovery ladder**.

So the 0.18 to 0.22 step (about +2 tasks, and reproduced by many teams) is attributable to locating behaviour. v29, at about 10 tasks, behaves like the 0.18 version.

**Behavioural differences.** The v29 measurements come from 121 lab runs in `tokan/recs.json`.

| # | 0.22 prompt | v29 prompt | What v29 actually does (F) |
|---|---|---|---|
| 1 | Batches independent fixed-string greps for the symbols, their callers and test paths (git ls-files) in one call | One search per call; try one different string if empty | 7.6 searches per run; only 0.31 calls per run contain more than one grep |
| 2 | Reads the implementation plus one caller or test, up to 3 regions of about 40 lines per call | One region of at most 80 lines ("whole suspect function") | Reads a test file in only 17/121 runs (14%). Uses read_file 6.9 times per run although the prompt says to read with cat -n piped to sed, so compliance with mechanical rules is weak |
| 3 | No reproducer file; runs python -c once, only if the issue contains a snippet | Writes a /tmp/r.py reproducer, at most 2 calls before the first edit | 3.5 reproducer calls per run, 12.5% of the 28-call budget. 50 of 418 reproducer outputs show Type, Attribute, Import, Name or Syntax errors, even on repos the model knows |
| 4 | For a feature, copies the closest sibling including registration points (`__all__`, option lists, dispatch tables, imports) | Nothing | 36 of 193 failed runs (18.7%) edited the right place but missed a second gold .py file, the exact failure this rule targets |
| 5 | Writes a specification and an edge-case list (None, empty, negative, unicode, duplicates, defaults) and handles each; fix the cause, never special-case the example | "If the reproducer output is now right, make no further edits" plus "smallest change" | v29 stops at its own reproducer, but the hidden tests check the whole specification (I). The edge-case rule was dropped over two rich tasks (research_v30.md:72) |
| 6 | Finds tests with find, runs `pytest -x -q -k` under timeout 150, unittest fallback, fixes once from the traceback | "The test file for the module" with no discovery step; timeout 60; several rules for ignoring failures | 1.2 test calls per run. 24% of v29 runs ran pytest on a path that does not exist (research_v30.md) |
| 7 | Phased call plan (1–8 locate, 9–12 edit, 13–20 verify, no exploration after 20); checks patch_size > 0 after submitting and edits and resubmits if it is 0 | Edit by call 12, then submit and stop | First successful edit after call 12 in 42/121 runs; no successful edit in 32/121; empty patch in 19% of runs (the forum's Budget-Fit run: 11.6% no-edit, topic 749198); call cap exhausted in 51% of runs (22% solved vs 62% when not capped) |
| 8 | Decision rules: fix where the wrong value is produced, not where it is observed; after an empty search try one string, then edit; when stuck, make a different, smaller change | Partial | — |
| 9 | Few mechanics rules | Many mechanics rules (5000-character cut, backslashes, heredoc fallback) | Corrupted calls fell from 48 to 8 with no solve gain (holdout 11 vs 11) |

**Mechanism (I):** 51% of v29 runs hit the 28-call cap. So the binding constraint is information per call, and rows 1–2 buy more of it per call. On repos the model has not seen, the contract and the conventions have to come from tests and callers (rows 2, 4, 6). On fastapi and rich the model already knows them, which is why the lab cannot see these effects.

## 3. Estimated breakdown of hidden-set failures (inference)

**In the lab** (v29, v29c36 and v30; 193 failed runs, compared with gold, F):

| Lab failure category | Share of failed runs |
|---|---|
| No source edit | 28.5% |
| Wrong file | 13.5% |
| Right file, wrong region | 6.2% |
| Right region, wrong or incomplete semantics | 51.8% (18.7 points of it missed a second gold file) |
| Ended on the 8-minute or turn cap | 10% (overlaps the categories above) |

- The forum's Budget-Fit run on 112 public tasks splits similarly: 22% no-edit, 14% wrong file, 65% right file (topic 749198).
- In the lab, the edit reaches the gold region in 69% of runs, and 57% of those are solved: 0.69 × 0.57 ≈ 0.40.

**On the hidden set** the solve rate is about 0.17. Three ways to explain the drop:

| Scenario | Unlocated share of failures | Wrong-semantics share |
|---|---|---|
| Only localization gets worse | 84% | 16% |
| Both get worse equally (×0.65 each) | 66% | 34% |
| Only semantics gets worse | 37% | 63% |

The hosts vetted that a frontier model can solve each task from the issue text. That argues against the semantics-only scenario: in the lab, 10 of 33 failures needed information the issue does not give. Repos the model has not seen make localization harder.

**Central estimate for the hidden set:**

| Category | Share of failures |
|---|---|
| Never edited | about 30–40% |
| Wrong location | about 25–35% |
| Wrong or incomplete semantics | about 25–40% |
| Real-clock 8-minute timeout | about 3–8% |

- The timeout figure is low because in the real-clock lab17 runs only 1 of 24 v29 runs timed out; most end on the call cap, which matters more.
- Call-cap exhaustion is probably above 60%.

**Implication:** localization and "never edited" are probably the majority of hidden failures. Our lab is the setting where those failure modes are least visible.

## 4. The biggest single mistake

We used the fastapi/rich lab as the decision instrument and wrote prompt rules from individual lab failure traces, without ever checking that the lab ranks bundles the way the leaderboard does. Two pieces of evidence:
- **v29 was deliberately stripped of the 0.22 structure.** research_v29_design.md:100: "No v28 structure: no call-phase plan, no batched multi-search, no 40-line reads… Each of these is traced to a specific v28 loss." v30 then rejected "read one caller or test", the 0.22 verification steps and the edge-case rule on 1–2-task lab evidence (research_v30.md:59–72). That is the same locating behaviour the public A/B credits with 0.18 → 0.22.
- **The calibration control was never run.** Running the 0.22 bundle and Budget-Fit in the lab (research_oct15.md:246, Q9, about 4 quota-hours) would have shown whether the lab even orders 0.18 below 0.22. It stayed undecided, so every later lab gate rested on an unvalidated instrument.

Caveat: v28 is our 7.2 KB paraphrase, not their prompt. It was also slower (358 vs 268 thought tokens per call) and failed the 12-hour limit. Its lab loss is therefore not a clean test of the structure.

## 5. What we should stop doing

1. **Single paired lab runs on fastapi/rich as gates.** They cannot detect less than about 8 tasks of 73, and only 19 tasks can move.
2. **Writing rules from individual traced tasks** (split_cells inputs, 11194, 3043 and so on). They are fitted to repos the model already knows.
3. **Treating per-task flips as signal.** About 15% of tasks flip between identical runs.
4. **Adding mechanics rules as the main lever.** They cut corrupted calls with no solve gain, and the model ignores many of them (6.9 read_file calls per run against the prompt).
5. **Keeping fastapi_14851 in the scored lab set.** It passes empty in every run.
6. **Optimizing tokens and time beyond keeping about 5% margin under 12 hours.** That is a constraint, not a way to gain tasks.
7. **Building rules that move away from LB-measured public structure** on lab evidence alone.

Do instead:
- Start from the LB-proven 0.22 structure, written in our own words and kept to about v29's token cost: batched locate, caller/test reads, sibling registration, test discovery with -k, the patch_size check, no reproducer file.
- Build a lab of repos absent from the public set with empty and gold controls, as Gluzdov did with pyairtable, django-axes, polyfactory and bandit (31 tasks).
- Validate that lab by checking it ranks Budget-Fit below the 0.22 design before trusting it.
- Only then test search_similar_code there. The hosts say the private repos have full graph data (topic 745998), and we have never tested those tools on unfamiliar code.