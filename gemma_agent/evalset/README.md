# evalset-v1: unseen-repo eval set

Tasks from the SWE-rebench family (CC BY 4.0), post-2025-02, in small, mostly synchronous Python repos (at most 1.8% `async def`).
None come from public or famous repos, and there are at most 2 per repo. Each task is rebuilt for the competition's
py3.13 sandbox. A task is kept only when the official verifier passes the gold patch in 2 of 2 runs and fails the empty patch in 2 of 2 runs.

## Pipeline

| Step | Where | What |
|---|---|---|
| `filter.py`, `select.py` | local (done) | 420 candidates from 302 repos -> `candidates_v1.json` |
| `split_cands.py` | local (done) | `splits/part{1..4}.json` repo-disjoint shards; `split_manifest.json` seeded (20261018) repo-level A 60% / B 40%; `pilot.json` |
| `stage_inputs.py` | local | flat dir for the private dataset `anandsingh8687/evalset-build-inputs` (scripts, shards, candidate-row parquet subsets, run_official.py, docker shims, sandbox/setup.py) |
| `make_build_kernel.py --part partK` | local | private CPU kernel `evalset-v1-build-partK` (internet on; competition + wheelhouse attached) |
| `pipeline.py` | kernel | per candidate: `build.py` (bare mirror -> snapshot at base_commit on branch main -> uv py3.13 venv -> freeze -> `pip download` cp313 wheels) -> `emit_tasks.py` row -> `goldcheck.py` (gold1, empty1, gold2, empty2 through `run_official.py --phase2-only --deps image`; own data dir + TMPDIR per task) -> failures deleted at once -> `make_graph.py` -> `tasks_meta.jsonl` |
| `make_merge_kernel.py` / `merge.py` | kernel | `evalset-v1-merge`: combines the 4 build outputs (kernel sources) into one layout; retries the GitHub API for PR text and repo dates |

Text-format fixes from the 10-18 critique:
- **`problem_statement` is PR-style**, taken from the first source available:
  - V2 rows: `pr_description`, written as "title\n\nbody".
  - Leaderboard and rebench rows: the GitHub REST PR title and body (`gh_pr`).
  - Otherwise: the title and body of the merge or squash commit in the repo history (`git_pr`).
  - Last resort: the dataset's issue text (`issue`).
  - `tasks_meta.ps_source` records which source was used.
- **`hints_text` is always `""`.**
- **No `FAIL_TO_PASS` or `PASS_TO_PASS` in `tasks.jsonl`.** The verifier therefore requires every added `test_*`, as it does for the public tasks. The F2P and P2P lists are kept in `tasks_meta.jsonl`.
- **Repo age.**
  - `repo_created_at` is the GitHub `created_at`, or the date of the base commit's root commit when the API is unavailable (`repo_created_source`).
  - `repo_created_after_2025_01` and `ids_new_repos.txt` mark the subset of repos created after 2025-01.

GitHub API note: this session's `gh api` proxy only serves attached repos, so the PR text could not be prefetched locally. The kernels call the API without authentication (60/h per IP) and fall back to `git_pr`.

## Layout for the lab (`evalset-v1-merge` output, `evalset/`)

```
tasks.jsonl  tasks_meta.jsonl  rejects.jsonl  split_manifest.json  summary.json  gh_cache.json
ids_all.txt  ids_A.txt  ids_B.txt  ids_new_repos.txt
snapshots/<id>.tgz             wheels_by_task/<id>/*.whl (+ requirements.txt)
graphs/<name>_<commit>.json    embeddings/<name>_<commit>.npz   (name = repo.split('/')[-1])
sandbox/setup.py  docker/  wheels/README.txt
```

Lab use:
- Set `DATA_DIR` to the mounted `.../evalset-v1-merge/evalset`.
- For each task, set `wheels_dir = DATA_DIR/wheels_by_task/<id>` and give the task its own TMPDIR.
- Use the docker-like sandbox manager from `official/run_official.py` with `--deps image` semantics. This is the configuration the gold checks used.
- Tune on `ids_A.txt`. Run `ids_B.txt` only for sealed gates, and do not read its trajectories.

## Results of the 10-18/19 build

**Kernels (all private, CPU, internet on)**

| Kernel | Candidates | Valid | Repos | Hours |
|---|---|---|---|---|
| `anandsingh8687/evalset-v1-build-pilot` | 10 | 4 | – | 0.3 |
| `anandsingh8687/evalset-v1-build-part1` | 105 | 40 | 30 | 1.9 |
| `anandsingh8687/evalset-v1-build-part2` | 105 | 37 | 27 | 2.6 |
| `anandsingh8687/evalset-v1-build-part3` | 105 | 37 | 31 | 1.4 |
| `anandsingh8687/evalset-v1-build-part4` | 105 | 47 | 40 | 1.9 |
| `anandsingh8687/evalset-v1-merge` | – | **161** | **128** | – |

The pilot was a test run; the merge leaves it out. The merge output is 17 GB: snapshots 5.4 GB and wheels 10.3 GB.

**The merged set (161 valid tasks)**
- **Splits:** A 89, B 72. A/B was drawn at 60/40 over candidate repos, so the share of valid tasks drifts with how many survive in each.
- **Sources:**
  - 85 SWE-rebench-leaderboard, 73 V2, 3 SWE-rebench.
  - Repos: 95 have 1 task, 33 have 2.
- **Task dates:** 2025-02-02 to 2026-05-12.
- **`problem_statement` sources:**
  - 87 `gh_pr`, 73 `v2_pr`, 1 `issue` (movingpandas-469, whose PR fetch failed).
  - Median length 359 characters; the public median is 418.
- **Repos created on or after 2025-01:** only 2 (`ids_new_repos.txt`: mempalace-1004, mtplx-21). The "unseen repo" subset is too small to report on its own. Most candidates are new fixes in repos that already existed.
- **Gold-patch verify time:** median 49 s, max 584 s.
- **`_interface` tasks (6, `v1/ids_interface.txt`; A 2, B 4):** SWE-rebench-leaderboard variants whose tests need names or behaviour given only in the dataset's `interface` field (for example the private `_get_wait_time` in stravalib-709, the `original_participant_id` column in nwb2bids-347). Our rows use the PR text and drop that field, so these 6 may be harder than the hidden tasks. Report results with and without them.

**Rejects (259)**
- **Build stage (124):** mostly the async share over 1.8%. The rest:
  - deps install failures: setuptools-scm with no tags, `uv` `required-version`, monorepo subpackages, C++ backends;
  - wheel sets over 1.5 GB (optuna, SDV).
- **Check stage (135):** gold fails under the harness's own `pytest.ini`/env, for example:
  - DISPLAY or GUI imports;
  - a missing generated `_version.py`;
  - an added `test_*` that is not collected or is skipped (exit 0 but not resolved);
  - timeouts.

Small copies in this repo: `v1/ids_{all,A,B,new_repos}.txt`, `v1/summary.json`, `v1/tasks_index.jsonl` (per-task metadata without F2P/P2P).
