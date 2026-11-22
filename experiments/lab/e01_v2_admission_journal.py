"""Crash-recoverable, single-source admission transaction; offline only.

One SQLite journal binds one extraction to its reserved calls/dispatches, actual
response span, review and resulting memory snapshot. It launches nothing. Caps
cover this extraction only, NOT a complete arm or shared preparation budget.
The host must integrate the returned snapshot with the live task sequence and
global resource authority; reopening here never changes a deployed agent.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import hashlib
import sqlite3
from .e01_v2_design import Memory, canonical, digest, identifier
from .e01_v2_resources import ResourceJournal, Limits, PendingDispatch
from .e01_v2_public_memory import RecentSequence
from .e01_v2_admission_receipts import AdmissionLedger
from .e01_v2_execution import strict_json


class AdmissionJournal:
    def __init__(self, path, session_id, store, window, event_ids, initial, limits, *, create=False):
        identifier(session_id)
        if type(create) is not bool or type(limits) is not Limits or type(initial) is not Memory:
            raise ValueError('typed memory/limits and boolean create required')
        if window.phase != 'online':raise ValueError('online admission only; M0 preparation is separate')
        if limits.calls != 1 or limits.tests != 0:raise ValueError('one extraction call, no test reservations')
        self._store,self._window,self._event_ids=store,window,event_ids
        self._initial,self._limits=initial,limits
        # Validate memory before creating any artifact.
        RecentSequence('U',initial,(window.task_id,))
        ledger=AdmissionLedger(store);self._key,request=ledger.request(window,event_ids)
        self._request=request
        modules=('e01_v2_admission_journal.py','e01_v2_admission_receipts.py',
                 'e01_v2_public_memory.py','e01_v2_resources.py','e01_v2_design.py',
                 'e01_v2_execution.py','e01_v2_manifest.py','e01_v2_file_boundary.py',
                 'e01_v2_analysis.py')
        self._header={'schema':'e01-single-admission-journal-offline-v1','session_id':session_id,
            'request_body':request.body.decode('utf-8'),'request_provenance':request.provenance.decode('utf-8'),
            'initial':strict_json(initial.payload()),'initial_sha256':initial.sha256(),
            'limits':asdict(limits),'response_max_utf8_bytes':65536,
            'implementation':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in modules}}
        self._header_bytes=canonical(self._header)
        self.path=Path(path).absolute()
        if create:
            with self.path.open('xb'):pass
        self._db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,isolation_level=None,timeout=5)
        self._db.execute('PRAGMA synchronous=FULL')
        try:
            if create:
                self._db.execute('PRAGMA journal_mode=DELETE');self._db.execute('BEGIN IMMEDIATE')
                self._db.execute('CREATE TABLE header (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)')
                self._db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, payload BLOB NOT NULL, sha256 TEXT NOT NULL)')
                self._db.execute('INSERT INTO header VALUES (1,?)',(self._header_bytes,));self._db.execute('COMMIT')
            self._transaction(None)
        except BaseException:
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            self._db.close();raise

    def close(self):self._db.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def _reduce(self, events):
        # Reuse the frozen resource reducer without creating a second journal.
        # Its private reducer dependency is explicit and hash-bound in the header.
        resources=object.__new__(ResourceJournal)
        resources.limits=self._limits;resources.calls={};resources.events={};resources.test_ids=set()
        ledger=AdmissionLedger(self._store);key,request=ledger.request(self._window,self._event_ids)
        if request!=self._request:raise ValueError('public request changed since journal initialization')
        sequence=RecentSequence('U',self._initial,(self._window.task_id,))
        sequence.begin(self._window.task_id);sequence.finish(self._window.task_id)
        call_id=None;pending=None;received=False;abandoned=False;published=False
        for index,event in enumerate(events,1):
            if type(event) is not dict or set(event)!={'kind','data'} or type(event['data']) is not dict:
                raise ValueError('invalid journal event')
            kind,data=event['kind'],event['data'];eid=f'journal-event-{index}'
            def fields(names):
                if set(data)!=set(names):raise ValueError('event fields mismatch')
            def resource(kind,**data):resources._apply({'id':eid,'kind':kind,'data':data})
            if kind=='reserve':
                fields(('call_id',))
                if call_id is not None:raise ValueError('extraction already reserved')
                call_id=identifier(data['call_id'])
                resource('call',call_id=call_id,role='update',task_id=self._window.task_id)
            elif kind=='issue':
                fields(())
                if call_id is None:raise ValueError('reserve before dispatch')
                resource('attempt',call_id=call_id);pending=eid
            elif kind=='settle':
                fields(('attempt_id','outcome','usage','response_id','text','origin'))
                if pending is None or data['attempt_id']!=pending:raise ValueError('no matching pending dispatch')
                if data['outcome']=='success':
                    if type(data['text']) is not str or len(data['text'].encode('utf-8'))>65536:
                        raise ValueError('response must fit fixed UTF-8 byte cap')
                    ledger.response(key,response_id=data['response_id'],text=data['text'],origin=data['origin'])
                    received=True
                elif any(data[x] is not None for x in ('response_id','text','origin')):
                    raise ValueError('failure cannot carry a usable response')
                resource('settle',call_id=call_id,attempt_id=pending,outcome=data['outcome'],usage=data['usage'])
                pending=None
            elif kind=='abandon':
                fields(('attempt_id','reason','reconciled'))
                if pending is None or data['attempt_id']!=pending or data['reconciled'] is not True:
                    raise ValueError('explicit reconciliation of matching dispatch required')
                if type(data['reason']) is not str or not 1<=len(data['reason'])<=256:
                    raise ValueError('bounded reconciliation reason required')
                resource('settle',call_id=call_id,attempt_id=pending,outcome='failure',usage=None)
                # Distinct internal event, within the SAME SQLite transaction.
                resources._apply({'id':eid+'-close','kind':'close','data':{'call_id':call_id}})
                pending=None;abandoned=True
            elif kind=='candidate':
                fields(('item_id','start','end','source_event_ids'))
                ledger.candidate(key,**{**data,'source_event_ids':tuple(data['source_event_ids'])})
            elif kind=='review':
                fields(('review_id','accepted','reviewer_kind','reviewer_id','rationale'))
                ledger.review(key,**data)
            elif kind=='publish':
                fields(())
                ledger.publish(key,sequence);published=True
            else:raise ValueError('unknown admission event')
        return {'resources':resources.summary(),'receipt':strict_json(ledger.archive()),
            'pending_attempt':pending,'has_response':received,'abandoned_unobserved':abandoned,
            'snapshot_published':published,'memory':sequence.stored_memory(),
            'call_id':call_id,'request_sha256':key}

    def _read(self):
        if self._db.execute('SELECT id,payload FROM header').fetchall()!=[(1,self._header_bytes)]:
            raise ValueError('journal header/implementation/input identity changed')
        events=[];chain=digest(self._header)
        for expected,(seq,payload,sha) in enumerate(self._db.execute('SELECT seq,payload,sha256 FROM events ORDER BY seq'),1):
            if seq!=expected or type(payload) is not bytes:raise ValueError('journal sequence gap')
            event=strict_json(payload)
            if canonical(event)!=payload:raise ValueError('noncanonical event bytes')
            chain=digest({'previous':chain,'seq':seq,'event':event})
            if chain!=sha:raise ValueError('journal chain mismatch')
            events.append(event)
        return events,chain

    def _transaction(self,event):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            events,chain=self._read()
            state=self._reduce(events+([] if event is None else [event]))
            if event is not None:
                seq=len(events)+1;chain=digest({'previous':chain,'seq':seq,'event':event})
                self._db.execute('INSERT INTO events VALUES (?,?,?)',(seq,canonical(event),chain))
            self._db.execute('COMMIT')
            return state,chain
        except BaseException:
            if self._db.in_transaction:self._db.execute('ROLLBACK')
            raise

    def _record(self,kind,**data):return self._transaction({'kind':kind,'data':data})[0]
    def reserve(self,call_id):self._record('reserve',call_id=call_id)
    def issue(self):
        state=self._record('issue')
        # Dispatch permit is returned only after reservation commits.
        return {'session_id':self._header['session_id'],'call_id':state['call_id'],
                'attempt_id':state['pending_attempt'],'request_sha256':self._key,
                'request_body':self._request.body}
    def settle(self,attempt_id,*,outcome,usage=None,response_id=None,text=None,origin=None):
        self._record('settle',attempt_id=attempt_id,outcome=outcome,usage=usage,
                     response_id=response_id,text=text,origin=origin)
    def abandon_after_reconciliation(self,attempt_id,reason,*,reconciled):
        self._record('abandon',attempt_id=attempt_id,reason=reason,reconciled=reconciled)
    def candidate(self,*,item_id,start,end,source_event_ids):
        if type(source_event_ids) is not tuple:raise ValueError('source ID tuple required')
        self._record('candidate',item_id=item_id,start=start,end=end,source_event_ids=source_event_ids)
    def review(self,**data):self._record('review',**data)
    def publish(self):
        return self._record('publish')['memory']
    def report(self):
        state,chain=self._transaction(None)
        state['memory_sha256']=state['memory'].sha256();state['memory']=strict_json(state['memory'].payload())
        return {**state,'journal_sha256':chain,'scope':'one extraction; no global budget or live deployment',
                'session_id':self._header['session_id']}
