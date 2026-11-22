"""Plan-bound descriptive E01 analysis. No inference interval or verdict.

Weights are fixed by planned family/task/repeat identities, not by which rows
finished. Missing outcomes yield logical bounds, not confidence intervals.
Online and frozen-transfer phases must be analyzed separately.
"""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
from collections import Counter,defaultdict
from .e01_v2_design import identifier,integer


@dataclass(frozen=True)
class PlannedUnit:
    phase: str
    family: str
    task: str
    repeat: int

    def __post_init__(self):
        if self.phase not in ('online','transfer'): raise ValueError('phase must be explicit')
        identifier(self.family);identifier(self.task);integer(self.repeat,'repeat')


@dataclass(frozen=True)
class Observation:
    unit: PlannedUnit
    arm: str
    outcome: bool | None
    status: str

    def __post_init__(self):
        if type(self.unit) is not PlannedUnit or self.arm not in ('R','F','U','L'):
            raise ValueError('valid unit and arm required')
        if self.status in ('budget_exhausted','invalid_candidate'):
            if self.outcome is not False: raise ValueError('policy failure must remain observed false')
        elif self.status == 'completed':
            if type(self.outcome) is not bool: raise ValueError('completed outcome must be boolean')
        elif self.status in ('external_interruption','not_run'):
            if self.outcome is not None: raise ValueError('missing observation cannot be filled')
        else: raise ValueError('unknown observation status')


def describe(planned, observations, *, phase, comparison=('U','R')):
    if type(planned) is not tuple or not planned or any(type(u) is not PlannedUnit for u in planned):
        raise ValueError('nonempty immutable planned manifest required')
    if len(set(planned)) != len(planned): raise ValueError('duplicate planned unit')
    if phase not in ('online','transfer'): raise ValueError('explicit phase required')
    if type(comparison) is not tuple or len(comparison)!=2 or comparison[0]==comparison[1] or any(x not in ('R','F','U','L') for x in comparison):
        raise ValueError('ordered two-arm contrast required')
    families_by_task=defaultdict(set)
    for unit in planned: families_by_task[unit.phase,unit.task].add(unit.family)
    if any(len(x)>1 for x in families_by_task.values()): raise ValueError('task family identity is inconsistent')
    selected=tuple(x for x in planned if x.phase==phase)
    if not selected: raise ValueError('requested phase absent from plan')
    planned_set=set(planned);records={}
    for row in observations:
        if type(row) is not Observation or row.unit not in planned_set: raise ValueError('observation not in plan')
        key=(row.unit,row.arm)
        if key in records: raise ValueError('duplicate outcome; cannot silently retain a favorable rerun')
        records[key]=row
    family_tasks=defaultdict(set);repeat_counts=Counter((x.family,x.task) for x in selected)
    for u in selected:family_tasks[u.family].add(u.task)
    nf=len(family_tasks)
    lo=hi=complete_sum=complete_weight=Fraction(0)
    complete_n=0;rows=[];status_counts={a:Counter() for a in comparison}
    per_family=defaultdict(lambda: {'weighted_lower':Fraction(0),'weighted_upper':Fraction(0),'units':0})
    for u in selected:
        weight=Fraction(1,nf*len(family_tasks[u.family])*repeat_counts[u.family,u.task])
        observed=[]
        for arm in comparison:
            record=records.get((u,arm))
            status_counts[arm][record.status if record else 'missing_record']+=1
            observed.append(None if record is None else record.outcome)
        a,b=observed
        # bool endpoints are exact integers; unknown arm contributes [0,1].
        amin,amax=(0,1) if a is None else (int(a),int(a))
        bmin,bmax=(0,1) if b is None else (int(b),int(b))
        lower,upper=amin-bmax,amax-bmin
        lo+=weight*lower;hi+=weight*upper
        if a is not None and b is not None:
            complete_n+=1;complete_weight+=weight;complete_sum+=weight*(int(a)-int(b))
        pf=per_family[u.family];pf['weighted_lower']+=weight*nf*lower;pf['weighted_upper']+=weight*nf*upper;pf['units']+=1
        rows.append({'family':u.family,'task':u.task,'repeat':u.repeat,
            'weight_fraction':str(weight),'left_outcome':a,'right_outcome':b,
            'difference_bounds':[lower,upper]})
    assert sum(Fraction(x['weight_fraction']) for x in rows)==1
    return {'identity':'plan-bound descriptive comparison; no automatic proposition decision',
        'phase':phase,'contrast':f'{comparison[0]} minus {comparison[1]}',
        'weight_rule':'equal planned families; equal planned tasks within family; equal planned repeats within task',
        'planned_units':len(selected),'planned_families':nf,'complete_pairs':complete_n,
        'complete_planned_weight':float(complete_weight),
        'complete_case_reweighted_difference':float(complete_sum/complete_weight) if complete_weight else None,
        'planned_mean_logical_bounds':[float(lo),float(hi)],
        'bound_note':'range implied by observed outcomes and [0,1] for missing scores; NOT a confidence interval',
        'point_estimate':float(lo) if lo==hi else None,
        'status_counts':{a:dict(c) for a,c in status_counts.items()},
        'family_ranges':{f:{'logical_bounds':[float(v['weighted_lower']),float(v['weighted_upper'])],
                            'planned_units':v['units']} for f,v in per_family.items()},
        'rows':rows,'inference_interval':None,'proposition_status':'open',
        'limitations':['No representativeness, family-independence, or precision claim.',
            'Complete-case reweighting changes the target when planned outcomes are missing.',
            'Sequence dependence and randomization are not estimated by this descriptive module.']}
