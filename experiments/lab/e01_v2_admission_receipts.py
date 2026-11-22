"""Trusted-host provenance binding for offline E01 lesson publication.

This records review decisions; it does not judge semantic truth, authenticate the
reviewer, call a model, or enforce OS isolation. It is not a live runner or a
restartable transaction log. Existing public-memory adapters remain unchanged.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib
from .e01_v2_design import Lesson,canonical,identifier
from .e01_v2_public_memory import PublicEventStore,RecentSequence

SCHEMA='e01-admission-receipt-offline-v1'

def _text(value):
    if type(value) is not str or not value.strip():raise ValueError('nonempty text required')
    canonical(value)
    return value

def _sha(value):return hashlib.sha256(value).hexdigest()

class AdmissionLedger:
    def __init__(self,store):
        if type(store) is not PublicEventStore:raise ValueError('registered public store required')
        self._store=store
        self._rows={}
        self._tasks=set()
        self._response_ids=set()
        self._review_ids=set()
        self._lesson_ids=set()

    def request(self,window,event_ids):
        q=self._store.extraction(window,event_ids)
        if window.task_id in self._tasks:raise ValueError('one extraction slot per source task')
        key=_sha(q.body)
        if key in self._rows:raise ValueError('duplicate request')
        self._rows[key]={'request':q,'task':window.task_id,'phase':window.phase,
            'event_ids':event_ids,'response':None,'candidate':None,'review':None,'publication':None}
        self._tasks.add(window.task_id)
        return key,q

    def _row(self,key):
        if type(key) is not str or key not in self._rows:raise ValueError('unknown registered request')
        return self._rows[key]

    def response(self,key,*,response_id,text,origin):
        row=self._row(key);identifier(response_id);_text(text)
        if origin not in ('scripted_fixture','model_response'):raise ValueError('explicit response identity required')
        if row['response'] is not None or response_id in self._response_ids:raise ValueError('response already used')
        row['response']={'response_id':response_id,'text':text,'origin':origin,
                         'sha256':_sha(text.encode('utf-8'))}
        self._response_ids.add(response_id)

    def candidate(self,key,*,item_id,start,end,source_event_ids):
        row=self._row(key);identifier(item_id)
        if row['response'] is None or row['candidate'] is not None:raise ValueError('one candidate after response')
        if item_id in self._lesson_ids:raise ValueError('lesson ID already used')
        if type(start) is not int or type(end) is not int or not 0<=start<end<=len(row['response']['text']):
            raise ValueError('explicit Unicode codepoint span required')
        if type(source_event_ids) is not tuple or not source_event_ids or len(set(source_event_ids))!=len(source_event_ids):
            raise ValueError('nonempty unique source IDs required')
        if any(x not in row['event_ids'] for x in source_event_ids):raise ValueError('source outside extraction')
        lesson=Lesson(item_id,row['response']['text'][start:end],row['task'],row['phase'])
        _text(lesson.text)
        row['candidate']={'lesson':lesson,'start':start,'end':end,'source_event_ids':source_event_ids,
            'lesson_sha256':_sha(canonical(asdict(lesson))),'length_ok':len(lesson.text)<=400}
        self._lesson_ids.add(item_id)
        return lesson

    def review(self,key,*,review_id,accepted,reviewer_kind,reviewer_id,rationale):
        row=self._row(key);identifier(review_id);identifier(reviewer_id);_text(rationale)
        if type(accepted) is not bool:raise ValueError('explicit boolean decision required')
        if reviewer_kind not in ('codex_self_review','human_review','scripted_fixture'):raise ValueError('explicit reviewer category required')
        if row['candidate'] is None or row['review'] is not None or review_id in self._review_ids:
            raise ValueError('one review bound to an existing candidate')
        row['review']={'review_id':review_id,'accepted':accepted,'reviewer_kind':reviewer_kind,
            'reviewer_id':reviewer_id,'rationale':rationale,'request_sha256':key,
            'response_sha256':row['response']['sha256'],'lesson_sha256':row['candidate']['lesson_sha256']}
        self._review_ids.add(review_id)

    def publish(self,key,sequence):
        row=self._row(key)
        if type(sequence) is not RecentSequence or row['phase']!='online':raise ValueError('online sequence required; M0 merge is separate')
        if row['review'] is None or row['publication'] is not None:raise ValueError('one publication after review')
        before=sequence.stored_memory().sha256()
        # Sequence enforces the just-completed source task, U arm, and one decision.
        # Rejection is still a consumed decision. Overlength cannot become accepted.
        accepted=sequence.publish(row['candidate']['lesson'],validated=row['review']['accepted'])
        row['publication']={'accepted':accepted,'before':before,'after':sequence.stored_memory().sha256(),
            'review_id':row['review']['review_id'],'request_sha256':key,
            'lesson_sha256':row['candidate']['lesson_sha256']}
        return accepted

    def archive(self):
        rows=[]
        for key,row in self._rows.items():
            candidate=row['candidate']
            rows.append({'request_sha256':key,'request_body':row['request'].body.decode('utf-8'),
                'request_provenance':row['request'].provenance.decode('utf-8'),
                'response':row['response'],'candidate':None if candidate is None else
                {**candidate,'lesson':asdict(candidate['lesson'])},
                'review':row['review'],'publication':row['publication']})
        return canonical({'schema':SCHEMA,'identity':'trusted-host record; not semantic or OS proof',
            'implementation_sha256':_sha(__import__('pathlib').Path(__file__).read_bytes()),'rows':rows})
