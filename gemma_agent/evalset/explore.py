import sys, json, collections, pandas as pd
for name in sys.argv[1:]:
    df = pd.read_parquet(name)
    print('=====', name, len(df), 'repos', df.repo.nunique())
    print(df.columns.tolist())
    print('created', collections.Counter(str(x)[:4] for x in df.created_at).most_common())
    ic = df.install_config
    py = collections.Counter((c or {}).get('python') if isinstance(c, dict) else None for c in ic)
    print('python', py.most_common(12))
    print('test_cmd', collections.Counter(((c or {}).get('test_cmd') or '')[:60] for c in ic).most_common(8))
    print('log_parser', collections.Counter((c or {}).get('log_parser') for c in ic).most_common(5))
    r = df.iloc[0]
    for k in df.columns:
        print('  ', k, '=>', repr(r[k])[:300])
    if 'meta' in df:
        ms = df.meta.apply(lambda m: m.get('llm_score') if isinstance(m, dict) else None)
        print('difficulty', collections.Counter(m.get('difficulty_score') if m is not None else None for m in ms))
        print('issue_text', collections.Counter(m.get('issue_text_score') if m is not None else None for m in ms))
        print('nmod', collections.Counter(m.get('num_modified_files') if isinstance(m, dict) else None for m in df.meta).most_common(6))
    print('top repos', df.repo.value_counts().head(15).to_dict())
    print('repos with 1-3 tasks', (df.repo.value_counts() <= 3).sum())
