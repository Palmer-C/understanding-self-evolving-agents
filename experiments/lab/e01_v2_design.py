"""E01 v2 offline contracts. No API, execution sandbox, or ability verdict.

Public-only types limit accidental information flow; they are NOT a security
boundary against adversarial Python or generated code. Runner isolation remains
an explicit prerequisite of any new hidden-test capability experiment.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import re


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value):
        raise ValueError('safe nonempty identifier required')
    if value.upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)),
                        *(f'LPT{i}' for i in range(10))}:
        raise ValueError('reserved Windows identifier')
    return value


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be integer >= {minimum}')
    return value


@dataclass(frozen=True)
class Lesson:
    item_id: str
    text: str
    source_task: str
    source_phase: str

    def __post_init__(self):
        identifier(self.item_id); identifier(self.source_task)
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError('nonempty lesson required')
        if self.source_phase not in ('prepare', 'online'):
            raise ValueError('evaluation data cannot source a lesson')


@dataclass(frozen=True)
class Memory:
    items: tuple[Lesson, ...] = ()

    def __post_init__(self):
        if type(self.items) is not tuple or any(type(x) is not Lesson for x in self.items):
            raise ValueError('immutable Lesson tuple required')
        if len({x.item_id for x in self.items}) != len(self.items):
            raise ValueError('duplicate memory ID')

    def payload(self):
        return canonical([asdict(x) for x in self.items])

    def sha256(self):
        return hashlib.sha256(self.payload()).hexdigest()

    def save_new(self, path):
        with Path(path).open('xb') as stream:
            stream.write(self.payload())


@dataclass(frozen=True)
class PublicCandidate:
    candidate_id: str
    order: int
    code: str
    public_passed: int
    public_total: int
    public_ran: bool
    submittable: bool = True

    def __post_init__(self):
        identifier(self.candidate_id); integer(self.order, 'order')
        integer(self.public_passed, 'public_passed'); integer(self.public_total, 'public_total', 1)
        if type(self.public_ran) is not bool or type(self.submittable) is not bool:
            raise ValueError('boolean status required')
        if self.public_passed > self.public_total or (not self.public_ran and self.public_passed):
            raise ValueError('impossible public score')
        if not isinstance(self.code, str) or (self.submittable and not self.code.strip()):
            raise ValueError('submittable candidate needs code')


def select_public(candidates: tuple[PublicCandidate, ...]):
    """One final candidate; runnable > unrunnable, then score, then earliest."""
    if type(candidates) is not tuple or any(type(x) is not PublicCandidate for x in candidates):
        raise ValueError('public candidate tuple required')
    if len({x.order for x in candidates}) != len(candidates) or len({x.candidate_id for x in candidates}) != len(candidates):
        raise ValueError('candidate order and ID must be unique')
    if len({x.public_total for x in candidates}) > 1:
        raise ValueError('same public suite required; raw counts otherwise incomparable')
    eligible = [x for x in candidates if x.submittable]
    return max(eligible, key=lambda x: (x.public_ran, x.public_passed, -x.order), default=None)


class SequenceMemory:
    """Deterministic policy state; publish only just-completed task records.

    `validated` is a caller-supplied protocol verdict, not proof of semantic
    truth. No hidden score is accepted. The runner must enforce evaluator access.
    """
    def __init__(self, arm, initial: Memory, tasks: tuple[str, ...], *, evaluation_follows=False):
        if arm not in ('R', 'F', 'U', 'L') or type(initial) is not Memory:
            raise ValueError('invalid arm or initial memory')
        if type(tasks) is not tuple or not tasks or len(set(tasks)) != len(tasks):
            raise ValueError('unique ordered tasks required')
        for task in tasks: identifier(task)
        if any(x.source_phase != 'prepare' for x in initial.items):
            raise ValueError('M0 must contain only preparation material')
        if set(tasks) & {x.source_task for x in initial.items}:
            raise ValueError('preparation and online task identities overlap')
        if type(evaluation_follows) is not bool:
            raise ValueError('evaluation_follows must be boolean')
        self.arm, self.tasks = arm, tasks
        self.initial_sha256 = initial.sha256()
        self.memory = Memory() if arm == 'R' else initial
        self.index, self.active, self.just_finished = 0, None, None
        self.temporary_note = None
        self.evaluation_follows = evaluation_follows
        self.events = []

    def begin(self, task):
        if self.active is not None or self.index == len(self.tasks) or task != self.tasks[self.index]:
            raise ValueError('task order violation')
        self.active, self.just_finished = task, None
        return self.memory

    def note(self, text):
        if self.arm != 'L' or self.active is None or not isinstance(text, str):
            raise ValueError('only active L task can retain a temporary note')
        self.temporary_note = text

    def finish(self, task):
        if task != self.active or task is None:
            raise ValueError('wrong active task')
        self.active, self.just_finished, self.temporary_note = None, task, None
        self.index += 1

    def publish(self, lesson: Lesson, *, validated: bool):
        if type(validated) is not bool or type(lesson) is not Lesson:
            raise ValueError('explicit validation and Lesson required')
        if self.arm != 'U' or self.active is not None or self.just_finished is None:
            raise ValueError('write forbidden at this arm/time')
        if lesson.source_task != self.just_finished or lesson.source_phase != 'online':
            raise ValueError('future/stale or non-online source')
        if self.index == len(self.tasks) and not self.evaluation_follows:
            raise ValueError('no consumer for last-task update')
        before = self.memory.sha256()
        if validated:
            self.memory = Memory(self.memory.items + (lesson,))
        self.events.append({'source': lesson.source_task, 'accepted': validated,
                            'before': before, 'after': self.memory.sha256()})
        self.just_finished = None  # One publication decision, including rejection.


def create_sequence_directory(root, *, run_id, arm, repeat):
    identifier(run_id)
    if arm not in ('R', 'F', 'U', 'L'): raise ValueError('invalid arm')
    integer(repeat, 'repeat')
    path = Path(root) / run_id / arm / f'repeat-{repeat:04d}'
    path.mkdir(parents=True, exist_ok=False)
    return path
