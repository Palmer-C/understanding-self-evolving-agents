"""E11-specific dispatch journal. No prices; failed or absent usage stays unknown.

The underlying HTTP backend MUST have retries disabled. We journal and bound
each invocation ourselves; a dispatch is not proof that the server received it.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.error

from .backends import BackendUnavailable, _RETRYABLE_ERRORS, _RETRYABLE_STATUS
from .budget import BudgetExceeded


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


@dataclass(frozen=True)
class SequenceLimits:
    calls: int = 68
    http_attempts: int = 340
    prompt_tokens: int = 2_000_000
    completion_tokens: int = 200_000
    wall_seconds: float = 5400

    def __post_init__(self):
        for key in ('calls', 'http_attempts', 'prompt_tokens', 'completion_tokens'):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError('positive integer required: ' + key)
        if not 0 < self.wall_seconds < float('inf'):
            raise ValueError('positive finite wall limit required')


class MissingUsage(RuntimeError):
    """Success without provider usage cannot be treated as a free call."""


class JournalBackend:
    """One instance per arm/sequence/repeat; all task and lesson calls share it."""

    def __init__(self, backend, directory, limits, *, max_retries=4,
                 retry_backoff=3., clock=time.perf_counter, sleep=time.sleep):
        if getattr(backend, 'max_retries', 0) != 0:
            raise ValueError('nested backend retries must be disabled')
        if type(max_retries) is not int or not 0 <= max_retries <= 4:
            raise ValueError('max_retries must be in 0..4')
        self.backend, self.name = backend, backend.name
        self.directory, self.limits = Path(directory), limits
        self.directory.mkdir(parents=True, exist_ok=False)
        self.max_retries, self.retry_backoff = max_retries, retry_backoff
        self.clock, self.sleep = clock, sleep
        self.started = clock()
        self.context = None
        self.ledger = dict(generate_calls_reserved=0, returned_replies=0,
                           transport_dispatches=0, retries_dispatched=0,
                           known_prompt_tokens=0, known_completion_tokens=0,
                           failed_attempts_usage_unknown=0, missing_usage_replies=0,
                           scripted_estimates=self.name == 'scripted', phases={})
        self.save()

    def save(self):
        atomic_json(self.directory / 'ledger.json', self.snapshot())

    def snapshot(self):
        pending = (self.ledger['transport_dispatches'] - self.ledger['returned_replies']
                   - self.ledger['failed_attempts_usage_unknown'])
        return {**self.ledger, 'elapsed_seconds': self.clock() - self.started,
                'pending_dispatches_usage_unknown': pending,
                'limits': asdict(self.limits), 'usd': None,
                'cost_complete': self.name != 'scripted' and
                    pending == 0 and
                    self.ledger['failed_attempts_usage_unknown'] == 0 and
                    self.ledger['missing_usage_replies'] == 0,
                'scope': 'task and lesson calls once each; monitor CPU recorded separately',
                'bound_note': 'Calls/dispatches hard bounded; token and wall checks before dispatch, '
                    'one request or local verification may overshoot; unknown usage excluded from known totals.'}

    def set_context(self, phase, episode_id):
        if phase not in ('task', 'lesson') or not episode_id:
            raise ValueError('explicit task/lesson context required')
        self.context = {'phase': phase, 'episode_id': episode_id}

    def _check(self, *, new_call=False):
        l, b = self.ledger, self.limits
        reason = None
        if new_call and l['generate_calls_reserved'] >= b.calls:
            reason = 'sequence call cap'
        elif l['transport_dispatches'] >= b.http_attempts:
            reason = 'sequence transport cap'
        elif l['known_prompt_tokens'] >= b.prompt_tokens or l['known_completion_tokens'] >= b.completion_tokens:
            reason = 'sequence known-token soft stop'
        elif self.clock() - self.started >= b.wall_seconds:
            reason = 'sequence wall soft stop'
        if reason:
            atomic_json(self.directory / 'budget-stop.json', {'at': utcnow(), 'reason': reason})
            raise BudgetExceeded(reason)

    @staticmethod
    def _retryable(exc):
        cause = exc.__cause__ if isinstance(exc, BackendUnavailable) else exc
        if isinstance(cause, urllib.error.HTTPError):
            return cause.code in _RETRYABLE_STATUS
        return isinstance(cause, _RETRYABLE_ERRORS)

    def generate(self, messages):
        if self.context is None:
            raise ValueError('set context before generation')
        self._check(new_call=True)
        l = self.ledger
        l['generate_calls_reserved'] += 1
        phase = self.context['phase']
        l['phases'][phase] = l['phases'].get(phase, 0) + 1
        call_dir = self.directory / f"call-{l['generate_calls_reserved']:04d}"
        call_dir.mkdir(exist_ok=False)
        atomic_json(call_dir / 'request.json', {'at': utcnow(), **self.context,
                    'messages': messages, 'status': 'reserved_before_dispatch'})
        self.save()
        for attempt in range(self.max_retries + 1):
            self._check()
            l['transport_dispatches'] += 1
            l['retries_dispatched'] += int(attempt > 0)
            record = {'at': utcnow(), 'attempt_index': attempt,
                      'status': 'dispatch_reserved', 'server_receipt_confirmed': False}
            attempt_path = call_dir / f'attempt-{attempt}.json'
            atomic_json(attempt_path, record)
            self.save()  # A process kill leaves a visible pending dispatch, not zero cost.
            started = self.clock()
            try:
                reply = self.backend.generate(messages)
            except BaseException as exc:
                l['failed_attempts_usage_unknown'] += 1
                cause = exc.__cause__ if isinstance(exc, BackendUnavailable) else exc
                record.update(status='failed_usage_unknown', exception_type=type(exc).__name__,
                              http_status=getattr(cause, 'code', None),
                              elapsed_seconds=self.clock() - started)
                # Exception body/URL might contain credentials; never serialize str(exc).
                atomic_json(attempt_path, record)
                self.save()
                if isinstance(exc, Exception) and self._retryable(exc) and attempt < self.max_retries:
                    self.sleep(self.retry_backoff * (attempt + 1))
                    continue
                raise
            usage = reply.raw.get('usage') if isinstance(reply.raw, dict) else None
            valid_usage = isinstance(usage, dict) and all(
                type(usage.get(k)) is int and usage[k] >= 0
                for k in ('prompt_tokens', 'completion_tokens'))
            if self.name == 'scripted':
                usage = {'prompt_tokens': reply.prompt_tokens, 'completion_tokens': reply.completion_tokens}
                valid_usage = True
            record.update(status='returned', text=reply.text, raw=reply.raw,
                          usage=usage if valid_usage else None,
                          usage_kind='scripted_estimate' if self.name == 'scripted' else 'provider',
                          elapsed_seconds=self.clock() - started)
            atomic_json(attempt_path, record)
            l['returned_replies'] += 1
            if valid_usage:
                l['known_prompt_tokens'] += usage['prompt_tokens']
                l['known_completion_tokens'] += usage['completion_tokens']
            else:
                l['missing_usage_replies'] += 1
            self.save()
            if not valid_usage:
                raise MissingUsage('Provider usage missing or malformed; preserve reply and stop sequence')
            return reply
        raise AssertionError('unreachable')
