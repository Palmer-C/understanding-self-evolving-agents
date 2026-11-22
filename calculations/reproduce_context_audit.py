"""Exact teaching arithmetic and reported-table checks, without model calls.

This does not reproduce ACE/GEPA experiments. Constants retain the identities of
their source tables; historical dated outputs are read, never overwritten.
"""
from pathlib import Path
from fractions import Fraction as F
from math import comb
import json

ROOT=Path(__file__).resolve().parents[1]
cdf=[F(sum(comb(4,j) for j in range(k+1)),16) for k in range(4)]
selection=[dict(candidates=m,exact=str(sum((1-p**m for p in cdf),F())/4),
                mean=float(sum((1-p**m for p in cdf),F())/4)) for m in [1,2,4,8]]
historical=json.loads((ROOT/'calculations/ch07-calculations-2026-09-30.json').read_text('utf-8'))
if any(r['exact']!=old['exact'] for r,old in zip(selection,historical['selection_rows'])):
    raise ValueError('Exact selection arithmetic differs from historical record')
differences={
    'GEPA_Table1_aggregate_vs_GRPO':F('54.85')-F('48.91'),
    'GEPA_Table1_aggregate_vs_MIPROv2':F('54.85')-F('47.84'),
    'GEPA_Table1_HotpotQA_vs_GRPO':F('62.33')-F('43.33'),
    'GEPA_Table1_AIME_vs_MIPROv2':F('32')-F('20'),
    'GEPA_Table2_transfer_vs_baseline':F('62.03')-F('53.03'),
    'GEPA_Table2_target_optimized_vs_transfer':F('65.22')-F('62.03'),
    'ACE_Table2_FiNER_online_unlabeled':F('67.3')-F('70.7'),
    'ACE_Table2_Formula_online_unlabeled':F('78.5')-F('67.5'),
    'ACE_Table2_average_online_unlabeled':F('72.9')-F('69.1')}
cost={
    'ACE_Table4_offline_latency_reduction_percent':100*(1-F(9517,53898)),
    'ACE_Table4_offline_rollout_reduction_percent':100*(1-F(357,1434)),
    'ACE_Table4_online_latency_reduction_percent':100*(1-F(5503,65104)),
    'ACE_Table4_online_token_cost_reduction_percent':100*(1-F('2.9')/F('17.7')),
    'ACE_Table12_rollout_increase_percent':100*(F(2075,1455)-1),
    'ACE_Table12_input_reduction_percent':100*(1-F(39250925,204076096)),
    'ACE_Table12_output_reduction_percent':100*(1-F(307128,1870188)),
    'ACE_Figure2_context_reduction_percent':100*(1-F(122,18282)),
    'GEPA_best_appearance_rollout_ratio':F(24000,678),
    'GEPA_reported_total_budget_rollout_ratio':F(24000,3593)}
rounded_expectations=[82.3,75.1,91.5,83.6,42.6,80.8,83.6,99.3]
if [round(float(x),1) for x in list(cost.values())[:8]]!=rounded_expectations:
    raise ValueError('Rounded percentages do not match source-table arithmetic')
out=dict(identity='Deterministic arithmetic on reported rounded tables and exact constructed selection example; not E04 or paper replication',api_calls=0,
         selection_assumptions='Independent candidates and independent Bernoulli(1/2) outcomes on four development tasks; m positive integer',
         selection=selection,source_score_differences={k:str(v) for k,v in differences.items()},
         cost_arithmetic={k:float(v) for k,v in cost.items()},
         scopes={'ACE_Table4':'Main-table latency/rollout and historical-dollar reports',
                 'ACE_Table12':'AppendixA.3 separate fine-grained setting:1 epoch/1 reflector round; all3 component totals',
                 'GEPA_best_vs_total':'678 is reported best-prompt appearance,3593 total optimization budget row GEPA(+Merge); not interchangeable'},
         unmeasured='No E04 run, no causal component attribution, no source-table uncertainty intervals')
target=ROOT/'analysis/context-audit-reproduction.json'
target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Exact selection example and19 source-table differences/ratios reconciled; API calls:0')
