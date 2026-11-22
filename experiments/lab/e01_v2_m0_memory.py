"""Offline M0 preparation and verified memory merge; contracts only.

Implements the "M0 准备记忆合并" piece named at the end of E01-v2-draft §16 and
in the §17 limitation list. It is the offline component that precedes the real
runner and the true preparation set; no backend, no candidate execution, and no
OS isolation are present here.

Two pieces:

1. M0Builder — builds M0 once from a preparation set and byte-clones it to the
   F/U/L arms. Per §3, F/U/L must receive a byte-for-byte identical copy of M0;
   per-arm regeneration that could drift the source is forbidden. Building from
   the same preparation set twice yields the same M0 hash, so a silent per-arm
   rebuild cannot diverge from the shared M0.

2. MemoryMergeStore — append-only merge of verified published lessons (online
   phase) for one arm-repeat of one run. It mirrors the immutability and identity
   binding of the budget/cursor contracts (R6/R7): an incoming lesson whose id is
   already stored must be byte-equal to the stored one (idempotent replay) or it
   is rejected (MergeConflict) — a published lesson can never be silently
   overwritten. The store is bound to (run_id, arm, repeat, m0_sha256); reopening
   under a different identity is rejected (IdentityMismatch), so a persisted
   memory cannot be repointed at another experiment or a regenerated M0.

The semantic truth of each published lesson is a caller-supplied validated
decision (as in RecentSequence.publish), not proven here. Merge is a pure data
operation over Memory/Lesson.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import json
import sqlite3
from .e01_v2_design import Lesson, Memory, canonical, digest, identifier, integer


class MergeConflict(RuntimeError):
    pass


class IdentityMismatch(RuntimeError):
    pass


class FrozenArmViolation(RuntimeError):
    """Raised when an R/F arm is asked to merge online (published) lessons.

    Per E01-v2-draft §18/§19, R holds no preparation memory and F is a frozen
    M0; neither admits online updates. The merge store enforces this at the
    component layer (R10) rather than silently letting a caller write into a
    frozen arm.
    """


@dataclass(frozen=True)
class M0BuildRecord:
    m0_sha256: str
    preparation_count: int
    preparation_ids: tuple[str, ...]
    lineage_sha256: str
    build_impl_sha256: str

    def payload(self):
        return canonical(asdict(self))


def build_m0(items: tuple[Lesson, ...]) -> Memory:
    """Build M0 from a preparation set; only preparation material is allowed."""
    if type(items) is not tuple or any(type(x) is not Lesson for x in items):
        raise ValueError('preparation Lesson tuple required')
    for it in items:
        if it.source_phase != 'prepare':
            raise ValueError('M0 may hold preparation material only')
    return Memory(items)


class M0Builder:
    """Builds M0 once; deterministic and byte-cloneable to F/U/L arms.

    Building from the same preparation set twice yields the same M0 hash, so a
    per-arm rebuild cannot quietly diverge from the shared M0 (§3). Arms receive a
    byte-cloned copy via ``clone_for_arm``; they never rebuild independently.
    """

    def __init__(self, preparation_items: tuple[Lesson, ...]):
        if type(preparation_items) is not tuple or not preparation_items:
            raise ValueError('nonempty preparation items required')
        m0 = build_m0(preparation_items)
        self._m0 = m0
        self._record = M0BuildRecord(
            m0_sha256=m0.sha256(),
            preparation_count=len(preparation_items),
            preparation_ids=tuple(x.item_id for x in preparation_items),
            lineage_sha256=digest([(x.item_id, x.source_task) for x in preparation_items]),
            build_impl_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    @property
    def m0(self) -> Memory:
        return self._m0

    @property
    def record(self) -> M0BuildRecord:
        return self._record

    def clone_for_arm(self, arm: str) -> Memory:
        """Return a byte-for-byte identical M0 for the given arm.

        R holds no preparation memory (§3), so it receives an empty Memory that
        matches what SequenceMemory uses for R. F/U/L receive the exact M0
        items, hence the exact M0 hash. The clone is asserted to be identical; a
        divergent clone would mean a regeneration bug, not a clone.
        """
        if arm == 'R':
            return Memory()
        if arm not in ('F', 'U', 'L'):
            raise ValueError('unknown arm')
        clone = Memory(self._m0.items)
        if clone.sha256() != self._m0.sha256():
            raise ValueError('clone diverged from M0 (regeneration bug)')
        return clone


class MemoryMergeStore:
    """Append-only merge of verified published lessons under (run_id, arm, repeat, m0).

    The store holds the current memory for one arm-repeat of one run. On creation
    it is seeded with the arm's M0 clone (or empty for R; an R store rejects a
    non-empty seed). Each ``merge`` call integrates a tuple of verified published
    (online-phase) lessons under immutability: a lesson whose id already exists
    must be byte-equal to the stored one (idempotent replay) else it is rejected
    (MergeConflict). The store is bound to a (run_id, arm, repeat, m0_sha256)
    identity; reopening under a different identity is rejected (IdentityMismatch).

    R/F arms reject online updates at the component layer (FrozenArmViolation,
    R10): R holds no memory and F is a frozen M0, so neither may merge. The merge
    transaction writes to the database first and only syncs the in-memory cache
    after COMMIT, so a partial failure never leaves a ghost entry that a later
    idempotent replay would then skip (R9).
    """

    def __init__(self, path, run_id, arm, repeat, m0: Memory, *, create=False):
        identifier(run_id)
        if arm not in ('R', 'F', 'U', 'L'):
            raise ValueError('unknown arm')
        integer(repeat, 'repeat')
        if type(m0) is not Memory:
            raise ValueError('typed M0 seed required')
        # R10 (Codex 2026-10-01 13:15): R holds no preparation memory (§3),
        # so an R store must start from an empty seed; a non-empty seed would
        # silently give R preparation material it is not allowed to hold.
        if arm == 'R' and m0.items:
            raise ValueError('R arm must start from an empty seed (no preparation memory)')
        self._run_id, self._arm, self._repeat = run_id, arm, repeat
        self.path = Path(path).absolute()
        modules = ('e01_v2_m0_memory.py', 'e01_v2_design.py')
        self._header = {'schema': 'e01-m0-memory-merge-offline-v1',
                        'run_id': run_id, 'arm': arm, 'repeat': repeat,
                        'seed_sha256': m0.sha256(),
                        'implementation': {n: hashlib.sha256(
                            Path(__file__).with_name(n).read_bytes()).hexdigest()
                            for n in modules}}
        self._header_bytes = canonical(self._header)
        if create:
            with self.path.open('xb'):
                pass
        self._db = sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True,
                                   isolation_level=None, timeout=5)
        self._db.execute('PRAGMA synchronous=FULL')
        try:
            if create:
                self._db.execute('PRAGMA journal_mode=DELETE')
                self._db.execute('BEGIN IMMEDIATE')
                self._db.execute('CREATE TABLE header (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)')
                self._db.execute('CREATE TABLE items (item_id TEXT PRIMARY KEY, payload BLOB NOT NULL, phase TEXT NOT NULL)')
                self._db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, payload BLOB NOT NULL, sha256 TEXT NOT NULL)')
                self._db.execute('INSERT INTO header VALUES (1, ?)', (self._header_bytes,))
                for lesson in m0.items:
                    self._db.execute('INSERT INTO items VALUES (?,?,?)',
                                     (lesson.item_id, canonical(asdict(lesson)), lesson.source_phase))
                self._db.execute('COMMIT')
            rows = self._db.execute('SELECT id, payload FROM header').fetchall()
            if rows != [(1, self._header_bytes)]:
                raise IdentityMismatch('merge store identity changed (run_id/arm/repeat/m0)')
            self._items = {}
            for item_id, payload, phase in self._db.execute('SELECT item_id, payload, phase FROM items'):
                lesson = Lesson(**json.loads(payload))
                self._items[item_id] = lesson
        except BaseException:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            self._db.close()
            raise

    def close(self):
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def memory(self) -> Memory:
        return Memory(tuple(self._items.values()))

    def merge(self, lessons: tuple[Lesson, ...]):
        if type(lessons) is not tuple or any(type(x) is not Lesson for x in lessons):
            raise ValueError('Lesson tuple required')
        # R10 (Codex 2026-10-01 13:15): R holds no memory and F is a frozen M0;
        # neither admits online updates. Reject the call at the component layer
        # rather than silently accepting a merge into a frozen arm.
        if self._arm in ('R', 'F'):
            raise FrozenArmViolation(
                'R/F arms forbid online updates: R holds no memory and F is a frozen M0 (§18/§19)')
        # R9 fix (Codex 2026-10-01 13:15): never mutate the in-memory cache
        # before the transaction commits. A later lesson that raises (a non-online
        # phase, or a conflicting content) must not leave a ghost entry in
        # self._items while the database rolls back, which previously let a
        # failed batch drop a lesson that a later idempotent replay then skipped.
        # Validate + insert inside one transaction; sync the cache only after
        # COMMIT succeeds.
        self._db.execute('BEGIN IMMEDIATE')
        inserted = []
        try:
            for lesson in lessons:
                if lesson.source_phase != 'online':
                    raise ValueError('only online-phase published lessons may merge')
                row = self._db.execute(
                    'SELECT payload FROM items WHERE item_id=?', (lesson.item_id,)).fetchone()
                if row is not None:
                    stored = Lesson(**json.loads(row[0]))
                    if stored != lesson:
                        raise MergeConflict('published lesson id already stored with different content')
                    continue  # idempotent same replay, no DB write
                self._db.execute('INSERT INTO items VALUES (?,?,?)',
                                 (lesson.item_id, canonical(asdict(lesson)), lesson.source_phase))
                inserted.append(lesson)
            self._db.execute('COMMIT')
        except BaseException:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            raise
        else:
            for lesson in inserted:
                self._items[lesson.item_id] = lesson

    def summary(self):
        online = sum(1 for x in self._items.values() if x.source_phase == 'online')
        return {'run_id': self._run_id, 'arm': self._arm, 'repeat': self._repeat,
                'total_items': len(self._items), 'online_items': online,
                'memory_sha256': self.memory().sha256()}


def run_m0_memory_demo(root, run_id):
    """Synthetic M0 build + clone + merge; no model, no OS isolation.

    Shows: deterministic M0 build, byte-identical F/U clones, seed + idempotent
    replay + conflicting-merge rejection, and identity-binding enforcement on
    reopen. Over-reservation style refusals are covered by the contract test
    suite; this demo returns the assembled evidence.
    """
    from .e01_v2_design import Lesson
    root = Path(root)
    identifier(run_id)
    work = root / run_id
    work.mkdir(parents=True, exist_ok=False)

    prep = (Lesson('p1', 'Empty input returns default.', 'prep0', 'prepare'),
            Lesson('p2', 'Off-by-one: use len-1.', 'prep1', 'prepare'))
    builder = M0Builder(prep)
    # Determinism: a second build from the same set is identical.
    builder2 = M0Builder(prep)
    m0_deterministic = builder.m0.sha256() == builder2.m0.sha256()
    # Byte-for-byte clones.
    f_clone = builder.clone_for_arm('F')
    u_clone = builder.clone_for_arm('U')
    clones_identical = (f_clone.sha256() == builder.m0.sha256()
                        and u_clone.sha256() == builder.m0.sha256())
    r_seed = builder.clone_for_arm('R')

    # U arm merge store seeded with M0 clone.
    u_store = MemoryMergeStore(work / 'u-memory.sqlite', run_id, 'U', 0, u_clone, create=True)
    before = u_store.memory().sha256()
    # First published lesson merges.
    u_store.merge((Lesson('u1', 'Cache the parser between tasks.', 't0', 'online'),))
    after_first = u_store.memory().sha256()
    # Idempotent replay of the same lesson is a no-op (no MergeConflict).
    u_store.merge((Lesson('u1', 'Cache the parser between tasks.', 't0', 'online'),))
    after_replay = u_store.memory().sha256()
    # A conflicting lesson with the same id but different content is rejected.
    conflict_rejected = False
    try:
        u_store.merge((Lesson('u1', 'DIFFERENT text for u1.', 't0', 'online'),))
    except MergeConflict:
        conflict_rejected = True
    u_store.close()

    # Reopen: identity holds, lesson persists, memory hash unchanged.
    u_store2 = MemoryMergeStore(work / 'u-memory.sqlite', run_id, 'U', 0, u_clone)
    reopen_persisted = u_store2.memory().sha256() == after_replay
    u_store2.close()

    # Identity mismatch: a store opened under a different run_id is rejected.
    mismatch_rejected = False
    try:
        MemoryMergeStore(work / 'u-memory.sqlite', 'other-run', 'U', 0, u_clone)
    except IdentityMismatch:
        mismatch_rejected = True

    return {'identity': 'synthetic offline M0 prep + merge; no model ability or OS isolation',
            'api_calls': 0,
            'm0_sha256': builder.m0.sha256(),
            'm0_deterministic_same_seed': m0_deterministic,
            'f_u_clones_byte_identical_to_m0': clones_identical,
            'r_seed_empty': r_seed.items == (),
            'u_merge_before_sha256': before,
            'u_merge_after_first_sha256': after_first,
            'u_merge_changed_after_first': before != after_first,
            'u_replay_idempotent': after_first == after_replay,
            'u_conflicting_merge_rejected': conflict_rejected,
            'u_reopen_persisted': reopen_persisted,
            'identity_mismatch_rejected': mismatch_rejected}
