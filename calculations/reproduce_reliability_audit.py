"""Offline reliability diagnostics, exact geometry and paired noise statistics.

Local permission counterexamples use newly created dummy files only. They do
not test a live model or alter historical records. E12 remains unrun.
"""
from pathlib import Path
from fractions import Fraction as F
import hashlib,json,math,random,statistics,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.lab.archive_inputs import load_summary
from experiments.lab.e12_arms import noise_floor,degradation
from experiments.lab.e12_design_v2 import (Item,MemorySnapshot,measure_change,
    controlled_corruption,describe_pair,restore_new_snapshot,resource_totals)
from calculations.audit_e01_file_boundary import audit as boundary_audit

def require(ok,message):
    if not ok:raise ValueError(message)
run_id='E02-20260924T153511Z-421eac';s=load_summary(ROOT,run_id);vv=s['verdicts'];comparisons=[]
for base in ('arm_base','arm_formal'):
    require(set(vv[base])==set(vv['arm_noise']),'Paired tasks mismatch')
    ds=[statistics.mean(vv['arm_noise'][k])-statistics.mean(vv[base][k]) for k in vv[base]]
    rng=random.Random(0);n=len(ds)
    boot=sorted(statistics.mean(ds[rng.randrange(n)] for _ in range(n)) for _ in range(10000))
    row=dict(base=base,n=n,point=statistics.mean(ds),sd=statistics.stdev(ds),
             ci95=[boot[250],boot[9750]],precision_n=math.ceil((1.96*statistics.stdev(ds)/.03)**2),
             worse_tasks=sum(d<0 for d in ds),better_tasks=sum(d>0 for d in ds))
    require(row['precision_n']==490,'Noise-specific precision calculation changed')
    comparisons.append(row)
require(comparisons[0]['worse_tasks']==8 and comparisons[0]['better_tasks']==3,'Directional task counts changed')
require(s['feedback_quality']['arm_noise']['n_mismatch']==2,'Feedback perturbation count changed')
# Exact unit-vector dot products at 0,60,120 degrees; no rounded trig.
uv=F(1,2);vw=F(-1,4)+F(3,4);uw=F(-1,2)
d_uv,d_vw,d_uw=(1-v for v in (uv,vw,uw))
require((d_uv,d_vw,d_uw)==(F(1,2),F(1,2),F(3,2)) and d_uw>d_uv+d_vw,'Geometric counterexample changed')
require(noise_floor([[True,True]]*2,[[False,False]]*2)==0 and degradation([True]*2,[False]*2)==1,'Legacy dispersion example changed')
a=MemorySnapshot((Item('1','ABC','source','constructed'),));b=MemorySnapshot((Item('1','XYZ','source','constructed'),))
change=measure_change(a,b);require(change['net_bytes']==0 and change['modified_text_ids']==['1'],'Equal-length rewrite not visible')
with tempfile.TemporaryDirectory(prefix='reliability-snapshot-') as directory:
    p=Path(directory)/'restored.json';restored=restore_new_snapshot(a,p)
    require(restored['file_restored'] and MemorySnapshot.load(p)==a,'Snapshot restore failed')
    try:restore_new_snapshot(a,p)
    except FileExistsError:overwrite_blocked=True
    else:raise ValueError('Snapshot overwrite allowed')
corrupt,evidence=controlled_corruption();require(evidence['counterexample']['observed']==[2,3],'Range counterexample changed')
pair=describe_pair({'a':True,'b':True},{'a':True,'b':False},{'a':False,'b':False})
require((pair['D_raw'],pair['D_control'],pair['D_adjusted'])==(1,.5,.5),'Raw/control/adjusted distinction changed')
keys=('calls','transport_dispatches','known_prompt_tokens','known_completion_tokens')
totals=resource_totals(dict.fromkeys(keys,2),{'arm':dict.fromkeys(keys,3)})
unknown=resource_totals(dict.fromkeys(keys,2),{'arm':{**dict.fromkeys(keys,3),'known_prompt_tokens':None}})
require(totals['calls']==5 and unknown['known_prompt_tokens'] is None,'Exclusive resource accounting changed')
excerpt=json.loads((ROOT/'analysis/e12-legacy-bookkeeping-excerpt.json').read_text('utf-8'))
require(excerpt['original_sha256']=='2bc7b2125647f2a674113962b3af802d07001c33ce5197500c97a2700b9bdeb8','Legacy source identity changed')
historical=json.loads((ROOT/'calculations/e12-readiness-audit-2026-09-30.json').read_text('utf-8'))
require(excerpt['original_sha256'] in historical['source_sha256'].values(),'Legacy excerpt differs from historical audit identity')
env={'per_arm':{'control_no_update':{'D_mean':0}},'arm':'small'}
try:exec(compile(excerpt['code'],'quoted_legacy_bookkeeping','exec'),env)
except KeyError as exc:legacy=dict(exception='KeyError',missing_field=exc.args[0],scope=excerpt['scope'])
else:raise ValueError('Legacy missing-field defect no longer reproduced')
paths=['experiments/lab/e12_arms.py','analysis/e12-legacy-bookkeeping-excerpt.json','experiments/lab/e12_design_v2.py',
       'experiments/lab/run_e12_v2.py','experiments/lab/sandbox.py','experiments/lab/e01_v2_file_boundary.py',
       'calculations/e12-readiness-audit-2026-09-30.json','calculations/audit_e01_file_boundary.py']
out=dict(identity='Read-only historical statistics and local constructed reliability checks; not E12 or production security proof',
 api_calls=0,summary_sha256=hashlib.sha256((ROOT/'experiments/runs'/run_id/'summary.json').read_bytes()).hexdigest(),
 source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},noise_comparisons=comparisons,
 geometry=dict(unit_vector_angles=[0,60,120],distances=[str(d_uv),str(d_vw),str(d_uw)],adjacent_sum=str(d_uv+d_vw),
               meaning='One-minus-cosine is not a metric; fixed-target additive-increment and bounded reconciliation residual are extra assumptions'),
 legacy_bookkeeping_excerpt_check=legacy,local_file_boundaries=boundary_audit(),equal_length_change=change,
 snapshot_restoration=dict(**restored,overwrite_blocked=overwrite_blocked,behavior_equivalence_established=False),
 constructed_false_statement=evidence,paired_teaching_description=pair,exclusive_resources=totals,unknown_resources=unknown,
 selection_teaching=dict(independent_success_probability=.5,selected_initial_score=1,expected_retest=.5,expected_apparent_loss=.5),
 limits=['No natural model-error injection confirmed by a flipped label alone','No E12 paid run, universal degradation verdict or rollback success-rate estimate',
         'Dummy child-process write shows a legacy gap; tool fixes do not implement OS process isolation',
         'Noise precision_n uses task-level observed SD and 0.03 half-width, not a complete power design'])
(ROOT/'analysis/reliability-audit-reproduction.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
print('Two noise comparisons and490-task precision counts, exact cosine counterexample, legacy defect, snapshot and dummy permission boundaries checked; API calls:0')
