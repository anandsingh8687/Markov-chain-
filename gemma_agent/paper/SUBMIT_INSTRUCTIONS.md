# How to submit the paper (Kaggle Writeup) — deadline 2026-11-12 23:59 UTC

The Kaggle API cannot create writeups, so these steps are manual (about 10 minutes).

1. Open https://www.kaggle.com/competitions/gemma-4-developer-agent-paper and go to **Writeups → New Writeup**.
2. **Title:** `SealedGate-161: a Calibrated Fresh-Repository Gate for Changing a Gemma 4 Coding Agent` (the first line of `writeup.md`, without the `#`)
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

All results are in (labs 17–28s, last update 10-31). If the editor's word counter shows more than 3,000 words, tell Claude before submitting; the file is kept at or under 3,000 words counted as tokens containing a letter or digit.
