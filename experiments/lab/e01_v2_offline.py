"""Scripted integration fixture for E01 v2; intentionally no paid backend.

Candidate text, public scores, and hidden outcomes are constructed fixtures.
They test control/data flow, never task-solving ability or sandbox isolation.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
from .e01_v2_design import (Memory, Lesson, PublicCandidate, SequenceMemory,
                            select_public, create_sequence_directory, canonical)
from .e01_v2_resources import (ResourceJournal, Limits, BudgetStop, PendingDispatch,
                               sum_unique_ledgers)


class SimulatedTransportFailure(RuntimeError): pass


@dataclass(frozen=True)
class ScriptReply:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ScriptedProvider:
    """Finite response script; synthetic token counts, no credentials/network."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.invocations = 0
        self.requests = []

    def generate(self, public_request):
        self.invocations += 1
        self.requests.append(json.loads(json.dumps(public_request)))
        if not self.replies: raise RuntimeError('script exhausted')
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException): raise reply
        if type(reply) is not ScriptReply: raise ValueError('invalid fixture reply')
        return reply


def generate_scripted(provider, journal, *, call_id, role, task_id, public_request,
                      max_attempts=1):
    """Reserve before every invocation. Reopened calls are audit-only, not replay.

    Supports only the in-process ScriptedProvider, not a duck-typed network
    backend. Real usage parsing and cancellation need a later reviewed adapter.
    """
    if type(provider) is not ScriptedProvider:
        raise TypeError('this integration entry point is offline only')
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError('positive attempt count required')
    if not isinstance(public_request, dict) or set(public_request) != {'task', 'memory', 'role'}:
        raise ValueError('public fixture request fields required')
    if public_request['task'] != task_id or public_request['role'] != role:
        raise ValueError('request context mismatch')
    reserved = journal.record(f'{call_id}-reserve', 'call', call_id=call_id,
                              role=role, task_id=task_id)
    if not reserved: raise PendingDispatch('existing logical call must not be redispatched')
    for i in range(max_attempts):
        aid = f'{call_id}-a{i}'
        journal.record(aid, 'attempt', call_id=call_id)
        try:
            reply = provider.generate(public_request)
        except BaseException as error:
            journal.record(f'{call_id}-s{i}', 'settle', call_id=call_id,
                           attempt_id=aid, outcome='failure', usage=None)
            if isinstance(error, SimulatedTransportFailure) and i + 1 < max_attempts:
                continue
            journal.record(f'{call_id}-close', 'close', call_id=call_id)
            raise
        usage = None
        if type(reply.prompt_tokens) is int and reply.prompt_tokens >= 0 and type(reply.completion_tokens) is int and reply.completion_tokens >= 0:
            usage = {'prompt_tokens': reply.prompt_tokens, 'completion_tokens': reply.completion_tokens}
        journal.record(f'{call_id}-s{i}', 'settle', call_id=call_id,
                       attempt_id=aid, outcome='success', usage=usage)
        return reply
    raise AssertionError('unreachable')


def write_new_json(path, value):
    with Path(path).open('xb') as stream: stream.write(canonical(value))


