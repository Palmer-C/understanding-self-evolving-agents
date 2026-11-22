"""Offline teaching example: atomic memory operations, NOT a learned policy or E03b."""
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path
import copy
import hashlib
import json


@dataclass(frozen=True)
class Entry:
    value: str
    scope: str
    version: int


class Memory:
    def __init__(self):
        self.entries = {}
        self.events = []
        self.receipts = {}

    def apply(self, request_id, action, key, scope, expected=None, value=None):
        # Caller supplies an authenticated scope in this teaching fixture.
        # A real service must obtain scope from its authentication layer.
        payload = (action, key, scope, expected, value)
        if request_id in self.receipts:
            old_payload, receipt = self.receipts[request_id]
            if payload != old_payload:
                raise ValueError('request_id_reused_with_different_payload')
            return copy.deepcopy(receipt)
        current = self.entries.get(key)
        reason = None
        if action not in {'ADD', 'UPDATE', 'DELETE'}:
            reason = 'unsupported_action'
        elif current is not None and current.scope != scope:
            reason = 'scope_denied'
        elif action == 'ADD' and current is not None:
            reason = 'already_exists'
        elif action in {'UPDATE', 'DELETE'} and current is None:
            reason = 'not_found'
        elif action in {'UPDATE', 'DELETE'} and expected != current.version:
            reason = 'version_conflict'
        elif action in {'ADD', 'UPDATE'} and not isinstance(value, str):
            reason = 'invalid_value'
        before = asdict(current) if current else None
        if reason is None:
            if action == 'DELETE':
                del self.entries[key]
            else:
                # Version increases across delete/recreate: avoid ABA stale writes.
                version = 1 + max((e['after']['version'] for e in self.events
                                   if e['key'] == key and e['after']), default=0)
                self.entries[key] = Entry(value, scope, version)
        after_entry = self.entries.get(key)
        receipt = dict(request_id=request_id, action=action, key=key,
                       applied=reason is None, reason=reason or 'applied',
                       before=before, after=asdict(after_entry) if after_entry else None)
        if current is not None and current.scope != scope:
            receipt['before'] = receipt['after'] = None
        self.events.append(copy.deepcopy(receipt))
        self.receipts[request_id] = (payload, copy.deepcopy(receipt))
        return receipt

    def read(self, scope):
        return {k: asdict(v) for k, v in self.entries.items() if v.scope == scope}


def run():
    checks = []
    m = Memory()
    a = m.apply('a', 'ADD', 'exception', 'project-A', value='Return None on empty stack')
    assert a['applied'] and a['after']['version'] == 1
    checks.append('add_and_version')
    assert m.apply('a', 'ADD', 'exception', 'project-A', value='Return None on empty stack') == a
    assert len(m.events) == 1
    checks.append('retry_does_not_duplicate_event')
    try:
        m.apply('a', 'DELETE', 'exception', 'project-A', expected=1)
    except ValueError:
        checks.append('request_id_payload_mismatch_rejected')
    else:
        raise AssertionError('request reuse accepted')
    denied = m.apply('b', 'DELETE', 'exception', 'project-B', expected=1)
    assert not denied['applied'] and denied['reason'] == 'scope_denied'
    assert denied['before'] is None and denied['after'] is None
    assert m.read('project-B') == {} and len(m.read('project-A')) == 1
    checks.append('scope_enforced_for_read_and_write')
    u = m.apply('c', 'UPDATE', 'exception', 'project-A', expected=1, value='Raise IndexError on empty stack')
    assert u['applied'] and u['after']['version'] == 2
    stale = m.apply('d', 'DELETE', 'exception', 'project-A', expected=1)
    assert not stale['applied'] and m.entries['exception'].version == 2
    checks.append('stale_delete_rejected')
    d = m.apply('e', 'DELETE', 'exception', 'project-A', expected=2)
    assert d['applied'] and m.read('project-A') == {} and d['before'] == u['after']
    checks.append('delete_preserves_history_in_fixture')
    m.apply('f', 'ADD', 'exception', 'project-A', value='New contract')
    assert m.entries['exception'].version == 3
    stale2 = m.apply('g', 'UPDATE', 'exception', 'project-A', expected=1, value='stale')
    assert not stale2['applied']
    checks.append('delete_recreate_avoids_aba')
    # Expected-loss examples: assumptions, not empirical estimates.
    threshold1 = Fraction(1, 1) / (Fraction(1, 1) + 9)
    threshold2 = Fraction(4, 1) / (Fraction(4, 1) + 6)
    assert threshold1 == Fraction(1, 10) and threshold2 == Fraction(2, 5)
    # Pre-gate cost + fast/slow branch cost, exclusive accounting.
    old_cost = 100 * 40
    gated_cost = 100 * 8 + 20 * 40 + 80 * 1
    assert gated_cost == 1680 and Fraction(old_cost-gated_cost, old_cost) == Fraction(29, 50)
    # A delayed useful exception: deleting saves 2 now but loses 10 with probability 1/4.
    delete_advantage = 2 - Fraction(1, 4) * 10
    assert delete_advantage == -Fraction(1, 2)
    result = dict(kind='offline_teaching_example_not_E03b', model_calls=0,
                  checks=checks, passed=len(checks), events=m.events,
                  arithmetic=dict(loss_thresholds=[str(threshold1),str(threshold2)],
                                  gate_baseline=old_cost,gate_total=gated_cost,
                                  gate_saving=str(Fraction(old_cost-gated_cost, old_cost)),
                                  delete_advantage=str(delete_advantage)),
                  limitations=['single_process_in_memory_fixture',
                               'authenticated_scope_is_assumed_not_implemented',
                               'no_semantic_truth_validator',
                               'no_durable_or_tamper_proof_storage',
                               'no_policy_training_or_performance_claim'])
    return result


if __name__ == '__main__':
    report = run()
    report['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out = Path(__file__).with_name('ch06-operation-demo-2026-09-30.json')
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'model_calls':0,'output':str(out)},ensure_ascii=False))
