"""select.py OUT_JSON: merge SWE-rebench leaderboard/test and V2 candidates into one capped, de-biased candidate list."""
import json, sys, collections
import os
T = os.environ.get('EVALSET_T', '/tmp/claude-0/-home-user-Markov-chain-/420c290f-859c-5dc9-bf7e-f5ca9ed3f238/scratchpad/strat/evalset')  # dir with cand_{lb,rb,v2}.jsonl
PUBLIC = {'fastapi/fastapi', 'textualize/rich', 'psf/requests', 'encode/httpx'}
# very large / famous projects the base model has most likely seen in depth, plus async-heavy stacks
FAMOUS = {x.lower() for x in '''tobymao/sqlglot BerriAI/litellm astropy/astropy pandas-dev/pandas sympy/sympy dask/dask pydata/xarray
keras-team/keras PennyLaneAI/pennylane networkx/networkx ipython/ipython marimo-team/marimo ibis-project/ibis getmoto/moto
deepset-ai/haystack conan-io/conan zarr-developers/zarr-python pydicom/pydicom tox-dev/tox scipy/scipy numpy/numpy
modelcontextprotocol/python-sdk vyperlang/vyper huggingface/transformers pytest-dev/pytest python/mypy pylint-dev/pylint
sphinx-doc/sphinx django/django aio-libs/aiohttp modin-project/modin scrapy/scrapy pydantic/pydantic encode/starlette
All-Hands-AI/OpenHands langchain-ai/langchain run-llama/llama_index streamlit/streamlit Lightning-AI/pytorch-lightning
pytorch/ignite iterative/dvc Textualize/textual pre-commit/pre-commit apache/airflow home-assistant/core'''.split()}
rows = []
for f, src in (('cand_lb.jsonl', 'lb'), ('cand_rb.jsonl', 'rb'), ('cand_v2.jsonl', 'v2')):
    for l in open(f'{T}/{f}'):
        r = json.loads(l); r['src'] = src; rows.append(r)
seen, out, per = set(), [], collections.Counter()
reasons = collections.Counter()
# newest first so the cap keeps the most decontaminated tasks; V2 first within a date (PR-style text)
for r in sorted(rows, key=lambda r: (r['created_at'], r['src'] == 'v2'), reverse=True):
    iid = r['instance_id'].replace('_interface', '')
    repo = r['repo'].lower()
    if iid in seen: reasons['dup'] += 1; continue
    seen.add(iid)
    if repo in PUBLIC: reasons['public repo'] += 1; continue
    if repo in FAMOUS: reasons['famous'] += 1; continue
    if r['created_at'] < '2025-02-01': reasons['pre-cutoff'] += 1; continue
    if per[repo] >= 2: reasons['cap2'] += 1; continue
    per[repo] += 1; out.append(r)
print(dict(reasons), 'selected', len(out), 'repos', len(per), collections.Counter(r['src'] for r in out))
print('by month', sorted(collections.Counter(r['created_at'][:7] for r in out).items()))
json.dump(out, open(sys.argv[1], 'w'))
