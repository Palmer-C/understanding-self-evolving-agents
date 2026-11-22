"""Offline end-to-end assembly of E01 v2 components; contracts only.

Wires the already-built offline pieces into ONE coherent call chain so that the
global budget, the task/arm identity, the admission receipt, and the persistent
memory are co-constrained by the same ``RunIdentity``:

    for each canonical unit (arm, repeat, task_id):
        if arm == 'U':
            grant = GlobalBudgetAuthority.reserve(unit)   # draws from whole-run pool
        SequenceCursor.advance(unit, step)               # ONE step per real event
        if arm == 'U':
            PublicEventStore window -> AdmissionJournal(reserve/issue/settle/
                candidate/review/publish) -> MemoryMergeStore.merge(published)

No model, no candidate execution, no OS isolation, and no real budget spend
happen here. The admission journal runs on a synthetic public window and a
``scripted_fixture`` response; its published lesson is the only memory that may
merge. R/F arms are asserted frozen (no online merge). The run identity binds
the budget authority, the cursor, and every memory merge store, so a persisted
artifact cannot be repointed at another experiment or a regenerated M0.

R11 fixes (Codex 2026-10-01 19:15 inspection):

- R11.1 (state after persistence): the cursor advances only AFTER each real
  persistence event (reserve -> begin; candidate -> solve; review -> update;
  publish -> finish; merge -> publish). A crash mid-unit therefore leaves the
  cursor at the last genuinely completed step, never prematurely at 'publish'.
  The admission journal is also closed reliably via try/finally.
- R11.3 (publish vs merged, honestly scoped): the admission journal is a SINGLE
  admission transaction bound to M0, so its ``initial`` must be preparation-only
  (``m0.clone_for_arm('U')``); the published snapshot is M0 + this admission's
  lessons. The merge store is the CUMULATIVE arm memory (M0 + all merged
  lessons). Therefore the published snapshot equals the merged store ONLY for
  the first admission per (arm, repeat); later admissions' published snapshots
  are single-admission views and deliberately differ from the cumulative store.
  We do NOT claim "published lesson memory equals merged store memory" in
  general (Codex 2026-10-01 19:15). The verified invariant is membership: each
  admission's published online lesson lands in the bound cumulative store.
- R11.2 (reopen resumes, does not reset): reopening the same ``run_id`` reloads
  the committed state and skips already-committed units; the budget is NOT reset
  and lessons are NOT re-merged. The claim "reopening resumes execution from an
  arbitrary mid-unit crash" is NOT made: resume keys off the per-grant commit /
  cursor publish. A unit that crashed mid-flight is not auto-recovered by the
  assembly loop (the per-journal chain replay is the separate crash-recovery
  mechanism).
- R11.4 (honest budget scope): only the U extraction draws from the global pool
  in this offline fixture; the per-extraction cap is bound to the reserved grant
  and reconciled with it. Preparation/solving/testing/retry phases are not
  modeled, so they are not under global budget control. This is reported, not
  hidden.
- R11.5 (token / wall-clock hard ceilings, draft §13-16 line 39/113/137): a
  ``HardCeiling`` (per-call output-token upper bound + whole-run wall-clock stop
  condition) is consulted on the synthetic U extraction. ``HardCeilingGuard``
  raises ``TokenCeilingExceeded`` when a call's output tokens exceed the per-call
  ceiling and ``WallClockExceeded`` when cumulative simulated elapsed seconds
  cross the stop condition, so the run must stop rather than exceed hard limits.
  This is the offline contract only: no real token metering or wall-clock timeout
  occurs in this fixture, and the prepare/solve/test/retry phases are not modeled
  (consistent with R11.4), so they are not under the ceiling either.
  R15 (Codex 2026-10-03 01:15): the guard is created ONCE at run scope in
  ``run_e01_v2_assembly`` and shared by every unit, so the cumulative wall-clock is
  preserved across units and the whole-run stop condition can actually halt the
  run; a fresh per-unit guard (the prior behavior) reset the accumulator after
  each unit and the stop never triggered across units.

This is the offline assembly layer Codex asked for after R5/R6/R7/R9/R10: wire
budget/identity/receipts/memory into one chain rather than leaving each
component uninvoked. It is NOT a live runner and performs no paid execution.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from .e01_v2_orchestration import (RunIdentity, GlobalBudgetAuthority,
    SequenceCursor, ARM_STEPS, fixture_manifest)
from .e01_v2_m0_memory import M0Builder, MemoryMergeStore
from .e01_v2_design import Lesson, Memory, identifier
from .e01_v2_public_memory import PublicEventStore
from .e01_v2_resources import Limits
from .e01_v2_admission_journal import AdmissionJournal
from .e01_v2_token_wallclock import (HardCeiling, HardCeilingGuard,
    TokenCeilingExceeded, WallClockExceeded)


# R11.5: simulated wall-clock charged per U unit in the offline fixture. No real
# clock is read; this is the per-unit elapsed-second value the guard accumulates
# against the whole-run stop condition. A real runner would supply the actual
# monotonic elapsed time of each unit.
ELAPSED_PER_UNIT_SECONDS = 1.0


def _synthetic_prep():
    """Synthetic preparation lessons; not E01 capability or sealed data."""
    return (Lesson('p1', 'Empty input returns the default value.', 'prep0', 'prepare'),
            Lesson('p2', 'Off-by-one: index with len-1, not len.', 'prep1', 'prepare'))


def process_unit(run_id, identity, authority, cursor, m0, work, unit,
                 public_stores, merge_stores, sub, *, guard=None):
    """Drive one canonical unit through the wired chain; return a record.

    guard: a ``HardCeilingGuard`` enforced on the synthetic U extraction (R11.5).
    Callers SHOULD pass a guard created ONCE at run scope so cumulative wall-clock
    is preserved across units (R15 fix). ``None`` falls back to a permissive
    per-unit guard for backward compatibility (does not preserve cross-unit
    accumulation, and is therefore NOT the whole-run contract).
    """
    if guard is None:
        guard = HardCeilingGuard(HardCeiling(tokens_per_call=10**9,
                                             total_wall_clock_seconds=10**9))
    arm, repeat, task_id = unit.arm, unit.repeat, unit.task_id
    grant = None
    if arm == 'U':
        grant = authority.reserve(arm, repeat, task_id, sub)
        cursor.advance(arm, repeat, task_id, 'begin')  # R11.1: after budget grant
    elif arm in ('R', 'F', 'L'):
        # No external effect in this offline fixture; advance the ordered markers
        # so the run position reflects the (offline) arm lifecycle. They never
        # gate on a real persistence event because none exists for these arms.
        for step in ARM_STEPS[arm]:
            cursor.advance(arm, repeat, task_id, step)
        return {'arm': arm, 'repeat': repeat, 'task_id': task_id,
                'budget_draw': False, 'merged_online': 0,
                'frozen': arm in ('R', 'F'), 'published_equals_merged': None}
    # U arm chain.
    key = (arm, repeat)
    mpath = work / f'mem-{arm}-r{repeat}.sqlite'
    if key not in merge_stores:
        seed = m0.clone_for_arm('U')
        if mpath.exists():
            merge_stores[key] = MemoryMergeStore(mpath, run_id, arm, repeat, seed)
        else:
            merge_stores[key] = MemoryMergeStore(mpath, run_id, arm, repeat, seed, create=True)
    store = merge_stores[key]
    # R11.3 (honest): the admission journal is a SINGLE admission transaction
    # bound to M0, so its initial memory must be preparation-only. The published
    # snapshot is M0 + this admission's lessons; the merge store is the CUMULATIVE
    # arm memory. They are equal only for the first admission per (arm, repeat);
    # later admissions' published snapshots are single-admission views and
    # deliberately differ from the cumulative store (see module docstring). We do
    # NOT claim "published lesson memory equals merged store memory" in general.
    initial = m0.clone_for_arm('U')
    if key not in public_stores:
        public_stores[key] = PublicEventStore(identity.manifest, phase='online')
    st = public_stores[key]
    st.begin(task_id)
    st.model_request(f'{task_id}-req', 'synthetic public request')
    st.model_response(f'{task_id}-resp', 'synthetic public response')
    window = st.close(task_id)
    jpath = work / f'journal-{arm}-r{repeat}-{task_id}.sqlite'
    session_id = f'{run_id}-{arm}-r{repeat}-{task_id}'
    journal = AdmissionJournal(jpath, session_id, st, window, window.event_ids,
                               initial, Limits(calls=1, attempts=1, tests=0),
                               create=not jpath.exists())
    try:
        journal.reserve(f'{task_id}-call')
        permit = journal.issue()
        resp = 'Cache the parser across tasks to avoid re-parsing.'
        # R11.5: the single synthetic call's output tokens must not exceed the
        # per-call ceiling; otherwise the call is rejected before settlement.
        guard.check_call_tokens(1)
        journal.settle(permit['attempt_id'], outcome='success',
                       usage={'prompt_tokens': 1, 'completion_tokens': 1},
                       response_id=f'{task_id}-resp', text=resp,
                       origin='scripted_fixture')
        journal.candidate(item_id=f'{task_id}-lesson', start=0, end=len(resp),
                          source_event_ids=window.event_ids)
        cursor.advance(arm, repeat, task_id, 'solve')  # R11.1: extraction produced
        journal.review(review_id=f'{task_id}-rev', accepted=True,
                       reviewer_kind='scripted_fixture', reviewer_id='reviewer-1',
                       rationale='synthetic offline fixture; no semantic verdict')
        cursor.advance(arm, repeat, task_id, 'update')  # R11.1: reviewer gate passed
        published = journal.publish()
        cursor.advance(arm, repeat, task_id, 'finish')  # R11.1: published
        online = tuple(x for x in published.items if x.source_phase == 'online')
        store.merge(online)
        cursor.advance(arm, repeat, task_id, 'publish')  # R11.1: merged into persistent memory
        # R11.5: charge the simulated per-unit wall-clock against the whole-run
        # stop condition; crossing it raises WallClockExceeded and stops the run.
        guard.accumulate_wall_clock(ELAPSED_PER_UNIT_SECONDS)
    finally:
        try:
            journal.close()
        except Exception:
            pass
    authority.reconcile(grant, sub)  # R6 idempotent if already committed
    # Verified invariant (R11.3): this admission's published online lesson lands
    # in the bound cumulative merge store. Full-snapshot equality with the store
    # holds only for the first admission per (arm, repeat); later admissions'
    # published snapshots are single-admission views and differ by design, so we
    # report both hashes transparently and DO NOT claim general equality.
    merged_contains_lesson = (len(online) == 1 and
        any(l == online[0] for l in store.memory().items))
    return {'arm': arm, 'repeat': repeat, 'task_id': task_id,
            'budget_draw': True, 'merged_online': len(online),
            'published_memory_sha256': published.sha256(),
            'merged_memory_sha256': store.memory().sha256(),
            'published_first_admission_equals_merged':
                (published.sha256() == store.memory().sha256()),
            'merged_contains_lesson': merged_contains_lesson,
            'frozen': False}


def run_e01_v2_assembly(root, run_id, *, arms=('R', 'F', 'U'), repeats=2,
                        ceiling=None):
    """Drive a full RunIdentity through the wired offline chain; no API calls.

    ceiling: optional ``HardCeiling`` (R11.5) enforced on the synthetic U
    extraction. A single guard is created ONCE at run scope and shared by every
    unit (R15 fix), so cumulative wall-clock is preserved across units and the
    whole-run stop condition can halt the run. ``None`` uses a permissive default
    (the offline demo and existing callers are unaffected).

    Returns a JSON-serializable summary. Reopening the same ``run_id`` reloads
    the committed state: units whose grant is already committed (U) or already
    fully advanced in the cursor (R/F/L) are skipped, so the budget is NOT reset
    and lessons are NOT re-merged (R11.2). This is NOT a claim that an arbitrary
    mid-unit crash is auto-recovered by the loop; resume keys off commit/publish.

    R11.3 (honest): the admission journal is a single-admission transaction bound
    to M0; its published snapshot equals the cumulative merged store ONLY for the
    first admission per (arm, repeat). Later admissions publish M0 + their own
    lesson while the store accumulates all prior lessons, so their published
    snapshot differs from the cumulative store by design. The verified invariant
    is membership (each published lesson lands in the bound store), not full
    snapshot equality.
    """
    root = Path(root)
    if ceiling is None:
        ceiling = HardCeiling(tokens_per_call=10**9, total_wall_clock_seconds=10**9)
    identifier(run_id)
    work = root / run_id
    work.mkdir(parents=True, exist_ok=True)  # R11.2: allow reopening (no FileExistsError)
    identity = RunIdentity(run_id, fixture_manifest(), arms=arms, repeats=repeats)
    units = identity.units()
    u_count = sum(1 for u in units if u.arm == 'U')
    sub = Limits(1, 1, 0)
    total = Limits(u_count, u_count, 0)
    budget_path = work / 'budget.sqlite'
    cursor_path = work / 'cursor.sqlite'
    authority = GlobalBudgetAuthority(budget_path, identity, total,
                                      create=not budget_path.exists())
    cursor = SequenceCursor(cursor_path, identity, create=not cursor_path.exists())
    committed = authority.committed_units()  # (arm,repeat,task_id) already done
    pos_idx, pos_step = cursor.position()
    m0 = M0Builder(_synthetic_prep())
    public_stores, merge_stores = {}, {}
    # R15 fix (Codex 2026-10-03 01:15): one guard at run scope, shared by every
    # unit, so cumulative wall-clock is preserved across units and the whole-run
    # stop condition can halt the run (previously a fresh guard per unit reset the
    # accumulator after each unit, so the stop never triggered across units).
    guard = HardCeilingGuard(ceiling)
    # Pre-open existing merge stores so a resumed run continues the cumulative memory.
    for u in units:
        if u.arm == 'U':
            key = (u.arm, u.repeat)
            if key not in merge_stores:
                mpath = work / f'mem-{u.arm}-r{u.repeat}.sqlite'
                if mpath.exists():
                    merge_stores[key] = MemoryMergeStore(
                        mpath, run_id, u.arm, u.repeat, m0.clone_for_arm('U'))
    records = []
    skipped = 0
    try:
        for u in units:
            if (u.arm, u.repeat, u.task_id) in committed:
                skipped += 1
                continue
            if u.arm in ('R', 'F', 'L'):
                idx = identity.index_of(u.arm, u.repeat, u.task_id)
                if idx < pos_idx or (idx == pos_idx and pos_step == 'publish'):
                    skipped += 1
                    continue
            records.append(process_unit(run_id, identity, authority, cursor,
                                        m0, work, u, public_stores, merge_stores,
                                        sub, guard=guard))
        # Count lessons actually present in the bound merge stores (cumulative,
        # so a resumed run still reports the full count rather than only this
        # run's merges).
        lessons_merged = sum(st.summary()['online_items'] for st in merge_stores.values())
    finally:
        authority.close()
        cursor.close()
        for st in merge_stores.values():
            st.close()
    # Reopen: budget and cursor resume, not reset.
    authority = GlobalBudgetAuthority(budget_path, identity, total)
    cursor = SequenceCursor(cursor_path, identity)
    summary = authority.summary()
    resume = {'remaining_after_reopen': asdict(authority.remaining()),
              'cursor_after_reopen': cursor.position()}
    authority.close()
    cursor.close()
    published_lesson_in_bound_store = all(
        (r.get('merged_contains_lesson') in (True, None)) for r in records)
    return {'identity': 'synthetic offline assembly; no model, no OS isolation, no paid execution',
            'budget_scope': 'only U extraction draws from the global pool; prepare/solve/test/retry not modeled',
            'token_wallclock_scope': 'R11.5/R15: a single HardCeilingGuard is created once at run scope and shared by all units, so cumulative wall-clock is preserved across units and the whole-run stop halts the run; no real token metering or wall-clock timeout occurs; prepare/solve/test/retry not modeled',
            'api_calls': 0, 'run_id': run_id, 'arms': list(arms), 'repeats': repeats,
            'units': len(units), 'u_units': u_count, 'total_budget': asdict(total),
            'authority_summary': summary, 'records': records,
            'units_skipped_on_resume': skipped,
            'lessons_merged': lessons_merged,
            'merged_lesson_in_bound_store': lessons_merged == u_count,
            'published_lesson_in_bound_store_for_all_u': published_lesson_in_bound_store,
            'resume': resume}


if __name__ == '__main__':
    import json
    import tempfile
    out = run_e01_v2_assembly(tempfile.mkdtemp(), 'demo-assembly')
    print(json.dumps(out, ensure_ascii=False, indent=2))
