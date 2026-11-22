"""Read-only E05 archive/skill audit and exact teaching costs; no execution backend."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text('utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(condition,message):
    if not condition:raise ValueError(message)
run=ROOT/'experiments/runs/E05v2-20260929T143245Z-d7a8db';summary=read(run/'summary.json');config=read(run/'config.json')
source_identity={}
for name,digest in config['design']['source_sha256'].items():
    p=ROOT/('experiments/protocols/E05-v2.md' if name=='protocol' else 'experiments/lab/'+name)
    raw_bytes = p.read_bytes()
    raw_digest = hashlib.sha256(raw_bytes).hexdigest()
    lf_digest = hashlib.sha256(raw_bytes.replace(b'\r\n', b'\n')).hexdigest()
    raw_match = raw_digest == digest
    if raw_match:
        match_mode = 'raw'
    elif lf_digest == digest:
        match_mode = 'crlf_to_lf'
    else:
        match_mode = 'mismatch'
    source_identity[name] = dict(
        sha256=raw_digest, recorded_sha256=digest, match=raw_match,
        lf_sha256=lf_digest, accepted_match=match_mode != 'mismatch',
        match_mode=match_mode)
require(all(x['accepted_match'] for x in source_identity.values()),
        'Retained v2 source differs beyond CRLF/LF from recorded source digest')
sequences=[];totals=dict(calls=0,prompt_tokens=0,completion_tokens=0);trace_count=passed=0
for complete in sorted((run/'sequences').glob('*/complete.json')):
    seq=read(complete);traces=[];local={k:0 for k in totals}
    for event in seq['events']:
        p=complete.parent/event['trace'];t=read(p);trace_count+=1;passed+=t['verdict'] is True
        for k in totals:totals[k]+=t['usage'][k];local[k]+=t['usage'][k]
        system='\n'.join(s['content'] for s in t['steps'] if s['kind']=='system')
        tools=[s for s in t['steps'] if s['kind']=='tool_result'];writes=[s['detail']['args'] for s in tools if s['detail'].get('tool')=='write_file' and s['content'].startswith('已写入 ')]
        has_ref='Reference code passed its origin task only' in system
        require(has_ref==event['retrieved'],'Reference injection/event mismatch')
        traces.append(dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p),event=event,usage=t['usage'],
                           actual_tools=[dict(tool=s['detail']['tool'],args=s['detail']['args']) for s in tools],
                           reference=system.split('Reference code')[1] if has_ref else None,
                           successful_writes=writes,errors=[s['content'] for s in t['steps'] if s['kind']=='error'],
                           model_protocol_failures=[s['content'] for s in t['steps'] if s['kind']=='model' and ('DSML' in s['content'] or '\n"}' in s['content'])]))
    require(all(local[k]==seq['ledger'][k] for k in local),'Sequence usage does not reconcile')
    sequences.append(dict(complete=complete.relative_to(ROOT).as_posix(),sha256=sha(complete),arm=seq['arm'],k=seq['k'],ledger=seq['ledger'],final_skill=seq['final_skill'],traces=traces))
require((len(sequences),trace_count,passed,totals['calls'],totals['prompt_tokens'],totals['completion_tokens'])==(6,9,7,48,19031,1554),'Smoke totals differ')
require(summary['backend_retries_this_process']==0,'Recorded retry scope changed')
reuse={s['arm']:next(t for t in s['traces'] if t['event']['role']=='reuse') for s in sequences if s['k']==1}
require(reuse['static_skill']['successful_writes']==reuse['replan']['successful_writes'],'Published reuse case final code differs')
require('sum_inclusive' not in reuse['static_skill']['successful_writes'][0]['content'],'Source function unexpectedly executed/imported in final target')
teaching=read(ROOT/'calculations/ch08-cost-teaching-2026-09-30.json');ks=list(range(11));base=[5*k for k in ks];fixed=[12+2*k for k in ks];maint=[12+2*k+(12 if k>=6 else 0) for k in ks]
require((base,fixed,maint)==(teaching['replan'],teaching['static_skill'],teaching['maintained_skill']),'Teaching arrays differ')
figure=ROOT/'book/figures/generated/ch08-cost-teaching.pdf';require(sha(figure)==teaching['figure_sha256'],'Teaching figure differs from saved identity')
out=dict(identity='Independent arithmetic and semantic-event reconstruction of frozen archives; not E05 rerun or capability estimate',api_calls=0,legacy=dict(status='Not a reader reproduction input: original legacy run excluded from frozen package; dependent numeric table withdrawn from book; historical derived artifacts retained'),
         v2=dict(source_identity=source_identity,sequences=sequences,totals=totals,episodes=trace_count,passed=passed),
         teaching=dict(k=ks,replan=base,fixed_skill=fixed,maintained_skill=maint,figure_sha256=sha(figure)),
         interpretation=['Reference injected only in static reuse; direct function execution not observed','Dynamic origins fail protocol parsing before writes; no skill admission; successful reuse uses empty reference','No repair episodes observed; no causal reference-benefit estimate or P4 verdict','48 generate calls and zero recorded current-process retries; not independent network-service billing verification'])
(ROOT/'analysis/skill-audit-reproduction.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
print('6v2sequences/9traces/48calls,3reusecases and33teachingcostvalues reconciled; legacy table excluded; API calls:0')
