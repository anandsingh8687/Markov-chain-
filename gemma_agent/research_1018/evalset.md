# Building a local eval set that predicts the hidden private-repo score better than the fastapi/rich lab

**Bottom line:** we can build one in 2–3 days. The source is the SWE-rebench family (CC BY 4.0, post-January-2025 tasks from about 300 smaller Python repos). The tasks go through the official harness on CPU, and we keep only those where the gold patch passes and an empty patch fails. I tested the whole pipeline on 21 candidates here. 8 came out valid. A full build should give about **130–190 valid tasks**.

## 1. What the hidden tasks look like (verified unless marked)

**Task format and grading**
- `tasks.jsonl` has 8 fields: `instance_id, repo, base_commit, patch, test_patch, problem_statement, hints_text, created_at`. It has **no** `FAIL_TO_PASS`/`PASS_TO_PASS` fields (compdata/tasks.jsonl: 129 rows; fastapi 67, rich 48, requests 13, httpx 1).
- The `Task` dataclass does accept `FAIL_TO_PASS`/`PASS_TO_PASS` (swegemma/models/task.py:117-124).
- Grading runs pytest on **every test file the `test_patch` touches**. The task passes only if pytest exits 0, the JUnit XML shows at least one passing test, and every required test passes. Required tests are F2P+P2P if present; otherwise the `test_*` functions added in `test_patch` (harness/verification.py:208-342, 619-665).
- So a public-dataset task is only usable if its **whole test file** passes under the gold patch.

**Problem statements are PR title + body, not issue text**
- Example: fastapi_14266 is the PR title repeated, then two "Ref:" links.
- Public median is 418 chars. SWE-rebench issue texts have a median of 1460 chars; SWE-rebench-V2 `pr_description` has 482 (482 is the post-cutoff Python subset; my filtered candidates come to 457).

**Snapshots**
- `snapshots/<instance_id>.tgz` is a tar of `./` including `.git`. It holds the full history up to `base_commit` on branch `main` (rich_3063 has 3799 commits). A `base_*.tgz` + `patches/` layout also works (deduplication.py:1311-1368).
- Public snapshots: median 95 MB, max 274 MB.

**Environment**
- python:3.13-slim plus pytest, pytest-timeout==2.1.0, typer and the common build backends (docker/Dockerfile.sandbox). No network.
- The repo is installed with `pip install ... --no-deps -e` (failure ignored) and put on `sys.path` through `workspace_paths.pth` (sandbox/setup.py:290-320).
- Every wheel under 16 MB is unpacked into site-packages, cached as `sp_base.tar` in `$TMPDIR/swegemma_sp_cache_v8` **by a fixed name, whatever the wheel set** (container_setup.py:233-392). Per-task wheel sets therefore need a separate TMPDIR per task.
- Phase 2 overwrites `pytest.ini`, so repo pytest settings are lost (for example `DJANGO_SETTINGS_MODULE`). That is why django-guardian failed its gold check.

**Code graphs**
- The format is simple: nodes are dotted function and class names with their source text, edges are `calls`, and embeddings are 256-dim float32 in an `.npz`.
- My AST builder (`make_graph.py`), tested against the official rich_610fd75 graph:
  - nodes: recall 1.000, precision 0.999
  - edges: recall 0.86, precision 0.36

**Host forum statements** (scratchpad/strat/forum/data/host_all.txt)
- The test set comes from private repos that are not public (line 159). None of the training repos are in it (line 230).
- Every hidden task passes 100% with the gold patch (lines 134, 230).
- Private tasks have code graphs, and none touches an `async def`. Private repos have **at most 1.8% async functions** (lines 165-169).

**Async fraction, measured by me**

| Repo | async share |
|---|---|
| fastapi | 23.4% |
| rich | 0.1% |
| requests | 0% |
| scrapy | 15% |
| qwenpaw | 30% |

So fastapi, which is 31 of our 73 lab tasks, is structurally unlike the hidden set.

**Model cutoff:** Gemma 4's training data ends in **January 2025** (ai.google.dev/gemma/docs/core/model_card_4).

