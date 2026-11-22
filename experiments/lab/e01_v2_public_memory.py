"""Public-event extraction and recent-memory adapters; offline engineering only.

The trusted host supplies public observations. Strings can contain mislabeled
secrets: types/hashes do NOT establish semantic cleanliness or OS isolation.
No backend, candidate execution, generated M0, or semantic admission is present.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
from .e01_v2_design import (Memory, Lesson, SequenceMemory, canonical, digest,
                            identifier)
from .e01_v2_manifest import ExperimentManifest
from .e01_v2_execution import OracleSuite

SCHEMA = 'e01-public-extraction-offline-v1'
READ_POLICY = 'last-four-publication-order-v1-offline'


@dataclass(frozen=True)
class PublicEvent:
    event_id: str
    task_id: str
    phase: str
    ordinal: int
    kind: str
    text: str


@dataclass(frozen=True)
class ClosedWindow:
    task_id: str
    phase: str
    first: int
    last: int
    event_ids: tuple[str, ...]
    sha256: str


@dataclass(frozen=True)
class ExtractionRequest:
    body: bytes
    provenance: bytes

    def save_new(self, directory):
        # A failed second write can leave a partial directory; never overwrite
        # or silently resume it. This is not an atomic two-file commit.
        p = Path(directory); p.mkdir(parents=True, exist_ok=False)
        (p / 'request.json').write_bytes(self.body)
        (p / 'provenance.json').write_bytes(self.provenance)


class PublicEventStore:
    """One host-owned sequence, closed windows, explicit public projections.

    It accepts no serialized task/episode dictionary and excludes final task
    phases. The caller must also prevent prior/future answers inside public text.
    A separate store is needed for each arm/repeat; no global ID authority.
    """
    def __init__(self, manifest, *, phase):
        if type(manifest) is not ExperimentManifest or phase not in ('prepare', 'online'):
            raise ValueError('typed manifest and preparation/online phase required')
        self._phase = phase
        self._tasks = {x.task_id: x for x in manifest.tasks}
        self._order = getattr(manifest, phase)
        self._manifest_sha = manifest.commitment()['sha256']
        self._events, self._windows = {}, {}
        self._index, self._active, self._first = 0, None, None

    def begin(self, task_id):
        if self._active is not None or self._index >= len(self._order) or task_id != self._order[self._index]:
            raise ValueError('public source task order violation')
        self._active = task_id
        self._first = len(self._events)

    def _record(self, event_id, kind, text):
        identifier(event_id)
        if self._active is None or event_id in self._events:
            raise ValueError('active task and new event ID required')
        if type(text) is not str or not text.strip():
            raise ValueError('nonempty public text required')
        canonical(text)  # Reject invalid UTF-8 surrogate content before storing.
        item = PublicEvent(event_id, self._active, self._phase,
                           len(self._events), kind, text)
        self._events[event_id] = item
        return item

    def model_request(self, event_id, text):
        return self._record(event_id, 'public_model_request', text)

    def model_response(self, event_id, text):
        return self._record(event_id, 'public_model_response', text)

    def public_test(self, event_id, suite, observation_text):
        if type(suite) is not OracleSuite or suite.visibility != 'public' or suite.task_id != self._active:
            raise ValueError('only current public suite may supply an event')
        # No expected-answer, final-suite, or score object is serialized here.
        return self._record(event_id, 'public_test_observation', observation_text)

    def close(self, task_id):
        if task_id != self._active or task_id is None:
            raise ValueError('wrong active task')
        items = tuple(x for x in self._events.values() if x.task_id == task_id)
        if not items: raise ValueError('cannot extract from an empty event history')
        window = ClosedWindow(task_id, self._phase, self._first,
                              len(self._events)-1, tuple(x.event_id for x in items),
                              digest([asdict(x) for x in items]))
        self._windows[task_id] = window
        self._active = None; self._index += 1
        return window

    def extraction(self, window, event_ids):
        if type(window) is not ClosedWindow or self._windows.get(window.task_id) != window:
            raise ValueError('registered closed source window required')
        if type(event_ids) is not tuple or not event_ids or len(set(event_ids)) != len(event_ids):
            raise ValueError('nonempty unique ordered event IDs required')
        rows = []
        for event_id in event_ids:
            if event_id not in window.event_ids:
                raise ValueError('event is absent, future, or outside source task')
            rows.append(self._events[event_id])
        if [x.ordinal for x in rows] != sorted(x.ordinal for x in rows):
            raise ValueError('event order must match occurrence order')
        public = self._tasks[window.task_id].public_payload()
        # Deliberate field construction, never asdict(TaskSpec) then deletion.
        projected_task = {'task_id': public['task_id'], 'prompt': public['prompt'],
                          'files': public['files'], 'writable': public['writable']}
        body = canonical({'schema': SCHEMA, 'role': 'extract_public_lesson',
            'instruction': 'Propose one lesson grounded only in the public source below. Include applicable and inapplicable conditions; cite source event IDs. Do not claim unobserved validation.',
            'source_task': projected_task,
            'events': [{'event_id': x.event_id, 'kind': x.kind, 'text': x.text} for x in rows],
            'maximum_lesson_codepoints': 400})
        provenance = canonical({'schema': SCHEMA, 'manifest_sha256': self._manifest_sha,
            'source_window': asdict(window), 'selected_event_ids': event_ids,
            'selected_events_sha256': digest([asdict(x) for x in rows]),
            'public_task_sha256': digest(projected_task),
            'request_sha256': hashlib.sha256(body).hexdigest(),
            'constructor_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'semantic_admission': 'not performed; trusted-host content review still required'})
        return ExtractionRequest(body, provenance)

    def archive(self):
        return canonical({'schema': SCHEMA, 'manifest_sha256': self._manifest_sha,
            'phase': self._phase, 'events': [asdict(x) for x in self._events.values()],
            'closed_windows': [asdict(x) for x in self._windows.values()]})


@dataclass(frozen=True)
class ReadSnapshot:
    task_id: str
    storage_sha256: str
    selected: Memory

    def payload(self):
        return canonical({'policy': READ_POLICY, 'task_id': self.task_id,
            'storage_sha256': self.storage_sha256,
            'selected': [asdict(x) for x in self.selected.items],
            'selected_sha256': self.selected.sha256(),
            'text_codepoints': sum(len(x.text) for x in self.selected.items)})


def recent_snapshot(task_id, memory):
    identifier(task_id)
    if type(memory) is not Memory: raise ValueError('typed memory required')
    if any(len(x.text) > 400 for x in memory.items):
        raise ValueError('overlong stored item: no silent read-time truncation')
    return ReadSnapshot(task_id, memory.sha256(), Memory(memory.items[-4:]))


class RecentSequence:
    """Adapter around legacy state; limits admission before forming snapshots.

    The source receipt/semantic review is not yet bound to Lesson publication.
    `validated` remains an explicit caller decision, not an automatic validator.
    This adapter is not wired into the old scripted run or a live backend.
    """
    def __init__(self, arm, initial, tasks):
        if arm not in ('R', 'F', 'U') or type(initial) is not Memory:
            raise ValueError('R/F/U typed initial memory required')
        if arm == 'R' and initial.items:
            raise ValueError('R receives no preparation memory')
        if arm != 'R' and not 1 <= len(initial.items) <= 4:
            raise ValueError('F/U require one to four admitted preparation items')
        if any(len(x.text) > 400 for x in initial.items):
            raise ValueError('initial item exceeds admission cap')
        self._state = SequenceMemory(arm, initial, tasks, evaluation_follows=True)
        self._snapshot = None
        self.read_events, self.admission_events = [], []

    def begin(self, task_id):
        if self._state.arm == 'U' and self._state.just_finished is not None:
            raise ValueError('record previous update decision before next task')
        memory = self._state.begin(task_id)
        self._snapshot = recent_snapshot(task_id, memory)
        self.read_events.append(self._snapshot)
        return self._snapshot

    def current(self, task_id):
        if self._state.active != task_id or self._snapshot is None:
            raise ValueError('read is bound to active task')
        if self._state.memory.sha256() != self._snapshot.storage_sha256:
            raise ValueError('storage changed within task')
        return self._snapshot

    def finish(self, task_id):
        self._state.finish(task_id); self._snapshot = None

    def publish(self, lesson, *, validated):
        if type(lesson) is not Lesson or type(validated) is not bool:
            raise ValueError('typed lesson and explicit decision required')
        length_ok = len(lesson.text) <= 400
        accepted = validated and length_ok
        self._state.publish(lesson, validated=accepted)
        self.admission_events.append({'item_id':lesson.item_id,
            'accepted':accepted,'length_ok':length_ok,'caller_validated':validated})
        return accepted

    def stored_memory(self):
        return self._state.memory

    def freeze_transfer(self, tasks):
        if self._state.active is not None or self._state.index != len(self._state.tasks):
            raise ValueError('online sequence incomplete')
        if self._state.arm == 'U' and self._state.just_finished is not None:
            raise ValueError('last update decision has not been recorded')
        if set(tasks) & set(self._state.tasks):
            raise ValueError('transfer task overlaps online sequence')
        return FrozenRecentReader(self._state.memory, tasks)


class FrozenRecentReader:
    """Read-only transfer cursor: no write/history inheritance method."""
    def __init__(self, memory, tasks):
        if type(memory) is not Memory or type(tasks) is not tuple or not tasks or len(set(tasks)) != len(tasks):
            raise ValueError('typed memory and unique ordered transfer tasks required')
        for task in tasks: identifier(task)
        if set(tasks) & {x.source_task for x in memory.items}:
            raise ValueError('transfer task overlaps memory sources')
        recent_snapshot(tasks[0], memory)
        self._memory, self._tasks = memory, tasks
        self._index, self._active = 0, None

    def begin(self, task_id):
        if self._active is not None or self._index == len(self._tasks) or task_id != self._tasks[self._index]:
            raise ValueError('transfer task order violation')
        self._active = recent_snapshot(task_id, self._memory)
        return self._active

    def current(self, task_id):
        if self._active is None or self._active.task_id != task_id:
            raise ValueError('wrong active transfer task')
        return self._active

    def finish(self, task_id):
        self.current(task_id)
        self._active = None; self._index += 1
