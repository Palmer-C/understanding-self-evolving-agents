"""Offline E01 write-ahead call ledger. No backend import or paid entry point.

Single writer only. Call IDs reserve logical generations; attempts reserve actual
dispatch opportunities. Unknown usage stays unknown. A pending dispatch blocks
restart dispatch, since local journaling cannot guarantee exactly-once service
execution. Journal corruption fails closed and never truncates original bytes.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from copy import deepcopy
import json
import os
from pathlib import Path
from .e01_v2_design import canonical, digest, identifier, integer


class BudgetStop(RuntimeError): pass
class PendingDispatch(RuntimeError): pass


@dataclass(frozen=True)
class Limits:
    calls: int
    attempts: int
    tests: int

    def __post_init__(self):
        for k, v in asdict(self).items(): integer(v, k)


class ResourceJournal:
    """No refunds after reservation; all roles share the same total caps."""
    ROLES = ('solve', 'select', 'update', 'repair', 'prepare', 'restore')

    def __init__(self, path, limits: Limits, *, create=True):
        if type(limits) is not Limits: raise ValueError('Limits required')
        self.path, self.limits = Path(path), limits
        self.events, self.calls, self.test_ids = {}, {}, set()
        self.poisoned = False
        if create:
            with self.path.open('xb') as f:
                f.write(canonical({'schema': 'e01-v2-resource-draft-1', 'limits': asdict(limits)}) + b'\n')
                f.flush(); os.fsync(f.fileno())
        else:
            lines = self.path.read_bytes().splitlines(keepends=True)
            if not lines or any(not x.endswith(b'\n') for x in lines):
                raise ValueError('incomplete journal; manual reconciliation required')
            header = json.loads(lines[0])
            if header != {'schema': 'e01-v2-resource-draft-1', 'limits': asdict(limits)}:
                raise ValueError('journal schema or limits mismatch')
            for line in lines[1:]: self._apply(json.loads(line))

    def _apply(self, event):
        if not isinstance(event, dict) or set(event) != {'id', 'kind', 'data'}:
            raise ValueError('invalid event')
        eid, kind, data = event['id'], event['kind'], event['data']
        identifier(eid)
        if eid in self.events:
            if self.events[eid] != event: raise ValueError('conflicting event ID')
            return False
        if not isinstance(data, dict): raise ValueError('event data must be object')
        if kind == 'call':
            if set(data) != {'call_id', 'role', 'task_id'}: raise ValueError('call fields')
            cid = identifier(data['call_id']); identifier(data['task_id'])
            if data['role'] not in self.ROLES or cid in self.calls: raise ValueError('call identity/role')
            if len(self.calls) >= self.limits.calls: raise BudgetStop('logical call limit')
            if self.pending(): raise PendingDispatch('unresolved dispatch')
            self.calls[cid] = {**data, 'attempts': [], 'closed': False}
        elif kind == 'attempt':
            if set(data) != {'call_id'}: raise ValueError('attempt fields')
            call = self.calls[data['call_id']]
            if call['closed']: raise ValueError('call already closed')
            if self.pending(): raise PendingDispatch('unresolved dispatch')
            if sum(len(x['attempts']) for x in self.calls.values()) >= self.limits.attempts:
                raise BudgetStop('dispatch limit')
            call['attempts'].append({'id': eid, 'outcome': None, 'usage': None})
        elif kind == 'settle':
            if set(data) != {'call_id', 'attempt_id', 'outcome', 'usage'}: raise ValueError('settle fields')
            call = self.calls[data['call_id']]
            if not call['attempts'] or call['attempts'][-1]['id'] != data['attempt_id']:
                raise ValueError('settle must address latest attempt')
            attempt = call['attempts'][-1]
            if attempt['outcome'] is not None or data['outcome'] not in ('success', 'failure'):
                raise ValueError('already settled or invalid outcome')
            usage = data['usage']
            if usage is not None:
                if not isinstance(usage, dict) or set(usage) != {'prompt_tokens', 'completion_tokens'}:
                    raise ValueError('invalid provider usage')
                for k, v in usage.items(): integer(v, k)
            attempt.update(outcome=data['outcome'], usage=deepcopy(usage))
            if data['outcome'] == 'success': call['closed'] = True
        elif kind == 'close':
            if set(data) != {'call_id'}: raise ValueError('close fields')
            call = self.calls[data['call_id']]
            if any(x['outcome'] is None for x in call['attempts']): raise PendingDispatch('cannot discard pending request')
            if call['closed']: raise ValueError('call already closed')
            call['closed'] = True
        elif kind == 'test':
            if set(data) != {'task_id'}: raise ValueError('test fields')
            identifier(data['task_id'])
            if len(self.test_ids) >= self.limits.tests: raise BudgetStop('test limit')
            self.test_ids.add(eid)
        else: raise ValueError('unknown resource event')
        self.events[eid] = deepcopy(event)
        return True

    def record(self, event_id, kind, **data):
        if self.poisoned: raise RuntimeError('journal write failed; reopen for audit')
        event = {'id': event_id, 'kind': kind, 'data': data}
        # Validate and reduce a copy BEFORE append; rejection cannot mutate caps.
        probe = object.__new__(ResourceJournal)
        probe.limits = self.limits
        probe.calls, probe.test_ids, probe.events = deepcopy((self.calls, self.test_ids, self.events))
        changed = probe._apply(event)
        if not changed: return False
        try:
            with self.path.open('ab') as stream:
                stream.write(canonical(event) + b'\n'); stream.flush(); os.fsync(stream.fileno())
        except BaseException:
            self.poisoned = True
            raise
        self.calls, self.test_ids, self.events = probe.calls, probe.test_ids, probe.events
        return True

    def pending(self):
        return [x['id'] for c in self.calls.values() for x in c['attempts'] if x['outcome'] is None]

    def summary(self):
        attempts = [x for c in self.calls.values() for x in c['attempts']]
        known = [x['usage'] for x in attempts if x['usage'] is not None]
        return {'calls_reserved': len(self.calls), 'dispatches_reserved': len(attempts),
                'tests_reserved': len(self.test_ids),
                'known_prompt_tokens': sum(x['prompt_tokens'] for x in known),
                'known_completion_tokens': sum(x['completion_tokens'] for x in known),
                'attempts_usage_unknown': sum(x['usage'] is None for x in attempts),
                'pending_dispatches': len(self.pending()), 'usd': None,
                'journal_identity_sha256': digest({'limits': asdict(self.limits), 'events': list(self.events.values())}),
                'calls_by_role': {role: sum(c['role'] == role for c in self.calls.values()) for role in self.ROLES}}


def sum_unique_ledgers(ledgers):
    """Research totals count shared preparation once; conflicting copies fail."""
    unique = {}
    for ledger_id, summary in ledgers:
        identifier(ledger_id)
        if ledger_id in unique and unique[ledger_id] != summary:
            raise ValueError('conflicting shared ledger')
        unique[ledger_id] = deepcopy(summary)
    keys = ('calls_reserved', 'dispatches_reserved', 'tests_reserved',
            'known_prompt_tokens', 'known_completion_tokens', 'attempts_usage_unknown', 'pending_dispatches')
    for row in unique.values():
        for k in keys: integer(row[k], k)
    return {**{k: sum(row[k] for row in unique.values()) for k in keys},
            'distinct_ledgers': len(unique), 'ledger_ids': sorted(unique), 'usd': None}
