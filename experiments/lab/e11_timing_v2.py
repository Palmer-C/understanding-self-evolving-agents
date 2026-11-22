"""E11 v2 prefix-only timing controller; no model or live budget implementation.

Signals concern observed task inputs, NOT not-yet-generated lessons.
See E11-v2-draft.md. This is an offline component, not an experiment runner.
"""
from __future__ import annotations
from dataclasses import dataclass,field
import math,time
from .trigger_signals import jaccard

@dataclass
class TimingController:
    arm:str
    sequence_length:int
    write_attempt_limit:int=4
    period:int=2
    error_threshold:int=2
    drift_window:int=2
    drift_threshold:float=.5
    novelty_threshold:float=.5
    _observations:list=field(default_factory=list,init=False,repr=False)
    _ids:set=field(default_factory=set,init=False,repr=False)
    _attempts:int=field(default=0,init=False,repr=False)

    def __post_init__(self):
        if self.arm not in ('per_task','periodic','event'):raise ValueError('unknown arm')
        for k in ('sequence_length','period','error_threshold','drift_window'):
            x=getattr(self,k)
            if type(x) is not int or x<1:raise ValueError(k+' must be a positive integer')
        if type(self.write_attempt_limit) is not int or self.write_attempt_limit<0:raise ValueError('invalid write attempt limit')
        for k in ('drift_threshold','novelty_threshold'):
            x=getattr(self,k)
            if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or not 0<x<=1:raise ValueError(k+' must be in (0,1]')

    def observe(self,*,episode_id:str,verdict:bool,task_text:str)->dict:
        start=time.perf_counter()
        if not isinstance(episode_id,str) or not episode_id or episode_id in self._ids:raise ValueError('unique nonempty episode_id required')
        if type(verdict) is not bool:raise ValueError('missing outcome is not a failure')
        if not isinstance(task_text,str) or not task_text.strip():raise ValueError('observed task text required')
        i=len(self._observations)
        if i>=self.sequence_length:raise ValueError('sequence already complete')
        # Compute from this observation and the committed prefix only.
        old=[x['verdict'] for x in self._observations];values=old+[verdict]
        er=0
        for ok in reversed(values):
            if ok:break
            er+=1
        novelty=1.0 if not self._observations else 1-max(jaccard(task_text,x['task_text']) for x in self._observations)
        w=self.drift_window
        shift=None if len(values)<2*w else abs(sum(values[-w:])/w-sum(values[-2*w:-w])/w)
        reasons=[]
        if self.arm=='per_task':reasons=['per_task']
        elif self.arm=='periodic':
            if (i+1)%self.period==0:reasons=['periodic']
        else:
            if er>=self.error_threshold:reasons.append('error_run')
            if shift is not None and shift>=self.drift_threshold:reasons.append('absolute_failure_shift')
            if novelty>=self.novelty_threshold:reasons.append('input_novelty')
        requested=bool(reasons)
        if i==self.sequence_length-1:decision='terminal_no_future_task'
        elif not requested:decision='not_triggered'
        elif self._attempts>=self.write_attempt_limit:decision='write_attempt_limit'
        else:decision='attempt_reserved';self._attempts+=1
        self._ids.add(episode_id)
        self._observations.append({'episode_id':episode_id,'verdict':verdict,'task_text':task_text})
        return {'episode_index':i,'episode_id':episode_id,'error_run':er,
                'absolute_failure_shift':shift,'input_novelty':novelty,'trigger_reasons':reasons,
                'requested':requested,'decision':decision,'attempts_reserved':self._attempts,
                'signal_model_calls':0,'monitor_seconds':time.perf_counter()-start,
                'observation_scope':'current and prior task descriptions and outcomes',
                'resource_note':'W limits construction attempts only; live total-resource guard not implemented here'}
