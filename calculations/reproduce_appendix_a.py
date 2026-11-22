"""Deterministic constructed examples for Appendix A; never experimental data."""
from fractions import Fraction as F
from itertools import product
import json
import math
from pathlib import Path


def calculate():
    sizes = [8, 2, 2, 2]
    diffs = [F(1, 10), F(-2, 10), F(3, 10), F(-1, 10)]
    equal = sum(diffs) / 4
    pooled = sum(n*d for n,d in zip(sizes,diffs)) / sum(sizes)
    resamples = sorted(sum(diffs[i] for i in ids)/4 for ids in product(range(4),repeat=4))
    def quantile(p): return resamples[math.ceil(p*len(resamples))-1]
    bounds = [(F(1)-4)/14, (F(1)+4)/14]
    ratio_mean = (F(1,10)/2 + F(2,10)/10)/2
    ratio_pooled = F(3,10)/12
    def variance(families,tasks,repeats):
        return (F(4,100)+F(9,100)/tasks+F(16,100)/(tasks*repeats))/families
    variances = {name: variance(*dims) for name,dims in {
        'F4_T5_R2':(4,5,2), 'F4_T5_R20':(4,5,20), 'F40_T5_R2':(40,5,2)}.items()}
    # Exact conditional sign enumeration for five distinct nonzero absolute ranks.
    sign_rank_sums = [sum(rank for rank, sign in zip(range(1, 6), signs) if sign > 0)
                      for signs in product((-1, 1), repeat=5)]
    one_tail = F(sum(t >= 15 for t in sign_rank_sums), len(sign_rank_sums))
    two_tail = F(sum(t == 0 or t == 15 for t in sign_rank_sums), len(sign_rank_sums))
    assert one_tail == F(1, 32) and two_tail == F(1, 16)
    # These assert independently derived reference values, not rounded displays.
    assert equal == F(1,40) and pooled == F(2,35)
    assert bounds == [F(-3,14),F(5,14)]
    assert ratio_mean == F(7,200) and ratio_pooled == F(1,40)
    assert variances == {'F4_T5_R2':F(37,2000), 'F4_T5_R20':F(149,10000), 'F40_T5_R2':F(37,20000)}
    return {
        'identity':'constructed teaching inputs and exact arithmetic; not model calls or confidence coverage validation',
        'families':[{'name':name,'task_count':n,'assigned_difference':float(d)} for name,n,d in zip('ABCD',sizes,diffs)],
        'equal_family_difference':float(equal),'pooled_task_difference':float(pooled),
        'exhaustive_conditional_bootstrap':{
            'draws':len(resamples),'distinct_means':len(set(resamples)),
            'quantile_definition':'inverse empirical CDF, index ceil(p*N)-1, no interpolation',
            'q025':float(quantile(F(25,1000))),'q975':float(quantile(F(975,1000))),
            'resampling_scope':'four observed family means held fixed; does not validate frequentist coverage',
            'distribution':[{'mean':float(v),'multiplicity':resamples.count(v)} for v in sorted(set(resamples))]},
        'missing_pair_example':{'planned_pairs':14,'complete_pairs':10,'observed_difference_sum':1,
            'complete_case_mean':.1,'bounds_on_planned_mean':[float(x) for x in bounds]},
        'cost_ratio_example':{'gains':[.1,.2],'costs':[2,10],
            'mean_of_ratios':float(ratio_mean),'ratio_of_sums':float(ratio_pooled)},
        'assigned_random_effect_example':{'family_variance':.04,'task_variance':.09,'repeat_variance':.16,
            'variance_of_mean':{k:float(v) for k,v in variances.items()},
            'standard_error':{k:math.sqrt(float(v)) for k,v in variances.items()},
            'scope':'independent additive zero-mean components; not fitted to binary E01 data'},
        'signed_rank_teaching_example':{
            'assigned_differences':[1,2,3,4,5], 'positive_rank_sum':15,
            'conditional_sign_assignments':len(sign_rank_sums),
            'one_sided_upper_tail':float(one_tail), 'two_sided_extreme_tails':float(two_tail),
            'rank_sum_multiplicities':{str(t):sign_rank_sums.count(t) for t in sorted(set(sign_rank_sums))},
            'assumptions':'independent symmetric zero-centered differences under null; fixed distinct nonzero absolute ranks; direction specified before observing data',
            'scope':'exact constructed conditional enumeration; not a reconstruction of any paper or model run'},
        'calls':0}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-o', '--output', type=Path,
                        help='save to a new file; refuse to overwrite an existing destination')
    args = parser.parse_args(argv)
    result = calculate()
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is None:
        # Preserve the historical no-argument output location and write behavior.
        destination = Path(__file__).resolve().parents[1] / 'analysis/appendix-a-reproduction.json'
        destination.write_text(content, encoding='utf-8')
    else:
        destination = args.output
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open('x', encoding='utf-8') as stream:
                stream.write(content)
        except FileExistsError:
            parser.error(f'output destination already exists: {destination}')
    print(json.dumps({k:v for k,v in result.items() if k!='exhaustive_conditional_bootstrap'},ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result['exhaustive_conditional_bootstrap'].items() if k!='distribution'},ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
