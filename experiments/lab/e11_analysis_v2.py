"""E11 v2 outcome analysis: preserve repeat-local change points.

This module neither calls models nor evaluates resource efficiency. A cluster ID
must identify a predeclared independent sequence unit; repeats do not add clusters.
Intervals are descriptive cluster bootstraps, never automatic P5 decisions.
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import mean
import random

ARMS=('per_task','periodic','event')
CONTRASTS=(('event','periodic'),('periodic','per_task'),('event','per_task'))

@dataclass(frozen=True)
class SequenceRun:
    repeat_id: str
    verdicts: tuple[bool,...]
    split: int

    def __post_init__(self):
        if not isinstance(self.repeat_id,str) or not self.repeat_id:
            raise ValueError('repeat_id must be a nonempty string')
        if not isinstance(self.verdicts,tuple) or not self.verdicts or any(type(v) is not bool for v in self.verdicts):
            raise ValueError('verdicts must be a nonempty tuple of explicit bools; missing is not failure')
        if type(self.split) is not int or not 0<self.split<len(self.verdicts):
            raise ValueError('split must leave both pre and post observations')

def paired_metrics(arm:SequenceRun,base:SequenceRun)->dict:
    if (arm.repeat_id,arm.split,len(arm.verdicts))!=(base.repeat_id,base.split,len(base.verdicts)):
        raise ValueError('unmatched repeat, change point or length')
    s=arm.split
    pre=mean(arm.verdicts[:s])-mean(base.verdicts[:s])
    post=mean(arm.verdicts[s:])-mean(base.verdicts[s:])
    return {'quality_difference':mean(arm.verdicts)-mean(base.verdicts),
            'pre_advantage':pre,'post_advantage':post,'widening':post-pre}

def _index(records):
    if not records or any(not isinstance(x,SequenceRun) for x in records):
        raise ValueError('each cluster needs explicit SequenceRun records')
    indexed={x.repeat_id:x for x in records}
    if len(indexed)!=len(records):raise ValueError('duplicate repeat_id')
    return indexed

def _interval(values,draws,seed):
    if len(values)<2:return None
    rng=random.Random(seed)
    n=len(values)
    samples=sorted(mean(values[rng.randrange(n)] for _ in range(n)) for _ in range(draws))
    def q(p):
        k=(draws-1)*p;i=int(k);f=k-i
        return samples[i]*(1-f)+samples[min(i+1,draws-1)]*f
    return [q(.025),q(.975)]

def analyze(records:dict,*,draws=2000,seed=20260930)->dict:
    if type(draws) is not int or draws<100:raise ValueError('draws must be an integer >=100')
    if set(records)!=set(ARMS):raise ValueError('all three arms required, no unknown arms')
    clusters=set(records['per_task'])
    if not clusters or any(not isinstance(k,str) or not k for k in clusters):raise ValueError('nonempty string cluster IDs required')
    if any(set(records[a])!=clusters for a in ARMS):raise ValueError('unmatched clusters; no silent complete-case filtering')
    indexed={a:{c:_index(records[a][c]) for c in sorted(clusters)} for a in ARMS}
    for c in clusters:
        ids=set(indexed['per_task'][c])
        if any(set(indexed[a][c])!=ids for a in ARMS):raise ValueError('unmatched repeats')
    output={'unit':'predeclared independent sequence cluster','n_clusters':len(clusters),
            'repeats_per_cluster':{c:len(indexed['per_task'][c]) for c in sorted(clusters)},
            'method':'mean within cluster; equal-weight cluster mean; percentile cluster bootstrap',
            'bootstrap_draws':draws,'bootstrap_seed':seed,'p5_status':'open','resource_efficiency_evaluated':False,
            'limitations':['cluster independence and sampling scope require design justification',
                'intervals are marginal descriptive intervals, not multiplicity-controlled tests',
                'small cluster counts and fixed synthetic task families limit inference',
                'valid task failure is False; infrastructure missingness must not be converted to False'],
            'contrasts':{}}
    for ai,(arm,base) in enumerate(CONTRASTS):
        per_cluster={}
        for c in sorted(clusters):
            runs=[paired_metrics(indexed[arm][c][i],indexed[base][c][i]) for i in sorted(indexed[base][c])]
            per_cluster[c]={k:mean(v[k] for v in runs) for k in runs[0]}
        aggregate={}
        for mi,key in enumerate(('quality_difference','pre_advantage','post_advantage','widening')):
            values=[per_cluster[c][key] for c in sorted(clusters)]
            aggregate[key]={'point':mean(values),'ci95_descriptive':_interval(values,draws,seed+ai*10+mi)}
        output['contrasts'][f'{arm}-{base}']={'per_cluster':per_cluster,'aggregate':aggregate}
    return output
