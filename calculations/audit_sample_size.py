"""Offline audit: CI precision planning is not power planning.

Historical results stay unchanged. Normal approximations assume independent paired
tasks and usable variance estimates; no cluster/multiplicity/sequential corrections.
The power example is not a new preregistration or measured capability gain.
"""
from pathlib import Path
from statistics import NormalDist
import argparse, json, math, sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.lab.archive_inputs import required_summaries

def calculate(sd, h=.03, alpha=.05, power=.80, true_shift=.03):
    if sd <= 0 or h <= 0 or true_shift <= 0:
        raise ValueError('Positive standard deviation and effect scales required')
    if not 0 < alpha < 1 or not .5 < power < 1:
        raise ValueError('Invalid alpha or power')
    z=NormalDist().inv_cdf(1-alpha/2)
    return {'sd_from_pilot':sd,
            'legacy_precision_n':math.ceil((1.96*sd/h)**2),
            'precision_n_normal_quantile':math.ceil((z*sd/h)**2),
            'power_example_n':math.ceil(((z+NormalDist().inv_cdf(power))*sd/true_shift)**2)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--output', type=Path, help='Save a copy to a new file. Existing files are preserved.')
    args=ap.parse_args()
    specs=[('P1','E01-20260923T152230Z-90acda','sd_paired_diff_41','n_required_41'),
           ('P1b','E01-20260923T152230Z-90acda','sd_paired_diff_42','n_required_42'),
           ('P2b:self-exec','E02-20260924T153511Z-421eac','sd_paired_diff_self_exec','n_required_self_exec'),
           ('E02:formal-self','E02-20260924T153511Z-421eac','sd_paired_diff_formal_self','n_required_formal_self'),
           ('P3','E03-20260925T152453Z-254845','sd_p3_structured_vs_summary','n_required_p3')]
    summaries=required_summaries(args.root)
    rows=[]
    for label,run,sd_key,n_key in specs:
        s=summaries[run]['sample_sizing']
        row=calculate(s[sd_key]); row.update(comparison=label,run_id=run,recorded_n=s[n_key],available_tasks=16)
        if row['legacy_precision_n']!=s[n_key]:
            raise ValueError('Historical precision estimate mismatch')
        rows.append(row)
    result={'identity':'calculated from hash-bound historical pilot SDs; not measured capability',
            'input_manifest':'analysis/inputs.json',
            'E03_scope':'P3 structured-minus-summary only; does not use the disputed A/base_same baseline',
            'assumptions':{'alpha_two_sided':.05,'power_example':.8,'half_width':.03,'true_shift_vs_zero':.03},
            'limitations':['Task independence assumed; family dependence is not corrected.',
                           'Pilot SD uncertainty, multiple testing, and sequential looks are not included.',
                           'No confirmatory sample size has been preregistered by this script.'],
            'rows':rows}
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(text + '\n')
        except FileExistsError:
            ap.exit(1, f'输出已存在，请另选新文件：{args.output}\n')
        except OSError as exc:
            ap.exit(1, f'输出写入失败：{exc}\n')
    print(text)

if __name__=='__main__': main()