**Inference:** the hidden repos are small-to-medium, mostly synchronous, pure-Python libraries whose dependencies install as py3.13 wheels and whose test files pass under the harness's own `pytest.ini`. Our current lab passes about 42% of tasks against about 16% on the leaderboard. That gap fits repos the model knows well (fastapi, rich) plus a set filtered for gold-passable tasks.

## 2. Datasets (from the Hugging Face API, 2026-10-18)

| Dataset | Licence | Size | Env spec | Fit |
|---|---|---|---|---|
| **nebius/SWE-rebench-leaderboard** | CC BY 4.0 | 860 Python tasks, 413 repos, 2025-01 to 2026-05 | `install_config` (python, install, pip_packages, test_cmd), F2P/P2P, docker_image | **Best** (fresh, curated) |
| **nebius/SWE-rebench-V2** | CC BY 4.0 | 32,079 tasks, 20 languages; Python 7,243; 839 post-cutoff in 261 repos | `install_config`, **`pr_description`**, LLM metadata (solvable code A, difficulty, categories) | **Best match for PR-style statements** |
| nebius/SWE-rebench (test/filtered) | CC BY 4.0 | 21,336 / 6,542 tasks, 3.4k repos | `install_config` + frozen `requirements` | Mostly before 2025 and py3.9; minor |
| nebius/SWE-rebench-V2-PRs | CC BY 4.0 | 126,300 tasks | `install_config`, `pr_description` | Large reserve; not assessed |
| SWE-bench-Live | MIT | 1,888 tasks, 223 repos, to 2025-09 | test_cmds, log_parser | Secondary |
| SWE-Gym | MIT | 2,438 tasks, 11 famous repos, before 2024 | none | Poor (memorised repos) |
| SWE-smith / R2E-Gym | MIT / Apache-2.0 | 59k / 4.6k, synthetic bugs and LLM-written issues | image name only | Different distribution |
| nvidia/Nemotron-SWE-v1 | CC BY 4.0 | trajectories, not tasks | none | Training only |

The repos underneath keep their own licences (the `license_name`/`license` columns). Using them privately for evaluation is fine.

