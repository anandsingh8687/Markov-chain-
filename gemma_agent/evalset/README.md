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
