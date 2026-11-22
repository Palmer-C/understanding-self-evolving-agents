"""Exact reported-table arithmetic and constructed workflow models; no model calls."""
from pathlib import Path
from fractions import Fraction as F
from itertools import product
import json
ROOT=Path(__file__).resolve().parents[1]
def makespan(jobs,workers=2):
    return min(max(sum(t for t,a in zip(jobs,assignment) if a==w) for w in range(workers))
               for assignment in product(range(workers),repeat=len(jobs)))
results={
 'AFlow_Table1_score_gap_vs_CoTSC':F('80.3')-F('76.0'),
 'AFlow_Table1_score_gap_vs_ADAS':F('80.3')-F('67.2'),
 'AFlow_Table1_relative_percent_vs_CoTSC':100*(F('80.3')/F('76.0')-1),
 'AFlow_Table1_relative_percent_vs_ADAS':100*(F('80.3')/F('67.2')-1),
 'AFlow_AppD_rounded_cost_ratio_percent':100*F('0.0291')/F('0.6371'),
 'AFlow_AppD_same_model_score_gap_pp':100*(F('0.9390')-F('0.8860')),
 'AFlow_AppD_same_model_cost_ratio':F('0.0291')/F('0.0127'),
 'ADAS_Table2_GSM8K_gap_pp':F('69.5')-F('43.6'),
 'ADAS_Table2_GSMHard_gap_pp':F('31.2')-F('18.0'),
 'independent_candidate_coverage':1-(1-F('0.6'))**3,
 'conditional_selector_success':F('0.7')*(1-(1-F('0.6'))**3),
 'amortization_equal_use_count':F(120,5-2),
 'retry_dispatch_bound':6*3,
 'two_nested_retry_layers_dispatch_per_logical_call':3*3,
 'equal2_duration_three_jobs_two_workers_optimum':makespan([2,2,2]),
 'equal2_duration_lower_bound':max(F(2),F(6,2)),
 'equal2_duration_plus_aggregation1':makespan([2,2,2])+1,
 'jobs322_two_workers_optimum':makespan([3,2,2])}
if results['conditional_selector_success']!=F('0.6552') or results['equal2_duration_three_jobs_two_workers_optimum']!=4:
    raise ValueError('Constructed workflow arithmetic mismatch')
# Test the ordinary nearest-rounding explanation using exact positive bounds.
# Four-decimal dollar displays have half-unit width 0.00005. The reported
# percentage 4.55 has half-unit width 0.005 percentage points.
cost_half_unit = F('0.00005')
ratio_lower = 100 * (F('0.0291') - cost_half_unit) / (F('0.6371') + cost_half_unit)
ratio_upper = 100 * (F('0.0291') + cost_half_unit) / (F('0.6371') - cost_half_unit)
reported_lower = F('4.55') - F('0.005')
reported_upper = F('4.55') + F('0.005')
assert ratio_lower > reported_upper
rounding_check = {
    'assumption': 'Positive costs rounded to nearest four decimal places; ratio rounded to nearest two percentage decimals',
    'cost_ratio_percent_bounds': [str(ratio_lower), str(ratio_upper)],
    'reported_ratio_percent_bounds': [str(reported_lower), str(reported_upper)],
    'bounds_overlap': False,
    'conclusion': 'Ordinary displayed rounding does not reconcile the figures under this assumption; discrepancy origin is unresolved',
    'historical_run_reconstructed': False,
}
old=json.loads((ROOT/'calculations/ch09-table-arithmetic-2026-09-30.json').read_text('utf-8'))
if [str(results[k]) for k in ['AFlow_Table1_score_gap_vs_CoTSC','AFlow_Table1_score_gap_vs_ADAS']]!=old['score_point_gaps']:
    raise ValueError('Historical rounded Table1 differences mismatch')
out=dict(identity='Reported rounded tables plus explicitly constructed probability/scheduling/cost models; not E06 or external experiment replication',api_calls=0,
         results={k:dict(exact=str(v),value=float(v)) for k,v in results.items()},
         rounding_check=rounding_check,
         scope=['Table1 relative percentages and point gaps distinct; heterogenous benchmark scores','4.55% original narrative vs4.56757% from rounded AppendixDvalues retained distinct','Candidate coverage assumes independent equal successp;selectorq conditional on existingcorrectanswer,selectiononly','Scheduling enumeration assumes independent nonpreemptive tasks and2identicalworkers;noqueueoverhead','Strict amortization integerthreshold41 follows equality40 underS120,a2,b5;notAFlowmeasuredcost'])
(ROOT/'analysis/workflow-arithmetic-reproduction.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n','utf-8')
print('18 reported-table/constructed quantities reconciled; API calls:0; E06 notrun')