def run_offline_demo(root, run_id):
    """Three arms, two repeats, two tasks; all outcomes deliberately synthetic.

    Per-task allowance=3 logical calls, 4 dispatch attempts, 3 public tests.
    U uses 2 solve + 1 update on its first task, then 3 solve on its last;
    F/R use 3 solve throughout. First update's transport failure is retained.
    M0 is a manual fixture: zero API preparation, not claimed free human work.
    """
    root = Path(root)
    from .e01_v2_design import identifier
    identifier(run_id)
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    initial = Memory((Lesson('seed', 'Check empty input.', 'prep0', 'prepare'),))
    initial.save_new(run_dir / 'm0.json')
    write_new_json(run_dir / 'manifest.json', {
        'identity': 'synthetic offline engineering fixture; not E01 capability data',
        'run_id': run_id, 'arms': ['R', 'F', 'U'], 'repeats': 2, 'tasks': ['t0', 't1'],
        'm0_sha256': initial.sha256(), 'preparation': 'manual fixture; no API generation; human time not measured',
        'limits_per_task': asdict(Limits(3, 4, 3)), 'hidden_isolation_verified': False,
        'paid_execution_available': False})
    prep = ResourceJournal(run_dir / 'preparation.jsonl', Limits(0, 0, 0))
    reports, real_ledgers, deployments = [], [('preparation', prep.summary())], {}
    for arm in ('R', 'F', 'U'):
        for repeat in range(2):
            directory = create_sequence_directory(root, run_id=run_id, arm=arm, repeat=repeat)
            state = SequenceMemory(arm, initial, ('t0', 't1'))
            initial_sha = state.memory.sha256()
            local_ledgers, tasks = [], []
            for ti, task in enumerate(state.tasks):
                current_memory = state.begin(task)
                task_dir = directory / task; task_dir.mkdir()
                journal = ResourceJournal(task_dir / 'resources.jsonl', Limits(3, 4, 3))
                # The third candidate has less public success despite a hidden
                # fixture outcome of True; choosing it would be oracle leakage.
                nsolve = 2 if arm == 'U' and ti == 0 else 3
                replies = [ScriptReply(f'return {i}', 10 + i, 2) for i in range(nsolve)]
                if arm == 'U' and ti == 0:
                    replies += [SimulatedTransportFailure('synthetic failure'), ScriptReply('Retain empty-case guard.', 8, 3)]
                provider = ScriptedProvider(replies)
                candidates = []
                for i in range(nsolve):
                    reply = generate_scripted(provider, journal, call_id=f'solve{i}', role='solve', task_id=task,
                        public_request={'task': task, 'memory': [x.text for x in current_memory.items], 'role': 'solve'})
                    journal.record(f'test{i}', 'test', task_id=task)
                    candidates.append(PublicCandidate(f'c{i}', i, reply.text, [1, 2, 0][i], 3, True))
                selected = select_public(tuple(candidates))
                # Submission is persisted before any access to hidden fixture outcomes.
                write_new_json(task_dir / 'submission.json', {'candidate_id': selected.candidate_id,
                    'code': selected.code, 'public_passed': selected.public_passed,
                    'memory_sha256': current_memory.sha256()})
                state.finish(task)
                if arm == 'U' and ti == 0:
                    update = generate_scripted(provider, journal, call_id='update0', role='update', task_id=task,
                        max_attempts=2,
                        public_request={'task': task, 'memory': [x.text for x in current_memory.items], 'role': 'update'})
                    state.publish(Lesson('u0', update.text, task, 'online'), validated=True)
                hidden_fixture = {'c0': True, 'c1': False, 'c2': True}
                write_new_json(task_dir / 'evaluation.json', {'synthetic_selected_pass': hidden_fixture[selected.candidate_id],
                    'identity': 'constructed hidden outcome; not executed tests or model performance'})
                row = {'task_id': task, 'selected': selected.candidate_id,
                       'synthetic_selected_pass': hidden_fixture[selected.candidate_id],
                       'candidate_count': len(candidates), 'provider_invocations': provider.invocations,
                       'request_fields': [sorted(x) for x in provider.requests],
                       'ledger': journal.summary(), 'memory_after_sha256': state.memory.sha256()}
                write_new_json(task_dir / 'complete.json', row)
                tasks.append(row)
                lid = f'{arm}-r{repeat}-{task}'
                local_ledgers.append((lid, journal.summary()))
                real_ledgers.append((lid, journal.summary()))
            report = {'arm': arm, 'repeat': repeat, 'initial_memory_sha256': initial_sha,
                      'tasks': tasks, 'memory_events': state.events,
                      'resource_totals': sum_unique_ledgers(local_ledgers)}
            write_new_json(directory / 'complete.json', report)
            reports.append(report)
            deployments[f'{arm}-r{repeat}'] = sum_unique_ledgers(
                local_ledgers + ([('preparation', prep.summary())] if arm != 'R' else []))
    result = {'identity': 'synthetic offline integration, no model ability inference',
              'api_calls': 0, 'sequences': len(reports), 'task_opportunities': sum(len(r['tasks']) for r in reports),
              'research_actual_resources': sum_unique_ledgers(real_ledgers),
              'independent_deployment_resources': deployments, 'reports': reports,
              'limitations': ['no generated-code execution or OS isolation',
                              'no real model, independent task families, or confirmatory sample',
                              'logical calls and token counts here are scripted events, not paid use',
                              'request interruption cannot guarantee exactly-once external execution']}
    write_new_json(run_dir / 'complete.json', result)
    return result
