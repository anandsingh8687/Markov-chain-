"""fetch_v2prs.py OUT_PARQUET [CANDIDATES_JSON]
Read only the light columns of nebius/SWE-rebench-V2-PRs (126k PR-style tasks, CC BY 4.0) over HTTP range requests
and keep the rows whose repo appears in the candidate list. Used to find the PR title+body (pr_description) for
SWE-rebench-leaderboard / SWE-rebench rows, whose problem_statement is issue text (the hidden tasks use PR text)."""
import json, sys
import fsspec, pyarrow.parquet as pq, pyarrow as pa
BASE = 'https://huggingface.co/datasets/nebius/SWE-rebench-V2-PRs/resolve/main/data/train-{:05d}-of-00003.parquet'
COLS = ['instance_id', 'repo', 'pull_number', 'pr_description', 'problem_statement', 'created_at']
out = sys.argv[1]
repos = None
if len(sys.argv) > 2:
    repos = {r['repo'].lower() for r in json.load(open(sys.argv[2]))}
fs = fsspec.filesystem('https')
tables = []
for i in range(3):
    with fs.open(BASE.format(i), block_size=8 << 20) as fh:
        pf = pq.ParquetFile(fh)
        print(i, pf.metadata.num_rows, 'rows', pf.metadata.num_row_groups, 'groups', flush=True)
        for g in range(pf.metadata.num_row_groups):
            t = pf.read_row_group(g, columns=['repo'])
            keep = [j for j, r in enumerate(t.column('repo').to_pylist()) if repos is None or r.lower() in repos]
            if not keep:
                continue
            t = pf.read_row_group(g, columns=COLS).take(pa.array(keep))
            tables.append(t)
            print(f'  group {g}: kept {len(keep)}', flush=True)
pq.write_table(pa.concat_tables(tables), out)
print('wrote', out, sum(t.num_rows for t in tables))
