"""Exact reported-table arithmetic and constructed workflow models; no model calls."""
from pathlib import Path
from fractions import Fraction as F
from itertools import product
from decimal import Decimal
from math import comb
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calculations.historical_evidence import write_reproduction

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("-o", "--output", type=Path, help="Write a new file instead of updating the usual derived report.")
parser.add_argument("--aflow-archive", type=Path, help="Also audit a local copy of the authors' original results.tar.gz.")
args = parser.parse_args()

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
if ratio_lower <= reported_upper:
    raise ValueError("Displayed cost and percentage ranges no longer separate")
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

# Both workflows are already in the parent pool. With two choices the score
# component for the higher one reduces to a logistic probability.
raw_gap = Decimal("0.81") - Decimal("0.80")
alpha, uniform_weight = Decimal("0.2"), Decimal("0.3")
def higher_parent_probability(scale):
    return uniform_weight / 2 + (1 - uniform_weight) / (1 + (-alpha * scale * raw_gap).exp())

parent_probabilities = {
    "raw_scores": ["0.80", "0.81"],
    "alpha": str(alpha),
    "uniform_weight": str(uniform_weight),
    "reference_score_scale": 100,
    "higher_score_with_reference_scale": str(higher_parent_probability(100)),
    "higher_score_omitting_scale": str(higher_parent_probability(1)),
    "source": "FoundationAgents/AFlow 3f457218, DataUtils.select_round and _compute_probabilities",
    "scope": "Conditional on these two eligible parents; neither a historical draw nor an estimate of workflow quality.",
}

# Take the mean only after computing coverage for each task. Pooling first
# describes three draws with a common success probability.
task_probabilities = (F(3, 10), F(9, 10))
three_draw_coverage = [1 - (1 - p) ** 3 for p in task_probabilities]
results["task_average_independent_coverage"] = sum(three_draw_coverage) / len(three_draw_coverage)

# Three distinct sample indices chosen uniformly from five saved candidates,
# two of which passed. There is exactly one all-failing subset.
results["pass_at_3_from_five_saved_candidates"] = 1 - F(comb(3, 3), comb(5, 3))
results["pass_at_3_empirical_plugin"] = 1 - (1 - F(2, 5)) ** 3
out=dict(identity='Reported rounded tables plus explicitly constructed probability/scheduling/cost models; not E06 or external experiment replication',api_calls=0,
         results={k:dict(exact=str(v),value=float(v)) for k,v in results.items()},
         rounding_check=rounding_check,
         parent_selection_example=parent_probabilities,
         candidate_examples=dict(task_success_probabilities=[str(p) for p in task_probabilities],
                                 per_task_coverage=[str(c) for c in three_draw_coverage],
                                 saved_pool=dict(n=5, c=2, k=3, source="Chen et al., arXiv:2107.03374v2, Eq. 1; constructed counts")),
         scope=['Table1 relative percentages and point gaps distinct; heterogenous benchmark scores','4.55% original narrative vs4.56757% from rounded AppendixDvalues retained distinct','Candidate coverage assumes independent equal successp;selectorq conditional on existingcorrectanswer,selectiononly','Scheduling enumeration assumes independent nonpreemptive tasks and2identicalworkers;noqueueoverhead','Strict amortization integerthreshold41 follows equality40 underS120,a2,b5;notAFlowmeasuredcost'])
if args.aflow_archive:
    from calculations.aflow_archive import read_archive
    try:
        out["aflow_archive"] = read_archive(args.aflow_archive)
    except (OSError, ValueError) as error:
        parser.error(f"{error} See analysis/README.md for the cited source and expected input.")
try:
    write_reproduction(out, ROOT / "analysis/workflow-arithmetic-reproduction.json", args.output)
except OSError as error:
    parser.error(f"Could not write the report: {error}")
print(f"{len(results)} arithmetic results and two parent probabilities; no model calls.")
