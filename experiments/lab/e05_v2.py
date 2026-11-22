"""E05 v2 local mechanisms. No model calls and no capability claims."""
from __future__ import annotations

import ast
import hashlib
from pathlib import PurePosixPath

from .e05_arms import Skill, validate_contract
from .taskset_spec import FAMILIES

VERSION = "e05-v2-20260929"
ALLOWED_SPLITS = {"train", "select-valid", "regression"}


def source_files(task, trace):
    """Only task-owned mutable Python files; never publish protected tests."""
    allowed = {p for p in task.files if p.endswith('.py')
               and p not in task.protected
               and not PurePosixPath(p).name.startswith('test')
               and PurePosixPath(p).name != 'conftest.py'}
    recovered = dict(task.files)
    for step in trace.steps:
        # A rejected write still appears as tool_result in the legacy trace.
        if step.kind=='tool_result' and step.detail.get('tool')=='write_file' and step.content.startswith('已写入 '):
            args=step.detail.get('args',{})
            if args.get('path') in allowed and isinstance(args.get('content'),str):
                recovered[args['path']]=args['content']
    return {p: recovered[p] for p in sorted(allowed)}


def admit(task, trace, entry):
    """A passing origin is necessary, never a guarantee for later tasks."""
    if trace.verdict is not True:
        return None, "origin_failed"
    files = source_files(task, trace)
    if not files or sum(map(len, files.values())) > 12000:
        return None, "empty_or_oversize_source"
    signature = None
    try:
        for code in files.values():
            for node in ast.parse(code).body:
                if getattr(node, 'name', None) != entry:
                    continue
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    signature = f"{entry}({ast.unparse(node.args)})"
                elif isinstance(node, ast.ClassDef):
                    # Constructor signature is not the complete class interface.
                    init = next((n for n in node.body if isinstance(n, ast.FunctionDef)
                                 and n.name == '__init__'), None)
                    signature = f"{entry}({ast.unparse(init.args) if init else ''})"
    except SyntaxError:
        return None, "invalid_python"
    if signature is None:
        return None, "entry_not_found"
    body = '\n'.join(f'# {p}\n{code}' for p, code in files.items())
    skill = Skill(name=f'{task.family}-{entry}', signature=signature,
                  requires='python>=3.8',
                  applies_when=FAMILIES.get(task.family, {}).get('failure_mode', 'same task family'),
                  does_not_apply_when='Not verified for a different input contract or interface.',
                  code=body, verified_on=task.task_id,
                  fail_conditions='Only the origin task was verified; adaptation remains necessary.')
    ok, reasons = validate_contract(skill)
    return (skill, 'admitted') if ok else (None, ';'.join(reasons))


def eligible_sequences(tasks, families, grid):
    if not grid or any(k not in (0, 1, 2, 4) for k in grid) or len(set(grid)) != len(grid):
        raise ValueError('grid must be a nonempty unique subset of 0,1,2,4')
    groups = {}
    for task in tasks:
        if task.split in ALLOWED_SPLITS and task.family in families:
            groups.setdefault(task.family, []).append(task)
    if set(groups) != set(families):
        raise ValueError('unknown or empty family')
    for family, seq in groups.items():
        seq.sort(key=lambda t: t.task_id)
        if len(seq) < max(grid) + 1:
            raise ValueError(f'insufficient eligible tasks: {family}')
    return groups


def observed_costs(ledgers, grid, arm='static_skill'):
    """Ledgers already aggregate all attempts. Compare actual like-for-like totals."""
    rows = []
    for k in sorted(grid):
        a, b = ledgers.get(f'{arm}|k{k}'), ledgers.get(f'replan|k{k}')
        if a is None or b is None:
            rows.append({'k': k, 'status': 'missing_pair'})
            continue
        if a['episodes'] != b['episodes']:
            raise ValueError('unequal primary episode denominators')
        ca = a['build_calls'] + a['reuse_calls'] + a.get('repair_calls', 0)
        cb = b['build_calls'] + b['reuse_calls'] + b.get('repair_calls', 0)
        if ca != a['calls'] or cb != b['calls']:
            raise ValueError('call ledger does not reconcile')
        rows.append({'k': k, 'status': 'observed', 'primary_episodes': a['episodes'],
                     'skill_calls': ca, 'replan_calls': cb, 'call_difference': ca-cb,
                     'skill_tokens': a['prompt_tokens']+a['completion_tokens'],
                     'replan_tokens': b['prompt_tokens']+b['completion_tokens']})
    crossings = [r['k'] for r in rows if r['status']=='observed'
                 and r['k']>0 and r['call_difference']<=0]
    return {'rows': rows, 'first_observed_call_crossing': min(crossings) if crossings else None,
            'grid_complete': all(r['status']=='observed' for r in rows),
            'interpretation': 'descriptive grid crossing only; no interpolation, currency or P4 verdict'}


def digest(value):
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
