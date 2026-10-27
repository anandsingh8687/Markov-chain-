"""crosswalk.py WRITEUPS META OUTCOMES OUT.csv: SealedGate-161 id -> overlap with zysbnd1 / toasterson / sslasme / RepoGraph-Verified, with their published per-task outcomes."""
import json, csv, glob, sys, collections
W, META, OUT, DST = sys.argv[1:5]
meta = [json.loads(l) for l in open(META)]
runs = collections.defaultdict(list)
for r in csv.DictReader(open(OUT)):
    if r['model'] == '31b' and r['task_set'] == 'evalset' and r['outcome'] != 'server_hang':
        runs[r['task_id']].append(int(r['resolved']))
z = collections.defaultdict(list)
for l in open(W + '/ds/zysbnd1__task-or-trajectory-release-slice/task_outcomes.jsonl'):
    d = json.loads(l); z[d['task']].append(1 if d['class'] == 'res' else 0)
tc = glob.glob(W + '/ds/toasterson__gemma4-agent-paper-release/**/heldout_tasks.csv', recursive=True)[0]
toast = {(r['repo'].lower(), r['instance_id'].rsplit('_', 1)[-1]): r for r in csv.DictReader(open(tc))}
ss = W + '/ds/sslasme__gemma4-paper-certified-benchmarks/full/'
sslists = {f[:-4]: {l.strip() for l in open(ss + f) if l.strip()} for f in ('rb41_verifiable.txt', 'h40.txt', 'pool_certified.txt', 'poolB_certified.txt')}
co = {r['id']: r for r in csv.DictReader(open(ss + 'certified_outcomes.csv'))}
dm = {d['repo'].lower() for d in map(json.loads, open(W + '/ds/debmalya84__repograph-verified-swe-tasks/priv_eval/priv_eval/tasks.jsonl'))}
rows = []
for m in meta:
    t = m['instance_id']; k = (m['repo'].lower(), t.rsplit('-', 1)[1]); tr = toast.get(k)
    v = runs.get(t, [])
    rows.append({'instance_id': t, 'split': m['split'], 'sg_31b_solved': sum(v), 'sg_31b_runs': len(v),
                 'zysbnd1_solved': sum(z[t]) if t in z else '', 'zysbnd1_runs': len(z[t]) if t in z else '',
                 'toasterson_id': tr['instance_id'] if tr else '', 'toasterson_sound': tr['sound'] if tr else '',
                 'toasterson_split': tr.get('split', '') if tr else '',
                 'sslasme_lists': ';'.join(n for n, s in sslists.items() if t in s),
                 'sslasme_ok_n': (co[t]['v2_ok'] + '+' + co[t]['t1_ok'] + '/' + co[t]['v2_n'] + '+' + co[t]['t1_n']) if t in co else '',
                 'repograph_same_repo': int(m['repo'].lower() in dm)})
with open(DST, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print('wrote', DST, len(rows), 'zysbnd1', sum(1 for r in rows if r['zysbnd1_runs'] != ''), 'toasterson', sum(1 for r in rows if r['toasterson_id']),
      'sslasme', sum(1 for r in rows if r['sslasme_lists']), 'repograph repo', sum(r['repograph_same_repo'] for r in rows))
