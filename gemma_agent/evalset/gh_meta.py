"""GitHub REST metadata with a JSON cache: PR title+body (for PR-style problem statements) and repo created_at.

Library: GH(cache_path).pr(repo, number) -> {'title','body'} | None ; GH.repo(repo) -> {'created_at', ...} | None
CLI:     python -I gh_meta.py CACHE_JSON CANDIDATES_JSON      (fills the cache for every candidate; resumable)

Auth: GITHUB_TOKEN / GH_TOKEN if set, otherwise unauthenticated (60 requests/h per IP). When the API answers with a
rate-limit 403/429 the client stops calling for the rest of the process (no long sleeps) and callers fall back to the
git-derived PR title/body (build.git_facts) or the issue text; the source used is recorded per task in tasks_meta.
Locally `gh api` can stand in (GH_USE_CLI=1), but this session's GitHub proxy only serves attached repositories.
"""
import json, os, re, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path


class GH:
    def __init__(self, cache_path):
        self.path = Path(cache_path)
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.lock = threading.Lock()
        self.token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        self.use_cli = os.environ.get('GH_USE_CLI') == '1'
        self.blocked = None  # reason string once rate limited
        self.calls = 0

    def _save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.cache, indent=0, sort_keys=True))
        tmp.replace(self.path)

    def _get(self, endpoint):
        if self.blocked:
            return None, self.blocked
        self.calls += 1
        if self.use_cli:
            x = subprocess.run(['gh', 'api', endpoint], capture_output=True, text=True, timeout=60)
            if x.returncode:
                return None, f'gh-cli {x.stderr.strip()[:200]}'
            return json.loads(x.stdout), None
        req = urllib.request.Request(f'https://api.github.com/{endpoint}', headers={
            'Accept': 'application/vnd.github+json', 'User-Agent': 'evalset-builder',
            **({'Authorization': f'Bearer {self.token}'} if self.token else {})})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode()), None
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None, 'http 404'
                if e.code in (403, 429):
                    rem = e.headers.get('X-RateLimit-Remaining')
                    self.blocked = f'rate-limited (http {e.code}, remaining={rem}, reset={e.headers.get("X-RateLimit-Reset")})'
                    return None, self.blocked
                err = f'http {e.code}'
            except Exception as e:  # network hiccup
                err = f'{type(e).__name__}: {e}'
            time.sleep(2 * (attempt + 1))
        return None, err

    def _cached(self, key, endpoint, pick):
        with self.lock:
            if key in self.cache and self.cache[key].get('ok'):
                return self.cache[key]
        data, err = self._get(endpoint)
        val = dict(ok=True, **pick(data)) if data is not None else dict(ok=False, error=err)
        with self.lock:
            if val['ok'] or err == 'http 404':
                self.cache[key] = val
                self._save()
        return val

    def pr(self, repo, number):
        v = self._cached(f'pr:{repo.lower()}#{number}', f'repos/{repo}/pulls/{number}',
                         lambda d: dict(title=d.get('title') or '', body=d.get('body') or '', merged_at=d.get('merged_at'),
                                        html_url=d.get('html_url')))
        return v if v.get('ok') else None

    def repo(self, repo):
        v = self._cached(f'repo:{repo.lower()}', f'repos/{repo}',
                         lambda d: dict(created_at=d.get('created_at'), stargazers_count=d.get('stargazers_count'),
                                        full_name=d.get('full_name'), license=(d.get('license') or {}).get('spdx_id')))
        return v if v.get('ok') else None


def pr_number(instance_id):
    m = re.search(r'-(\d+)(?:_interface)?$', instance_id)
    return int(m.group(1)) if m else None


if __name__ == '__main__':
    gh = GH(sys.argv[1])
    cands = json.load(open(sys.argv[2]))
    ok = 0
    for r in cands:
        if r.get('src') != 'v2' and gh.pr(r['repo'], pr_number(r['instance_id'])):
            ok += 1
        gh.repo(r['repo'])
        if gh.blocked:
            print('stopped:', gh.blocked); break
    print(f'{ok} PRs cached, {gh.calls} calls, cache size {len(gh.cache)}')
