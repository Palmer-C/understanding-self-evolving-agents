"""Reconstruct archived E05 v2 case index without running a model or changing traces."""
from pathlib import Path
import argparse,hashlib,json
r=Path(__file__).resolve().parents[1];run=r/'experiments/runs/E05v2-20260929T143245Z-d7a8db'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('-o','--output',type=Path,help='Write a new case index at this path; existing files are refused. Default updates analysis/ch15-case-index-reproduction.json.')
args=parser.parse_args()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
rows=[]
for p in sorted((run/'sequences').glob('*/complete.json')):
 s=read(p);traces=[]
 for e in s['events']:
  q=p.parent/Path(e['trace']);t=read(q)
  traces.append({'path':q.relative_to(r).as_posix(),'sha256':digest(q),'task':t['task_id'],'calls':t['usage']['calls'],'verdict':t['verdict'],'retrieved':e['retrieved'],'role':e['role']})
 assert sum(t['calls'] for t in traces)==s['ledger']['calls']
 rows.append({'path':p.relative_to(r).as_posix(),'sha256':digest(p),'arm':s['arm'],'k':s['k'],'ledger':s['ledger'],'traces':traces,'has_final_skill':s['final_skill'] is not None})
all_traces=[t for a in rows for t in a['traces']]
assert len(all_traces)==9 and sum(t['calls'] for t in all_traces)==48 and sum(t['verdict'] for t in all_traces)==7
assert len({t['task'] for t in all_traces})==2
v={'identity':'read-only reconstruction of archived E05 v2 engineering smoke; no new API calls','run_id':run.name,'config_sha256':digest(run/'config.json'),'protocol_identity':'archived v2 configuration, not current v3','rows':rows,'totals':{'primary_episodes':9,'distinct_tasks':2,'families':1,'calls':48,'passed':7},'teaching_interaction':{'values':[.5,.55,.6,.62],'interaction':-.03},'scope':'training tasks only; trace evidence is not mechanism causality or P4 judgment'}
out=args.output if args.output is not None else r/'analysis/ch15-case-index-reproduction.json'
out.parent.mkdir(parents=True,exist_ok=True)
text=json.dumps(v,ensure_ascii=False,indent=2)
if args.output is not None:
    # Exclusive creation protects an earlier reader report, including concurrent writers.
    with out.open('x',encoding='utf-8') as stream:stream.write(text)
else:
    # Retain the historical derived-index default for existing callers.
    out.write_text(text,encoding='utf-8')
print('case index verified: 6 sequences, 9 traces, 48 calls, 7 passes, 2 tasks; 0 new calls')
print('index_written_to',str(out))
