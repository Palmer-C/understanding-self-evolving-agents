"""Offline, hash-bound access to explicitly named historical summaries.

The manifest records input identity, not approval of disputed scientific facts.
Never resolve a missing run by silently choosing another path or latest run.
"""
from pathlib import Path
import hashlib
import json

RUN_IDS = ('E01-20260923T152230Z-90acda',
           'E02-20260924T153511Z-421eac',
           'E03-20260925T152453Z-254845')

def load_summary(root, run_id):
    root=Path(root)
    manifest=json.loads((root/'analysis/inputs.json').read_text(encoding='utf-8-sig'))
    item=manifest['summaries'][run_id]
    path=root/item['path']
    if not path.is_file():
        raise FileNotFoundError(f'Required archived input missing: {path}')
    raw=path.read_bytes()
    actual=hashlib.sha256(raw).hexdigest()
    if actual != item['sha256']:
        raise ValueError(f'Archived input identity mismatch: {path}')
    data=json.loads(raw.decode('utf-8-sig'))
    if data['config']['run_id'] != run_id:
        raise ValueError(f'Run identity mismatch: {path}')
    return data

def required_summaries(root):
    # Validate every required run before producing any totals.
    return {run_id:load_summary(root,run_id) for run_id in RUN_IDS}
