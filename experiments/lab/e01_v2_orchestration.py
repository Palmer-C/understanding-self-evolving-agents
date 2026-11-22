"""Offline global run identity, atomic global budget authority, persistent cursor.

These three pieces answer the next integration need stated at the end of
E01-v2-draft §16: one run/task/arm/repeat identity, a task-sequence check, an
atomic global budget reservation, and a persistent sequence cursor. They are
offline contracts only. SQLite transactions guard the authoritative state;
hashes detect accidental change, not hostile rewriting. No backend, no paid
execution, no candidate execution, and no OS isolation are present here.

The global budget authority is the single source of truth for the whole-run
caps and the remaining pool. A per-extraction journal must obtain a Grant from
this authority; it cannot carry its own independent full caps, so creating a new
journal never resets the budget. Reopening reloads the remaining pool from disk.

CONTRACT GUARANTEES (enforced by the tests in test_e01_v2_orchestration.py):

- Atomic reservation: the remaining-pool check and decrement happen inside one
  SQLite transaction and read the authoritative on-disk value, so two handles
  opened against the same file cannot over-issue the pool (R5). A stale in-memory
  cache of the previous balance cannot authorize a second draw. ``remaining()``
  also reads the committed on-disk value, so a handle that failed a reserve (or
  never drew) never reports a stale whole-run balance (R5 read-consistency).
- Immovable settlement: a grant is settled exactly once. A conflicting replay
  (a smaller or different used amount after commit) is rejected; an identical
  replay is idempotent. Used resources can never be retroactively erased (R6).
- Identity binding: the budget authority is bound to the full RunIdentity
  (run_id + manifest commitment + arms + repeats). A different manifest under
  the same run_id, or a unit that is not part of this run, is rejected. The
  reservation key is the canonical unit identity (arm, repeat, task_id), so a
  custom grant_id cannot bypass the same-unit uniqueness check (R7).
- Legal cursor progression: a unit advances only through its arm-specific ordered
  steps (begin -> solve -> [update] -> finish -> publish); you cannot jump to a
  later step or a later unit without finishing the earlier ones (R7). The legality
  decision reads the committed position from disk inside the transaction, so the
  first advance must land on unit 0 (no jumping to a later unit), units must be
  consecutive (no skipping), and a second handle on the same file cannot roll the
  cursor back or skip ahead using a stale cache (R7 multi-handle consistency).

INTEGRATION GAP (not claimed here): these contracts are not yet invoked by the
run_e01_v2 call chain or consumed by AdmissionJournal. Wiring them into the real
runner is a separate offline step that follows this component work.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import sqlite3
import hashlib
from .e01_v2_design import canonical, digest, identifier, integer
from .e01_v2_resources import Limits
from .e01_v2_manifest import ExperimentManifest


class BudgetStop(RuntimeError): pass
class IdentityConflict(RuntimeError): pass


ARMS = ('R', 'F', 'U', 'L')

# Per-arm ordered step machine for the sequence cursor. R has no update step.
ARM_STEPS = {
    'R': ('begin', 'solve', 'finish', 'publish'),
    'F': ('begin', 'solve', 'update', 'finish', 'publish'),
    'U': ('begin', 'solve', 'update', 'finish', 'publish'),
    'L': ('begin', 'solve', 'update', 'finish', 'publish'),
}


@dataclass(frozen=True)
class Unit:
    arm: str
    repeat: int
    task_index: int
    task_id: str


@dataclass(frozen=True)
class RunIdentity:
    """Binds run_id to manifest/arms/repeats; enumerates and validates order.

    Reopening a cursor or budget authority bound to a different manifest
    (different online order, arms, or repeats) is rejected by the header hash,
    so a persisted artifact cannot be silently repointed at another experiment.
    """
    run_id: str
    manifest: ExperimentManifest
    arms: tuple[str, ...]
    repeats: int

    def __post_init__(self):
        identifier(self.run_id)
        if type(self.manifest) is not ExperimentManifest:
            raise ValueError('typed manifest required')
        if type(self.arms) is not tuple or not self.arms or len({*self.arms}) != len(self.arms):
            raise ValueError('unique nonempty arms required')
        for arm in self.arms:
            if arm not in ARMS:
                raise ValueError('unknown arm in run plan')
        integer(self.repeats, 'repeats', 1)

    def units(self):
        out = []
        for arm in self.arms:
            for repeat in range(self.repeats):
                for ti, task in enumerate(self.manifest.online):
                    out.append(Unit(arm, repeat, ti, task))
        return tuple(out)

    def index_of(self, arm, repeat, task_id):
        for i, u in enumerate(self.units()):
            if (u.arm, u.repeat, u.task_id) == (arm, repeat, task_id):
                return i
        raise ValueError('unit not in run plan')

    def is_unit(self, arm, repeat, task_id):
        try:
            self.index_of(arm, repeat, task_id)
            return True
        except ValueError:
            return False


class GlobalBudgetAuthority:
    """Authoritative whole-run budget; per-extraction journals draw from it.

    The total caps and the remaining pool live in one SQLite file. A new
    per-extraction journal must obtain a Grant here; it cannot carry independent
    full caps, so creating a new journal never resets the budget. Reopening
    reloads the remaining pool from disk.

    The authority is bound to the full RunIdentity (run_id + manifest commitment
    + arms + repeats). A reservation is keyed on the canonical unit identity
    (arm, repeat, task_id), so a non-canonical grant_id cannot bypass the
    same-unit uniqueness check. The remaining-pool check and decrement are
    performed inside one transaction against the on-disk value, so two handles
    against the same file cannot over-issue the pool (R5).
    """

    def __init__(self, path, identity: RunIdentity, limits: Limits, *, create=False):
        if type(identity) is not RunIdentity:
            raise ValueError('RunIdentity required')
        if type(limits) is not Limits:
            raise ValueError('Limits required')
        identifier(identity.run_id)
        self._identity = identity
        self._total = limits
        self.path = Path(path).absolute()
        modules = ('e01_v2_orchestration.py', 'e01_v2_resources.py',
                   'e01_v2_design.py', 'e01_v2_manifest.py')
        self._header = {'schema': 'e01-global-budget-authority-offline-v1',
                        'run_id': identity.run_id,
                        'manifest_sha256': identity.manifest.commitment()['sha256'],
                        'arms': identity.arms,
                        'repeats': identity.repeats,
                        'online_tasks': identity.manifest.online,
                        'limits': asdict(limits),
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
                self._db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), remaining BLOB NOT NULL)')
                self._db.execute('CREATE TABLE reservations (grant_id TEXT PRIMARY KEY, arm TEXT NOT NULL, '
                                 'rep INTEGER NOT NULL, task_id TEXT NOT NULL, calls INTEGER NOT NULL, '
                                 'attempts INTEGER NOT NULL, tests INTEGER NOT NULL, used_calls INTEGER NOT NULL DEFAULT 0, '
                                 'used_attempts INTEGER NOT NULL DEFAULT 0, used_tests INTEGER NOT NULL DEFAULT 0, '
                                 'committed INTEGER NOT NULL DEFAULT 0)')
                self._db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, payload BLOB NOT NULL, sha256 TEXT NOT NULL)')
                self._db.execute('INSERT INTO header VALUES (1, ?)', (self._header_bytes,))
                self._db.execute('INSERT INTO state VALUES (1, ?)', (canonical(asdict(limits)),))
                self._db.execute('COMMIT')
            rows = self._db.execute('SELECT id, payload FROM header').fetchall()
            if rows != [(1, self._header_bytes)]:
                raise IdentityConflict('budget authority identity/limits changed')
            remaining = Limits(**json.loads(self._db.execute(
                'SELECT remaining FROM state').fetchone()[0]))
            if (remaining.calls > limits.calls or remaining.attempts > limits.attempts
                    or remaining.tests > limits.tests):
                raise ValueError('remaining exceeds total: tampering or corruption')
            self._remaining = remaining
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

    def remaining(self):
        # R5 read-consistency fix (Codex 2026-10-01 13:15): read the
        # authoritative on-disk value rather than the in-memory cache, so a
        # handle that failed a reserve (or never drew) never reports a stale
        # balance such as its initial 3/3/0 when the pool is already drained to
        # 1/1/0. Any handle sees the same committed remaining.
        return Limits(**json.loads(self._db.execute(
            'SELECT remaining FROM state').fetchone()[0]))

    def reserve(self, arm, repeat, task_id, sub: Limits, *, grant_id=None):
        if arm not in ARMS:
            raise ValueError('unknown arm')
        if not self._identity.is_unit(arm, repeat, task_id):
            raise IdentityConflict('unit is not part of this run identity')
        identifier(task_id)
        integer(repeat, 'repeat')
        if type(sub) is not Limits:
            raise ValueError('sub Limits required')
        canonical_id = identifier(f'{arm}-r{repeat}-{task_id}-budget')
        if grant_id is None:
            grant_id = canonical_id
        elif grant_id != canonical_id:
            # A non-canonical grant_id would let a caller reserve the same unit
            # twice under different labels; reject it so uniqueness is enforced
            # on the canonical unit identity (R7).
            raise IdentityConflict('grant_id must equal the canonical unit identity')
        if self._db.execute('SELECT 1 FROM reservations WHERE arm=? AND rep=? AND task_id=?',
                            (arm, repeat, task_id)).fetchone() is not None:
            raise IdentityConflict('budget already reserved for this unit')
        # R5 fix: the balance check and decrement happen inside one transaction
        # against the authoritative on-disk value, so a stale handle cache
        # cannot authorize a second draw beyond the pool.
        self._db.execute('BEGIN IMMEDIATE')
        try:
            current = Limits(**json.loads(self._db.execute(
                'SELECT remaining FROM state').fetchone()[0]))
            if (current.calls < sub.calls or current.attempts < sub.attempts
                    or current.tests < sub.tests):
                raise BudgetStop('global remaining insufficient for reservation')
            new = Limits(current.calls - sub.calls,
                         current.attempts - sub.attempts,
                         current.tests - sub.tests)
            self._remaining = new
            self._db.execute('UPDATE state SET remaining=?',
                             (canonical(asdict(new)),))
            self._db.execute('INSERT INTO reservations VALUES (?,?,?,?,?,?,?,0,0,0,0)',
                             (grant_id, arm, repeat, task_id, sub.calls,
                              sub.attempts, sub.tests))
            self._db.execute('COMMIT')
            return grant_id
        except BaseException:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            raise

    def reconcile(self, grant_id, used: Limits):
        identifier(grant_id)
        if type(used) is not Limits:
            raise ValueError('used Limits required')
        # R6 fix: settlement is immutable. The read of the committed flag and the
        # write happen inside one transaction. A conflicting replay (a smaller or
        # different used amount after the first commit) is rejected; an identical
        # replay is idempotent. Used resources can never be retroactively erased.
        self._db.execute('BEGIN IMMEDIATE')
        try:
            row = self._db.execute(
                'SELECT calls,attempts,tests,used_calls,used_attempts,used_tests,committed '
                'FROM reservations WHERE grant_id=?', (grant_id,)).fetchone()
            if row is None:
                raise IdentityConflict('unknown grant')
            if used.calls > row[0] or used.attempts > row[1] or used.tests > row[2]:
                raise BudgetStop('used exceeds granted reservation')
            if row[6]:  # already committed
                prev = Limits(row[3], row[4], row[5])
                if used != prev:
                    raise IdentityConflict('settlement already committed; conflicting replay rejected')
                self._db.execute('COMMIT')  # idempotent same replay, no-op
                return
            self._db.execute(
                'UPDATE reservations SET used_calls=?,used_attempts=?,used_tests=?,committed=1 '
                'WHERE grant_id=?', (used.calls, used.attempts, used.tests, grant_id))
            self._db.execute('COMMIT')
        except BaseException:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            raise

    def committed_units(self):
        """Return the set of (arm, repeat, task_id) whose grant is committed.

        Used by the offline assembly to resume a run: a unit whose grant is
        already committed has fully drawn, run, and reconciled, so reopening the
        run skips it instead of re-drawing the budget or re-merging (R11.2).
        """
        rows = self._db.execute(
            'SELECT arm,rep,task_id FROM reservations WHERE committed=1').fetchall()
        return {(r[0], r[1], r[2]) for r in rows}

    def summary(self):
        remaining = Limits(**json.loads(self._db.execute(
            'SELECT remaining FROM state').fetchone()[0]))
        rows = self._db.execute(
            'SELECT grant_id,arm,rep,task_id,calls,attempts,tests,used_calls,used_attempts,used_tests '
            'FROM reservations ORDER BY grant_id').fetchall()
        reserved_calls = sum(r[4] for r in rows)
        reserved_attempts = sum(r[5] for r in rows)
        reserved_tests = sum(r[6] for r in rows)
        used_calls = sum(r[7] for r in rows)
        used_attempts = sum(r[8] for r in rows)
        used_tests = sum(r[9] for r in rows)
        return {'run_id': self._identity.run_id,
                'total': asdict(self._total),
                'remaining': asdict(remaining),
                'reserved': {'calls': reserved_calls, 'attempts': reserved_attempts, 'tests': reserved_tests},
                'used': {'calls': used_calls, 'attempts': used_attempts, 'tests': used_tests},
                'grants': len(rows),
                'exhausted': (remaining.calls == 0 and remaining.attempts == 0
                              and remaining.tests == 0)}


class SequenceCursor:
    """Persistent run position; resumes instead of restarting.

    Records the last committed (unit_index, step). Reopening with a different
    run_id/manifest is rejected by the header hash, so the cursor cannot be
    repointed at a different experiment.

    Progression is legal: a unit advances only through its arm-specific ordered
    steps; you cannot jump to a later step or a later unit without finishing the
    earlier ones (R7).
    """
    STEPS = ('begin', 'solve', 'update', 'finish', 'publish')

    def __init__(self, path, identity: RunIdentity, *, create=False):
        if type(identity) is not RunIdentity:
            raise ValueError('typed identity required')
        self._identity = identity
        self.path = Path(path).absolute()
        modules = ('e01_v2_orchestration.py', 'e01_v2_design.py', 'e01_v2_manifest.py')
        self._header = {'schema': 'e01-sequence-cursor-offline-v1',
                        'run_id': identity.run_id, 'arms': identity.arms,
                        'repeats': identity.repeats,
                        'online_tasks': identity.manifest.online,
                        'manifest_sha256': identity.manifest.commitment()['sha256'],
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
                self._db.execute('CREATE TABLE position (id INTEGER PRIMARY KEY CHECK(id=1), unit_index INTEGER NOT NULL, step TEXT NOT NULL)')
                self._db.execute('CREATE TABLE events (seq INTEGER PRIMARY KEY, payload BLOB NOT NULL, sha256 TEXT NOT NULL)')
                self._db.execute('INSERT INTO header VALUES (1, ?)', (self._header_bytes,))
                self._db.execute('INSERT INTO position VALUES (1, ?, ?)', (-1, 'none'))
                self._db.execute('COMMIT')
            rows = self._db.execute('SELECT id, payload FROM header').fetchall()
            if rows != [(1, self._header_bytes)]:
                raise IdentityConflict('cursor identity changed (run_id/arms/tasks/manifest)')
            pos = self._db.execute('SELECT unit_index, step FROM position').fetchone()
            self._unit_index, self._step = pos
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

    def advance(self, arm, repeat, task_id, step):
        if arm not in ARMS:
            raise ValueError('unknown arm')
        if step not in ARM_STEPS.get(arm, ()):
            raise ValueError('unknown step for arm')
        index = self._identity.index_of(arm, repeat, task_id)
        seq = ARM_STEPS[arm]
        # R7 remaining fix (Codex 2026-10-01 13:15): the legality decision reads
        # the latest committed position from disk INSIDE the transaction, not a
        # stale in-memory cache. Two handles on the same file cannot desync: a
        # handle that opened earlier (holding an old cursor) must honor the
        # position another handle already committed, so a stale handle can
        # neither roll the cursor back nor skip ahead.
        self._db.execute('BEGIN IMMEDIATE')
        try:
            cur_idx, cur_step = self._db.execute(
                'SELECT unit_index, step FROM position').fetchone()
            if (index, step) == (cur_idx, cur_step):
                self._db.execute('COMMIT')
                return  # idempotent replay of the committed step, no-op
            if index == cur_idx:
                # Same unit: must advance exactly one ordered step forward.
                if cur_step == 'none':
                    expected = seq[0]
                else:
                    pos = seq.index(cur_step)
                    expected = seq[pos + 1] if pos + 1 < len(seq) else None
                if step != expected:
                    raise ValueError('illegal in-unit step transition (expected %r)' % (expected,))
            elif index == cur_idx + 1:
                # Next unit: the previous one must be finished/published, and the
                # new unit must begin at its first step. With the fresh cursor at
                # (-1, 'none'), cur_idx + 1 == 0, so the very first advance must
                # land on unit 0; jumping straight to a later unit is rejected.
                if cur_idx >= 0 and cur_step not in ('finish', 'publish'):
                    raise ValueError('previous unit not finished before advancing')
                if step != seq[0]:
                    raise ValueError('new unit must start at its first step')
            else:
                # Backward move, or skipping one or more units: not allowed.
                raise ValueError('illegal unit jump (must be consecutive and forward)')
            self._db.execute('UPDATE position SET unit_index=?, step=?', (index, step))
            self._db.execute('COMMIT')
            self._unit_index, self._step = index, step
        except BaseException:
            if self._db.in_transaction:
                self._db.execute('ROLLBACK')
            raise

    def position(self):
        # R7 multi-handle consistency: read the committed position from disk so
        # a second handle observes progress the first handle already committed.
        cur_idx, cur_step = self._db.execute(
            'SELECT unit_index, step FROM position').fetchone()
        self._unit_index, self._step = cur_idx, cur_step
        return (cur_idx, cur_step)

    def current_unit(self):
        idx, _ = self.position()
        if idx < 0:
            return None
        return self._identity.units()[idx]


def fixture_manifest():
    """Synthetic manifest fixture; not E01 capability or sealed data."""
    from .e01_v2_manifest import TaskSpec
    def make(tid, family):
        return TaskSpec(task_id=tid, family=family, prompt=f'prompt {tid}',
                        public_files=(('main.py', 'x'),), final_files=(('final.out', 'z'),),
                        writable=('main.py',))
    tasks = (make('prep0', 'famA'), make('t0', 'famB'), make('t1', 'famB'), make('tr0', 'famC'))
    return ExperimentManifest(tasks=tasks, prepare=('prep0',),
                              online=('t0', 't1'), transfer=('tr0',), repeats=2)


def run_orchestration_demo(root, run_id):
    """Synthetic wiring: authority + cursor drive a full unit sequence.

    Per task a sub-budget is drawn from the global authority (never an
    independent cap), the cursor is advanced through each step, and the grant is
    reconciled. No model, no candidate execution, no real memory merge. The
    over-reservation and double-reserve refusals are covered by the contract
    test suite (AuthorityChecks); this demo shows the full reserve+reconcile,
    reopen-not-reset, and cursor-resume properties.
    """
    root = Path(root)
    identifier(run_id)
    work = root / run_id
    work.mkdir(parents=True, exist_ok=False)
    identity = RunIdentity(run_id, fixture_manifest(), arms=('R', 'F', 'U'), repeats=2)
    units = identity.units()
    total = Limits(len(units) * 3, len(units) * 4, len(units) * 3)
    authority = GlobalBudgetAuthority(work / 'budget.sqlite', identity, total, create=True)
    cursor = SequenceCursor(work / 'cursor.sqlite', identity, create=True)
    grants, reconciles, steps_seen = [], [], []
    try:
        for u in units:
            grants.append(authority.reserve(u.arm, u.repeat, u.task_id, Limits(3, 4, 3)))
            for step in ('begin', 'solve', 'update', 'finish'):
                if step == 'update' and u.arm == 'R':
                    continue  # R has no update permission
                cursor.advance(u.arm, u.repeat, u.task_id, step)
                steps_seen.append((u.arm, u.repeat, u.task_id, step))
            authority.reconcile(grants[-1], Limits(3, 4, 3))
            reconciles.append(grants[-1])
        # Reopen: budget and cursor resume, not reset.
        authority.close(); cursor.close()
        authority = GlobalBudgetAuthority(work / 'budget.sqlite', identity, total)
        cursor = SequenceCursor(work / 'cursor.sqlite', identity)
        resume = {'remaining_after_reopen': asdict(authority.remaining()),
                  'cursor_after_reopen': cursor.position(),
                  'cursor_unit': cursor.current_unit().task_id}
        return {'identity': 'synthetic offline orchestration; no model ability or OS isolation',
                'api_calls': 0, 'units': len(units),
                'total_budget': asdict(total),
                'grants_issued': len(grants), 'grants_reconciled': len(reconciles),
                'steps_recorded': len(steps_seen),
                'authority_summary': authority.summary(),
                'resume': resume,
                'over_reservation_refused': None}  # see AuthorityChecks (contract tests)
    finally:
        authority.close(); cursor.close()
