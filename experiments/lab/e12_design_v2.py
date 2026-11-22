"""Offline E12 v2 design primitives. No model calls, no inference or P6 verdict.

Snapshots, deterministic differences and paired descriptions are separate from
future execution. See E12-v2-draft.md for unresolved runner/protocol choices.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
from statistics import mean


@dataclass(frozen=True)
class Item:
    item_id: str
    text: str
    source_task_id: str
    provenance: str

    def __post_init__(self):
        if any(not isinstance(v,str) or not v.strip() for v in asdict(self).values()):
            raise ValueError('all item fields must be nonempty strings')


@dataclass(frozen=True)
class MemorySnapshot:
    items: tuple[Item,...]

    def __post_init__(self):
        if not isinstance(self.items,tuple) or any(not isinstance(x,Item) for x in self.items):
            raise ValueError('immutable tuple of Item required')
        ids=[x.item_id for x in self.items]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate item IDs')

    def payload(self):
        return json.dumps([asdict(x) for x in self.items],ensure_ascii=False,
                          sort_keys=True,separators=(',',':')).encode('utf-8')

    def sha256(self):
        return hashlib.sha256(self.payload()).hexdigest()

    def save_new(self,path):
        with Path(path).open('xb') as f:f.write(self.payload())

    @classmethod
    def load(cls,path):
        obj=json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(obj,list):raise ValueError('snapshot must be an item list')
        return cls(tuple(Item(**row) for row in obj))


def measure_change(old:MemorySnapshot,new:MemorySnapshot):
    a={x.item_id:x for x in old.items};b={x.item_id:x for x in new.items}
    common=set(a)&set(b)
    before,after=old.payload(),new.payload()
    counts={'inserted_bytes':0,'deleted_bytes':0,'replaced_old_bytes':0,'replaced_new_bytes':0}
    # Explicit autojunk=False; deterministic alignment, not a minimal edit distance.
    for op,i,j,k,l in SequenceMatcher(None,before,after,autojunk=False).get_opcodes():
        if op=='insert':counts['inserted_bytes']+=l-k
        elif op=='delete':counts['deleted_bytes']+=j-i
        elif op=='replace':counts['replaced_old_bytes']+=j-i;counts['replaced_new_bytes']+=l-k
    return {'added_ids':sorted(set(b)-set(a)),'deleted_ids':sorted(set(a)-set(b)),
            'modified_text_ids':sorted(k for k in common if a[k].text!=b[k].text),
            'modified_metadata_ids':sorted(k for k in common if
                (a[k].source_task_id,a[k].provenance)!=(b[k].source_task_id,b[k].provenance)),
            'common_order_changed':[x.item_id for x in old.items if x.item_id in common] !=
                                   [x.item_id for x in new.items if x.item_id in common],
            'old_bytes':len(before),'new_bytes':len(after),'net_bytes':len(after)-len(before),
            **counts,'old_sha256':old.sha256(),'new_sha256':new.sha256(),
            'byte_metric':'SequenceMatcher alignment of canonical UTF-8 JSON; not minimal or semantic distance'}


def controlled_corruption():
    text='Python的range(a,b)包含右端点b；因此计算闭区间时无需调整停止位置。'
    evidence={'kind':'constructed_false_statement_not_natural_model_error',
              'published_text':text,'counterexample':{'a':2,'b':4,'observed':list(range(2,4)),
                                                       'right_endpoint_present':4 in range(2,4)}}
    assert evidence['counterexample']['right_endpoint_present'] is False
    return Item('corrupt-range-endpoint',text,'python-range-counterexample','deterministic fault injection'),evidence


def construct_arms(baseline:MemorySnapshot,pool:tuple[Item,...],rewritten:Item):
    if not baseline.items or not isinstance(pool,tuple) or len(pool)!=3:
        raise ValueError('nonempty baseline and exactly three fixed candidates required')
    combined=MemorySnapshot(baseline.items+pool) # also validates uniqueness/types
    if rewritten.item_id!=baseline.items[0].item_id or rewritten.text==baseline.items[0].text:
        raise ValueError('rewrite must change the designated original item, keeping its ID')
    corrupt,evidence=controlled_corruption()
    arms={'control_no_update':baseline,
          'append_1':MemorySnapshot(baseline.items+pool[:1]),
          'append_3':combined,
          'rewrite_3':MemorySnapshot((rewritten,)+baseline.items[1:]+pool),
          'corrupt':MemorySnapshot(baseline.items+(corrupt,))}
    return arms,evidence


def _outcomes(values):
    if not isinstance(values,dict) or not values or any(not isinstance(k,str) or not k or type(v) is not bool for k,v in values.items()):
        raise ValueError('nonempty task-ID mapping of explicit bools required; missing is not failure')


def describe_pair(baseline,control,after):
    for values in (baseline,control,after):_outcomes(values)
    if set(baseline)!=set(control) or set(baseline)!=set(after):raise ValueError('unmatched fixed evaluation IDs')
    b,c,a=(mean(x.values()) for x in (baseline,control,after))
    return {'baseline_score':b,'control_score':c,'updated_score':a,
            'D_raw':b-a,'D_control':b-c,'D_adjusted':c-a,
            'per_task':{k:{'D_raw':int(baseline[k])-int(after[k]),
                          'D_control':int(baseline[k])-int(control[k]),
                          'D_adjusted':int(control[k])-int(after[k])} for k in sorted(baseline)},
            'n_tasks':len(baseline),'ci95':None,'p6_status':'open',
            'scope':'paired descriptive values, no automatic causal or universal inference'}


def rollback_requested(d_raw,threshold=.10):
    if isinstance(d_raw,bool) or not isinstance(d_raw,(float,int)) or not math.isfinite(d_raw):
        raise ValueError('observed finite D required')
    if isinstance(threshold,bool) or not isinstance(threshold,(float,int)) or not 0<threshold<=1:
        raise ValueError('threshold must be in (0,1]')
    return d_raw>=threshold


def restore_new_snapshot(baseline:MemorySnapshot,destination):
    baseline.save_new(destination)
    payload=Path(destination).read_bytes()
    return {'attempted':True,'file_restored':payload==baseline.payload(),
            'sha256':hashlib.sha256(payload).hexdigest(),
            'scope':'memory file only; no behavior equivalence or external-side-effect recovery claim'}


def describe_recovery(baseline,control,restored,*,file_restored):
    if type(file_restored) is not bool:raise ValueError('explicit file restore status required')
    metrics=describe_pair(baseline,control,restored)
    return {'file_restored':file_restored,'restored_score':metrics['updated_score'],
            'restored_minus_baseline':-metrics['D_raw'],
            'restored_minus_control':-metrics['D_adjusted'],
            'behavior_equivalence_established':False,'n_tasks':metrics['n_tasks']}


def resource_totals(shared_preparation,arm_ledgers):
    """Exclusive bookkeeping; missing known usage propagates, never becomes zero."""
    keys={'calls','transport_dispatches','known_prompt_tokens','known_completion_tokens'}
    rows=[shared_preparation]+list(arm_ledgers.values())
    if not arm_ledgers:raise ValueError('explicit arm ledgers required')
    for row in rows:
        if set(row)!=keys:raise ValueError('ledger has missing/unknown fields')
        if any(v is not None and (type(v) is not int or v<0) for v in row.values()):raise ValueError('invalid resource count')
    return {k:None if any(row[k] is None for row in rows) else sum(row[k] for row in rows) for k in sorted(keys)}
