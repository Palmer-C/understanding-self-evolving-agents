"""Exact chapter10 teaching/source arithmetic; no training or model execution."""
from pathlib import Path
from fractions import Fraction as F
import argparse
import hashlib
import json
import math
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calculations.historical_evidence import write_reproduction


def audit_seal_results(directory):
    """Read the 9 published summaries after checking their normalized source bytes."""
    paths = sorted([directory / "overall_results.json", *directory.glob("run*/summary*.json")])
    records = {}
    signatures = []
    for path in paths:
        name = path.relative_to(directory).as_posix()
        data = path.read_bytes().replace(b"\r\n", b"\n")
        signatures.append(f"{name}\t{hashlib.sha256(data).hexdigest()}\n")
        records[name] = data
    digest = hashlib.sha256("".join(signatures).encode()).hexdigest()
    if digest != "5d2e63985ea3cf2a6cdccceb64029e3a7be6fbbb25b1a7459f99bbf2d811dfad":
        raise ValueError("SEAL summary files differ from the cited release at 6d9c9f9.")
    overall = json.loads(records.pop("overall_results.json"))
    groups = [json.loads(raw) for raw in records.values()]
    size = groups[0]["n_sequences"]
    total = overall["n_sequences"]
    positions = overall["n_datapoints"]
    cells = []
    for step in range(positions + 1):
        included = positions if step == 0 else step
        for position in range(included):
            means = [g["mean_over_sequences"][step][position] for g in groups]
            deviations = [g["std_over_sequences"][step][position] for g in groups]
            mean = statistics.mean(means)
            within = sum((size - 1) * sd ** 2 for sd in deviations)
            between = sum(size * (value - mean) ** 2 for value in means)
            pooled_sem = math.sqrt((within + between) / ((total - 1) * total))
            cells.append({
                "step": step, "position": position + 1, "mean": mean,
                "archived_mean": overall["mean_over_sequences"][step][position],
                "archived_std": overall["std_over_sequences"][step][position],
                "mean_of_group_sds": statistics.mean(deviations),
                "pooled_sample_sem": pooled_sem,
            })
    return {
        "source_commit": "6d9c9f9ee392c6cc618e771f399d436d190f6ca4",
        "input_digest": digest, "groups": len(groups), "sequences_per_group": size,
        "total_sequences": total, "positions": positions, "observed_cells": cells,
        "scope": "Step zero covers all positions; later steps cover only visited positions. "
                 "Per-cell summaries do not give cross-step covariance for paired changes.",
    }


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--seal-results", type=Path, help="Directory of the original continual_self_edits summaries.")
parser.add_argument("-o", "--output", type=Path, help="Write a new file instead of refreshing the default report.")
args = parser.parse_args()
results={
 'SEAL_single_passage_vs_base_generated_pp':F('47.0')-F('39.7'),
 'SEAL_single_passage_vs_GPT41_data_pp':F('47.0')-F('46.3'),
 'SEAL_CPT200_vs_GPT41_data_pp':F('58.2')-F('59.4'),
 'SEAL_CPT2067_vs_GPT41_data_pp':F('46.4')-F('49.2'),
 'SEAL_heatmap_first_adapted_minus_final':F('.38')-F('.19'),
 'SEAL_heatmap_initial_minus_final':F('.33')-F('.19'),
 'SEAL_filtered_edit_evaluations':8*5,
 'SEAL_filtered_edit_successes':8*5*F('.725'),
 'SEAL_inner_evaluations_per_reported_round':50*5*3,
 'teacher_success_logit_derivative':1-F('.5'),
 'teacher_no_baseline_gradient':F('.5')/4,
 'teacher_success_only_mean_gradient':F('.5'),
 'teacher_nonzero_baseline_gradient':(F('.75')*F('.5')+3*F('-.25')*F('-.5'))/4,
 'service_cost_crossing':F(140-20,3-1),
 'external40':20+3*40,'parameter40':140+40,
 'external100':20+3*100,'parameter100':140+100,
 'serial100_edit_seconds_low':100*30,'serial100_edit_seconds_high':100*45}
if results['teacher_nonzero_baseline_gradient']!=F('.1875') or results['SEAL_filtered_edit_successes']!=29:
    raise ValueError('Exact chapter10 arithmetic failed')
intervals=[(-8,2),(-2,1),(1,4)]
out=dict(identity='Exact constructed algebra and arithmetic on reported rounded SEAL values; not E08,model training,or source experiment replication',api_calls=0,
         values={k:dict(exact=str(v),value=float(v)) for k,v in results.items()},
         supplied_interval_noninferiority_lower_above_minus3=[lo>-3 for lo,hi in intervals],
         scope=['Heatmap values read from originalv2Figure6 image;notnewmeasurements','40edit evaluations share8tasks;not40independenttaskfamilies','PGnormalization result onlysamebatch/parameterpoint,noKL/base/lengthnorm;nonzero baseline changesfinitebatch estimate','Timing bound assumesserialexecutionandnooverhead,notactualworkflowtime','Costlines hypotheticalconstantcharges,commonquality andvalidassetlifetime'])
if args.seal_results is not None:
    try:
        out["seal_archive"] = audit_seal_results(args.seal_results)
    except (OSError, ValueError) as error:
        parser.error(f"{error} See analysis/README.md for the cited source and expected input.")
try:
    write_reproduction(out, ROOT / "analysis/parameter-arithmetic-reproduction.json", args.output)
except OSError as error:
    parser.error(f"Could not write the report: {error}")
print(f"{len(results)} source and teaching quantities, {len(intervals)} interval examples; no model calls.")
