"""Competition-format task rows (exactly the 8 public fields) with PR-style problem statements.

Library: task_row(r, src, git_facts, gh) -> (row, ps_source)
CLI:     python -I emit_tasks.py IDS_JSON PARQUETS OUT_JSONL [--gh-cache FILE]

problem_statement, in order of preference (the hidden/public tasks carry the PR title + body, median ~420 chars):
  v2 rows        pr_description ("title\\nbody" -> "title\\n\\nbody")              ps_source = v2_pr
  lb/rb rows     GitHub REST pulls/N: "title\\n\\nbody"                          ps_source = gh_pr
                 merge/squash commit title (+ body) from the repo history       ps_source = git_pr
                 the dataset's issue text                                       ps_source = issue
hints_text is always "" (empty in all 129 public tasks). FAIL_TO_PASS / PASS_TO_PASS are NOT emitted: without them
the verifier requires every test_* added by test_patch, as for the public (and hidden) tasks.
"""
import json, sys

FIELDS = ('instance_id', 'repo', 'base_commit', 'patch', 'test_patch', 'problem_statement', 'hints_text', 'created_at')


def _iso(ts):
    """Any timestamp -> 'YYYY-MM-DDTHH:MM:SSZ' (UTC), the competition's created_at format."""
    from datetime import datetime, timezone
    s = str(ts).strip().replace(' ', 'T')
    try:
        d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return str(ts)
    d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    return d.strftime('%Y-%m-%dT%H:%M:%SZ')


def pr_text(title, body):
    title, body = (title or '').strip(), (body or '').strip()
    return f'{title}\n\n{body}' if body else title


def task_row(r, src, git=None, gh=None):
    get = (lambda k, d=None: r.get(k, d)) if hasattr(r, 'get') else (lambda k, d=None: getattr(r, k, d))
    iid, repo = get('instance_id'), get('repo')
    ps, source = get('problem_statement'), 'issue'
    prd = get('pr_description')
    if src == 'v2' and isinstance(prd, str) and prd.strip():
        t, _, b = prd.strip().partition('\n')
        ps, source = pr_text(t, b), 'v2_pr'
    else:
        got = None
        if gh is not None:
            from gh_meta import pr_number
            got = gh.pr(repo, pr_number(iid))
        if got and got.get('title'):
            ps, source = pr_text(got['title'], got.get('body')), 'gh_pr'
        elif git and git.get('git_pr_title'):
            ps, source = pr_text(git['git_pr_title'], git.get('git_pr_body')), 'git_pr'
    row = dict(instance_id=iid, repo=repo, base_commit=get('base_commit'), patch=get('patch'), test_patch=get('test_patch'),
               problem_statement=ps, hints_text='', created_at=_iso(get('created_at')))
    return row, source


if __name__ == '__main__':
    import pandas as pd
    ids = json.load(open(sys.argv[1]))
    df = pd.concat([pd.read_parquet(p) for p in sys.argv[2].split(',')]).drop_duplicates('instance_id').set_index('instance_id', drop=False)
    gh = None
    if '--gh-cache' in sys.argv:
        from gh_meta import GH
        gh = GH(sys.argv[sys.argv.index('--gh-cache') + 1])
    with open(sys.argv[3], 'w') as fh:
        for c in ids:
            row, src = task_row(df.loc[c['instance_id']], c.get('src', 'lb'), None, gh)
            fh.write(json.dumps(row) + '\n')
