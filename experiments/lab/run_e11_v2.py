"""Independent E11 v2 engineering pilot. Default: offline manifest only.

--execute requires a matching saved --approved-manifest and prior user consent.
The manifest is a consistency check, not proof of consent. No resume/overwrite.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
TASKS_ROOT = ROOT / 'experiments/tasks/v1'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.lab.backends import build_backend
from experiments.lab.budget import Budget, BudgetExceeded
from experiments.lab.e05_v2 import source_files, digest
from experiments.lab.e11_resources_v2 import JournalBackend, SequenceLimits, atomic_json, utcnow
from experiments.lab.e11_timing_v2 import TimingController
from experiments.lab.e11_analysis_v2 import ARMS, SequenceRun, analyze
from experiments.lab.protocol_agent_v3 import ProtocolAgentV3, SYSTEM_PROMPT
from experiments.lab.sandbox import Sandbox, SandboxViolation
from experiments.lab.tasks import load_task_dir
from experiments.lab.trace import new_run_id

VERSION = 'e11-v2-20260930'
ALLOWED_SPLITS = {'train', 'select-valid', 'regression'}
LESSON_PROMPT = ('从下列公开任务、实际可写源码和执行判定提炼一条可复用经验。'
                 '区分观察与猜测，不声称跨任务已经有效。只输出一段纯文本，1至120个字符。')


class VerificationUnavailable(RuntimeError):
    pass


class E11Sandbox(Sandbox):
    """Stricter local file boundary without modifying historical executors.

    Generated Python is still executed locally, not an OS security sandbox.
    """
    def _resolve(self, rel):
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root):
            raise SandboxViolation('path outside task root')
        return p

    def write_file(self, rel, content):
        p = self._resolve(rel)
        if p.relative_to(self.root).as_posix() not in self.mutable_files:
            raise SandboxViolation('only initial mutable Python files are writable')
        return super().write_file(rel, content)

    def run(self, command, timeout=120.):
        result = super().run(command, timeout)
        if result.timed_out:
            raise VerificationUnavailable('verification timeout; missing outcome, not task failure')
        return result


def validate_tasks(tasks, split):
    if type(split) is not int or not 0 < split < len(tasks):
        raise ValueError('split must leave two nonempty segments')
    ids = set()
    for task in tasks:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', task.task_id) or task.task_id in ids:
            raise ValueError('unique path-safe task ID required')
        ids.add(task.task_id)
        if task.split not in ALLOWED_SPLITS or not task.statement.strip():
            raise ValueError('ineligible split or empty task')
        for name in task.files:
            p = Path(name)
            if p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name:
                raise ValueError('unsafe task manifest path')


def memory_prompt(memory):
    if not memory:
        return ''
    return '\n以下经验只在来源任务上观察过，可能错误；须按当前任务核验。\n' + '\n'.join(memory)


def run_sequence(arm, tasks, backend, out_dir, *, split, repeat_id='r0',
                 limits=None, write_limit=4, max_retries=4, retry_backoff=3., seed=20260930):
    validate_tasks(tasks, split)
    controller = TimingController(arm, len(tasks), write_attempt_limit=write_limit)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    limits = limits or SequenceLimits(calls=len(tasks)*8+write_limit,
                                     http_attempts=(len(tasks)*8+write_limit)*(max_retries+1))
    atomic_json(out_dir / 'config.json', {'version': VERSION, 'arm': arm, 'split': split,
        'repeat_id': repeat_id, 'seed_label_not_provider_seed': seed, 'limits': asdict(limits),
        'task_ids': [t.task_id for t in tasks], 'initial_memory': [], 'write_limit': write_limit})
    journal = JournalBackend(backend, out_dir/'calls', limits,
                             max_retries=max_retries, retry_backoff=retry_backoff)
    events, memory = [], []
    current = {'phase': 'before_first_episode'}

    def save_progress(status):
        atomic_json(out_dir/'in-progress.json', {'status': status, 'events': events,
                    'memory': memory, 'current': current, 'ledger': journal.snapshot()})

    try:
        for i, task in enumerate(tasks):
            journal._check(new_call=True)
            episode_id = f'{repeat_id}-{i:02d}-{task.task_id}'
            current = {'phase': 'task', 'episode_id': episode_id, 'memory_before': list(memory)}
            save_progress('incomplete_sequence_do_not_merge')
            episode_dir = out_dir/'episodes'/episode_id
            sandbox = E11Sandbox.create_temp(prefix='e11-v2')
            sandbox.protected = set(task.protected)
            sandbox.mutable_files = {name for name in source_files(task, type('EmptyTrace', (), {'steps': []})())
                if Path(name).name not in task.protected and not Path(name).name.endswith('_test.py')}
            journal.set_context('task', episode_id)
            agent = ProtocolAgentV3(journal, SYSTEM_PROMPT+memory_prompt(memory), name=f'{VERSION}:{arm}')
            try:
                trace = agent.run_episode(task, budget=Budget(), sandbox=sandbox,
                                          seed=seed+i, out_dir=episode_dir)
            finally:
                sandbox.cleanup()
            if type(trace.verdict) is not bool:
                raise VerificationUnavailable('missing explicit verdict')
            # A shared-budget stop is infrastructure truncation, not an observed task failure.
            if (out_dir/'calls'/'budget-stop.json').exists():
                raise BudgetExceeded('shared sequence resource stop; no complete-sequence analysis')
            decision = controller.observe(episode_id=episode_id, verdict=trace.verdict, task_text=task.statement)
            event = {'episode_id': episode_id, 'task_id': task.task_id, 'verdict': trace.verdict,
                     'memory_before_sha256': digest(memory), 'decision': decision,
                     'trace': str((episode_dir/'trace.json').relative_to(out_dir)), 'lesson': None}
            events.append(event)
            if decision['decision'] == 'attempt_reserved':
                current = {'phase': 'lesson', 'episode_id': episode_id}
                lesson_dir = out_dir/'lessons'/episode_id
                lesson_dir.mkdir(parents=True, exist_ok=False)
                payload = {'task_id': task.task_id, 'statement': task.statement,
                           'mutable_source': source_files(task, trace), 'verdict': trace.verdict}
                atomic_json(lesson_dir/'source.json', payload)
                event['lesson'] = {'status': 'reserved', 'memory_before_sha256': digest(memory)}
                save_progress('incomplete_sequence_do_not_merge')
                journal.set_context('lesson', episode_id)
                try:
                    reply = journal.generate([{'role': 'system', 'content': LESSON_PROMPT},
                                              {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}])
                except BaseException as exc:
                    event['lesson']['status'] = 'failed_no_publish'
                    atomic_json(lesson_dir/'publication.json', {**event['lesson'],
                                'exception_type': type(exc).__name__, 'quota_refunded': False})
                    raise
                candidate = reply.text.strip()
                reason = ('empty' if not candidate else 'too_long' if len(candidate) > 120 else
                          'not_single_paragraph' if '\n' in candidate or '\r' in candidate else
                          'duplicate' if candidate in memory else None)
                if reason is None:
                    memory.append(candidate)
                event['lesson'].update(status='published' if reason is None else 'rejected',
                    rejection_reason=reason, candidate=candidate, quota_refunded=False,
                    memory_after_sha256=digest(memory), admission_scope='format only, not truth or transfer validity')
                atomic_json(lesson_dir/'publication.json', event['lesson'])
            save_progress('incomplete_sequence_do_not_merge')
        result = {'version': VERSION, 'arm': arm, 'repeat_id': repeat_id, 'split': split,
                  'verdicts': [x['verdict'] for x in events], 'events': events, 'final_memory': memory,
                  'ledger': journal.snapshot(), 'monitor_seconds': sum(x['decision']['monitor_seconds'] for x in events),
                  'sequence_wall_seconds': time.perf_counter()-started,
                  'evidence_kind': 'offline_harness_only' if backend.name == 'scripted' else 'engineering_pilot',
                  'status': 'complete', 'p5_status': 'open'}
        atomic_json(out_dir/'complete.json', result)
        save_progress('complete_see_complete_json')
        return result
    except BaseException as exc:
        save_progress('interrupted_do_not_resume_or_impute_missing_outcomes')
        atomic_json(out_dir/'interruption.json', {'at': utcnow(), 'exception_type': type(exc).__name__,
                    'current': current, 'completed_episode_count': len(events), 'ledger': journal.snapshot(),
                    'billing': 'Pending and failed dispatch usage may be unknown; never reset or impute zero.'})
        raise


def select_tasks(before, after):
    if before == after:
        raise ValueError('pilot requires two distinct families; stable control needs a separate design')
    all_tasks = [load_task_dir(p) for p in sorted(TASKS_ROOT.glob('*/*'))
                 if (p/'test.json').is_file()]
    selected = []
    for family in (before, after):
        group = sorted((t for t in all_tasks if t.family == family and t.split in ALLOWED_SPLITS),
                       key=lambda t: t.task_id)
        if len(group) < 4:
            raise ValueError('at least four eligible tasks required for ' + family)
        selected.extend(group[:4])
    validate_tasks(selected, 4)
    return selected


def preflight(before='offbyone', after='mutabledefault'):
    tasks = select_tasks(before, after)
    sources = ['run_e11_v2.py', 'e11_resources_v2.py', 'e11_timing_v2.py', 'e11_analysis_v2.py',
               'trigger_signals.py', 'e01_arms.py', 'static_agent.py', 'protocol_agent_v3.py', 'action_protocol_v3.py',
               'backends.py', 'budget.py', 'sandbox.py', 'tasks.py', 'trace.py',
               'e05_v2.py', 'e05_arms.py', 'taskset_spec.py']
    hashes = {p: hashlib.sha256((ROOT/'experiments/lab'/p).read_bytes()).hexdigest() for p in sources}
    hashes['protocol'] = hashlib.sha256((ROOT/'experiments/protocols/E11-v2.md').read_bytes()).hexdigest()
    base_url = os.environ.get('AGENT_LAB_BASE_URL', '').rstrip('/')
    url = urlsplit(base_url)
    if base_url and (url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment):
        raise ValueError('backend must be HTTPS without embedded credentials or query parameters')
    backend_identity = {'model': os.environ.get('AGENT_LAB_MODEL'), 'base_url': base_url, 'timeout': 120.0}
    design = {'version': VERSION, 'purpose': 'single sequence engineering pilot; P5 remains open',
              'backend_identity': backend_identity,
              'families': [before, after], 'split': 4, 'repeats': 1, 'arms': list(ARMS),
              'arm_order': list(ARMS), 'temperature': .7, 'max_retries': 4,
              'episode_budget': Budget().as_dict(), 'sequence_limits': asdict(SequenceLimits()),
              'write_attempt_limit': 4, 'period': 2, 'error_threshold': 2,
              'drift_window': 2, 'drift_threshold': .5, 'novelty_threshold': .5,
              'source_sha256': hashes, 'task_manifest': [
                  {'id': t.task_id, 'family': t.family, 'split': t.split, 'sha256': digest(vars(t))} for t in tasks],
              'primary_episodes': 24, 'max_lesson_calls': 12,
              'max_generate_calls': 204, 'max_transport_dispatches': 1020,
              'no_monetary_hard_cap': True,
              'limitations': ['One chosen family pair, one repeat, no population CI.',
                  'Fixed arm order may be confounded with service drift.',
                  'Family switch changes task difficulty/interfaces as well as description distribution.',
                  'Tests protected from file writes but readable; generated code is not OS-sandboxed.',
                  'Published lessons pass format admission only; no verified lesson truth.',
                  'A common cap is not equal realized cost; no automated proposition adjudication.']}
    return tasks, design


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before', default='offbyone')
    p.add_argument('--after', default='mutabledefault')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--approved-manifest', type=Path)
    p.add_argument('--save-preflight', type=Path)
    args = p.parse_args(argv)
    tasks, design = preflight(args.before, args.after)
    if args.save_preflight:
        if args.save_preflight.exists():
            raise ValueError('preflight destination already exists')
        atomic_json(args.save_preflight, design)
    print(json.dumps(design, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        return 0
    if not args.approved_manifest or json.loads(args.approved_manifest.read_text(encoding='utf-8')) != design:
        raise ValueError('matching preflight required before paid execution')
    identity = design['backend_identity']
    if not identity['model'] or not identity['base_url']:
        raise ValueError('explicit backend identity must be frozen before execution')
    # No model request is sent before this explicit branch.
    backend = build_backend('openai', model=identity['model'], base_url=identity['base_url'],
                            timeout=identity['timeout'], temperature=.7, max_retries=0)
    out = ROOT/'experiments/runs'/new_run_id('E11v2')
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out/'config.json', {'design': design, 'started_at': utcnow(),
        'backend': {'model': backend.model, 'base_url': backend.base_url, 'timeout': backend.timeout,
                    'backend_internal_retries': 0, 'journal_max_retries': 4}})
    completed = {}
    try:
        for arm in ARMS:
            completed[arm] = run_sequence(arm, tasks, backend, out/'sequences'/f'{arm}-pair0-r0', split=4)
            atomic_json(out/'partial.json', {'completed_arms': list(completed)})
        records = {a: {'pair0': [SequenceRun('r0', tuple(v['verdicts']), 4)]} for a, v in completed.items()}
        summary = {'config': design, 'arms': completed, 'analysis': analyze(records), 'finished_at': utcnow()}
        atomic_json(out/'summary.json', summary)
        atomic_json(ROOT/'experiments/results'/f'{out.name}.json', summary)
    except BaseException as exc:
        atomic_json(out/'interruption.json', {'at': utcnow(), 'exception_type': type(exc).__name__,
                    'completed_arms': list(completed), 'status': 'no_partial_arm_comparison'})
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
