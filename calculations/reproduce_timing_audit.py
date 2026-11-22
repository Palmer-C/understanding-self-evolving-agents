"""Offline timing diagnostics and exact teaching arithmetic; never an E11 run.

Historical outputs and raw records are read, not replaced. No model backend is
constructed. A single valid historical drift window is distinct from warmup.
"""
from pathlib import Path
from fractions import Fraction as F
from itertools import product
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.lab.trigger_signals import load_train_episodes,analyze,drift
from experiments.lab.e11_arms import signals_for,delta_widening
from experiments.lab.e11_timing_v2 import TimingController
from experiments.lab.archive_inputs import load_summary

def require(ok,message):
    if not ok:raise ValueError(message)

run_id='E01-20260923T152230Z-90acda'
summary=load_summary(ROOT,run_id)
run=ROOT/'experiments/runs'/run_id
episodes=load_train_episodes(run,'grid4');lessons=summary['memory']['grid4_lessons']
require(len(episodes)==len(lessons)==8,'Eight paired training records required')
require([x['source_task'] for x in lessons]==[x['task_id'] for x in episodes],'Source task alignment changed')
require([x['source_verdict'] for x in lessons]==[x['verdict'] for x in episodes],'Source verdict alignment changed')
require([x['index'] for x in lessons]==list(range(8)),'Source lesson order changed')
require(all(isinstance(x['text'],str) and x['text'].strip() for x in lessons),'Missing actual lesson text')
verdicts=[x['verdict'] for x in episodes]
replay=analyze(run,'grid4',[x['text'] for x in lessons])
historical=ROOT/f'experiments/results/triggers-{run_id}.json'
require(replay==json.loads(historical.read_text('utf-8'))['signals'][0],'Historical signal replay changed')
require(drift(verdicts)==[0.]*7+[.5],'Historical warmup scope changed')
signed=F(sum(not v for v in verdicts[4:]),4)-F(sum(not v for v in verdicts[:4]),4)
require(signed==F(-1,2),'Historical shift direction changed')

# Exhaustive probabilities for explicitly constructed, independent failures.
def probability(n,p,predicate):
    return sum((p**sum(xs)*(1-p)**(n-sum(xs)) for xs in product((0,1),repeat=n) if predicate(xs)),F())
window=lambda xs:abs(sum(xs[:2])-sum(xs[2:]))>=1
probs={'window_half':probability(4,F(1,2),window),
       'window_quarter':probability(4,F(1,4),window),
       'run2_in8_quarter':probability(8,F(1,4),lambda xs:any(a and b for a,b in zip(xs,xs[1:]))) }
require(list(probs.values())==[F(5,8),F(69,128),F(20905,65536)],'Exact teaching probabilities changed')
teaching=[True]*4+[False]*3+[True];decisions={}
for arm in ('per_task','periodic','event'):
    ctl=TimingController(arm,8)
    rows=[ctl.observe(episode_id=f'teaching-{i}',verdict=v,task_text='same public input') for i,v in enumerate(teaching)]
    decisions[arm]=dict(attempt_positions=[i+1 for i,r in enumerate(rows) if r['decision']=='attempt_reserved'],
        reasons_by_position={str(i+1):r['trigger_reasons'] for i,r in enumerate(rows)},terminal=rows[-1]['decision'])
require([x['attempt_positions'] for x in decisions.values()]==[[1,2,3,4],[2,4,6],[1,5,6,7]],'Teaching schedules changed')
legacy=signals_for([True,False,False,False],lesson_texts=['one stored lesson'])
require(legacy==[1.0],'Legacy alignment example changed')
base=[True,True,False,False];arm=[True]*4
require(delta_widening(base,arm)==1 and delta_widening(base*2,arm*2)==0,'Legacy repeat example changed')
arithmetic={'D_MEM_Table1_cost_ratio':F(1648,319),
 'D_MEM_Table1_reduction_percent':100*(1-F(319,1648)),
 'D_MEM_Table3_v1_reduction_percent':100*(1-F(489,1648)),
 'D_MEM_Table3_v3_over_v4_cost':F(531,319),
 'JitRL_Table9_WebRL_over_JitRL':F(9900,290),
 'JitRL_Table13_WebRL_minus_JitRL_score_pp':F('46.06')-F('40.88'),
 'A_MAC_Table1_relative_F1_gain_percent':100*(F('0.583')/F('0.541')-1),
 'A_MAC_Table1_latency_reduction_percent':100*(1-F(2644,3831)),
 'gate_teaching_strict_rate_upper_bound':1-F(1,10)-F(50,100*10),
 'quality_ratio_A':F(8,10),'quality_ratio_B':F(6,5),
 'JitRL_AppendixR_estimated_training_dollars':F(154*64)}
require(arithmetic['gate_teaching_strict_rate_upper_bound']==F(17,20),'Gate threshold changed')
paths=[historical,run/'summary.json',ROOT/'experiments/lab/trigger_signals.py',
 ROOT/'experiments/lab/e11_arms.py',ROOT/'experiments/lab/e11_timing_v2.py',
 ROOT/'experiments/lab/e11_resources_v2.py',ROOT/'experiments/lab/run_e11_v2.py',
 ROOT/'calculations/ch13-calculations-2026-09-30.json']+sorted((run/'traces/grid4/train').glob('*/trace.json'))
out=dict(identity='Historical fixed-input diagnostics and teaching arithmetic; no E11 quality/resource comparison',
 api_calls=0,source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
 historical_replay=replay,warmup_positions=list(range(1,8)),valid_window_positions=[8],
 valid_signed_failure_difference=str(signed),valid_absolute_failure_difference=str(abs(signed)),
 probabilities={k:dict(exact=str(v),decimal=float(v)) for k,v in probs.items()},
 teaching_schedule=decisions,legacy_defects=dict(four_outcomes_one_lesson_signal=legacy,one_repeat_widening=1,two_flattened_repeats_widening=0),
 source_and_teaching_arithmetic={k:dict(exact=str(v),decimal=float(v)) for k,v in arithmetic.items()},
 limits=['Historical novelty is generated-lesson novelty, not v2 public-input novelty',
         'Constructed schedules fix outcomes and cannot estimate counterfactual performance',
         'No live requests, no E11/E12 execution, no paper-code replication',
         'Calls and dispatches can be hard bounded; token/wall soft stops may overshoot; unknown usage remains unknown'])
target=ROOT/'analysis/timing-audit-reproduction.json'
target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
print('Eight historical training records, three exact probabilities, three schedules, two legacy defects and12 arithmetic quantities checked; API calls:0')
