# How to submit the paper (Kaggle Writeup) — deadline 2026-11-12 23:59 UTC

The Kaggle API cannot create writeups, so these steps are manual (about 10 minutes).

1. Open https://www.kaggle.com/competitions/gemma-4-developer-agent-paper and go to **Writeups → New Writeup**.
2. **Title:** `Sealed and Calibrated: a Fresh-Repository Gate for Changing a 12-Hour Gemma 4 Coding Agent`
   **Subtitle:** the line after "Subtitle:" in `writeup.md`.
3. **Body:** paste everything in `writeup.md` from `## Abstract` to the end. Markdown tables render in Kaggle writeups.
4. **Project links / attached resources.** Attach exactly these three. Private ones become public automatically after the deadline, which is intended:
   - notebook `anandsingh8687/sealedgate-161-companion` (reproduces every table);
   - notebook `anandsingh8687/sealedgate-161` (the task release: tasks, metadata, snapshots, wheels, graphs);
   - dataset `anandsingh8687/sealedgate-161-runs` (outcomes, leaderboard draws, trajectories, bundles, code).
5. **Never attach** any of the following. They contain copies of competition files (the sandbox `setup.py` and docker shims), which the rules forbid redistributing:
   - `evalset-v1-merge`
   - `evalset-v1-build-part1..4`
   - `evalset-v1-build-pilot`
   - the dataset `evalset-build-inputs`
   - any `gemma-agent-lab*` kernel
6. Save, then press **Submit** (top right). A saved draft that is not submitted is not judged.

Before submitting, check that the *pending* entries in `writeup.md` have been filled in: v33t's leaderboard draw (§3.3) and the v35 gate (§4.4). Claude updates them as results arrive.
