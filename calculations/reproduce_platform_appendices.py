"""Offline Appendix B/D/F records and synthetic interface demonstrations."""
from pathlib import Path
import collections, hashlib, json, math, sys, tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.lab.archive_inputs import required_summaries
from experiments.lab.cost_report import aggregate,row_total
from experiments.lab.e01_v2_offline import run_offline_demo
from calculations.demo_e01_public_memory import run as public_memory
from calculations.demo_e01_admission_receipts import run as receipts

def require(ok, message):
    if not ok:raise ValueError(message)

summaries=required_summaries(ROOT)
trace_path=ROOT/'experiments/runs/E01-20260923T152230Z-90acda/traces/grid4/sealed/classstate-07-r0/trace.json'
trace=json.loads(trace_path.read_text('utf-8'))
trace_record=dict(path=trace_path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                  usage=trace['usage'],event_rows=len(trace['steps']),event_kinds=dict(collections.Counter(x['kind'] for x in trace['steps'])),
                  verdict=trace['verdict'],verdict_source=trace['verdict_source'])
require((trace['usage']['calls'],trace['usage']['steps'],trace['usage']['prompt_tokens'],trace['usage']['completion_tokens'],len(trace['steps']),trace['verdict'])==(3,3,958,84,8,False),'Appendix D trace fields changed')
require(round(trace['usage']['wall_seconds'],2)==2.14,'Trace timing changed')
totals={}
for run,data in summaries.items():
    rows=[row_total(row) for row in aggregate(data).values()]
    totals[run]={key:sum(row[key] for row in rows) for key in ['episodes','calls','prompt_tokens','completion_tokens','wall_seconds']}
grand={key:sum(row[key] for row in totals.values()) for key in next(iter(totals.values()))}
require(tuple(grand[k] for k in ['episodes','calls','prompt_tokens','completion_tokens'])==(1680,7922,3795988,958399),'Historical cost totals changed')
unit={run:{key:row[key]/row['episodes'] for key in ['calls','prompt_tokens','completion_tokens','wall_seconds']} for run,row in totals.items()}
token_total=grand['prompt_tokens']+grand['completion_tokens'];prompt_share=100*grand['prompt_tokens']/token_total
require(token_total==4754387 and round(prompt_share,1)==79.8,'Token aggregation changed')
with tempfile.TemporaryDirectory(prefix='book-offline-platform-') as directory:
    result=run_offline_demo(Path(directory),'appendix-review')
    synthetic={key:result[key] for key in ['sequences','task_opportunities','research_actual_resources']}
    require(result['sequences']==6 and result['task_opportunities']==12,'Synthetic sequence design changed')
memory=public_memory();receipt=receipts()
require(memory['api_calls']==receipt['api_calls']==0,'Unexpected API count')
require(memory['final_storage_items']==8 and receipt['stored_items']==2,'Synthetic memory counts changed')
output=dict(identity='offline archived records and synthetic fixtures; not model performance or OS isolation',api_calls=0,
            trace_example=trace_record,historical_summary_totals=totals,grand_total=grand,per_episode=unit,
            token_total=token_total,prompt_token_percent=prompt_share,completion_token_percent=100-prompt_share,
            historical_E03_A_baseline='Unresolved verdict/usage conflict. Totals preserve summary scope; no corrected efficiency inference.',
            synthetic_sequences=synthetic,public_memory=memory,receipt=receipt)
(ROOT/'analysis/platform-appendices-reproduction.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps(dict(trace_events=8,trace_iterations=3,historical_episodes=1680,synthetic=synthetic,api_calls=0),ensure_ascii=False))