The Docker images (swerebench/*) can't be used on Kaggle because there is no Docker. Instead we rebuild each environment as py3.13 wheels, which is what the hidden set requires anyway.

## 3. Pilot run here (official swegemma 0.2.11 Phase 2, docker-like sandbox, `--deps image`)

**Filtering** (`filter.py`, `select.py`) keeps a task only if:
- it was created on or after 2025-02-01;
- its Python is 3.10–3.13 and its install has no apt/conda/cargo steps;
- the gold patch changes only `.py` files (at most 3) and at most 150 lines;
- its tests are Python files;
- its repo is not public-set, not on a famous/async-heavy denylist, and has at most 2 tasks.

That leaves **420 candidates from 302 repos** (231 leaderboard, 176 V2, 13 rebench-test), spread across 2025-02 to 2026-05.

**Build** (`build.py`): bare clone → snapshot in the hosts' format → py3.13 uv venv → `uv pip freeze` → `pip download --only-binary` cp313/abi3/any wheels. For every built task, 100% of dependencies were available as wheels.

**Gold/empty check** (`goldcheck.sh` around `official/run_official.py --phase2-only`). Each check took 4–49 s.

| Pilot | Valid (gold passes, empty fails) | Failures |
|---|---|---|
| Leaderboard rows, 13 tasks | **6**: isort-2491, marshmallow-2925, sql-metadata-625, mpmath-992, cyclopts-633, llm-sandbox-101 | 1 build failure (rslearn); env failures: django settings, snapshot tmp-path mismatch, all tests skipped, subprocess crawl, optuna, playwright tar |
| V2 rows, 8 tasks | **2**: pynwb-2060, pdm-3575 | 3 py3.13 build failures (gensim C code and others); 2 missing test deps (pandas, httpx came from `-r requirements/dev.txt`, which I now parse); 1 corrupt tar (disk full); 1 accidentally a public rich task (now denylisted) |

The async ≤1.8% filter and the `-r` fix are now in `build.py`. **Inference:** a yield of about 45–55% of the 420 candidates gives roughly **130–190 valid tasks**, capped at 2 per repo.

## 4. Build plan (2–3 days)

**Day 1, Kaggle CPU notebook with internet** (no GPU quota). This machine has only about 3 GB of free disk, and 13 tasks took about 1.4 GB.
- `pip install pandas pyarrow uv`. Install swegemma/adk from the competition wheelhouse with `--no-deps`. Provide python3.13 (`uv python install 3.13` if the image lacks it).
- Upload `scripts/` and `candidates_v1.json`, then:
  - `python -I build.py candidates_v1.json /kaggle/working/evalset lb_test.parquet,v2_py_post.parquet,rebench_test_*.parquet --jobs 4`
  - `goldcheck.sh` on everything built (sequentially; its cleanup glob is shared).
  - `emit_tasks.py ... --ps pr --no-nodes` so the rows carry the same 8 fields as the competition and V2 tasks use the PR text.
  - `make_graph.py <ws> <repo>_<base_commit> graphs/... embeddings/...` for each kept task.
- Throughput: about 2 min per task across 4 cores, so 420 tasks take about 14 h. Split the list over 2 sessions.
- Output layout: `tasks.jsonl`, `tasks_meta.jsonl` (F2P, source, licence, difficulty), `snapshots/`, a deduplicated `wheels_pool/` plus `wheels_manifest/<id>.txt`, `graphs/`, `embeddings/`, `sandbox/setup.py`, `docker/`. Save it as a private dataset of roughly 5–10 GB.

**Day 2, lab kernel changes** (`lab/make_lab.py`, `lab/labworker.py`)
- Point `DATA_DIR` at the new dataset.
- Per job, build a `wheels_dir` of symlinks from the manifest and set a separate TMPDIR (to get around the fixed-name `sp_base` cache).
- Replace the stock `SubprocessManager` with `make_docker_like_manager` from `run_official.py`. The stock one skips wheel injection and exposes the host's site-packages. With this change, in-kernel grading is faithful and local regrading becomes optional.
- Smoke test on 5 tasks with the gold patch.

**Day 3, calibration** (about 4–5 GPU-quota hours per bundle for 150 tasks at concurrency 6)
- Run v29 (leaderboard about 0.165) and v22 (about 0.10). Accept the set if v29 lands at roughly 12–25% and beats v22 by about 6 points.
- Then freeze it: tune on set A (~60%) and gate on sealed set B (~40%), whose trajectories nobody reads.

**Keeping it unbiased**
- Post-cutoff dates; no public or famous repos; at most 2 tasks per repo.
- Async ≤1.8%, which matches the hosts' statement.
- PR-style problem statements; no F2P fields given to the grader, as in the public data.
- A repo-disjoint A/B split.

**Statistical power (inference):** with about 150 paired tasks and about 25% discordant pairs, the standard error of a pass-rate difference is about 4 points. That is enough to detect a real +8-point gain, which the 48-task lab (noise ±3 tasks) could not.

## Files
All under `(scratchpad)/strat/evalset/`:
- Scripts: `scripts/{filter.py, select.py, build.py, emit_tasks.py, goldcheck.sh, make_graph.py, async_frac.py, explore.py}`
- Candidate list: `candidates_v1.json` (420 tasks)
- Pilot outputs: `data/` and `data2/` (snapshots, wheels, `goldcheck/{gold,empty}/results.jsonl`)
- Downloads: `dl/` (lb_test.parquet, v2_py_post.parquet, rebench_test_*.parquet)

I deleted the repo mirrors and per-task temp folders to free disk; they can be recreated. I also ran `uv cache prune` and `pip cache purge` (about 0.7 GB freed).

Sources: [SWE-rebench dataset](https://nebius.com/blog/posts/swe-rebench-dataset), [SWE-rebench V2](https://nebius.com/blog/posts/meet-swe-rebench-v2), [V2 paper](https://arxiv.org/abs/2602.23866), [SWE-Gym paper](https://arxiv.org/pdf/2412.21139), [Nemotron-SWE-v1](https://huggingface.co/datasets/nvidia/Nemotron-SWE-v1), [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4), [Harbor SWE-rebench](https://hub.harborframework.com/datasets/swe-rebench).