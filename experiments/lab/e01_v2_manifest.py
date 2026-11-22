"""Offline task-identity contract, not a proof of semantic independence.

Content commitments exclude task/family labels so renaming an identical task
cannot make a new observation. Callers must supply complete historical hashes;
this module does not discover an unreported prior exposure or paraphrase leak.
No execution, backend, or actual confirmatory dataset is provided here.
"""
from __future__ import annotations
from dataclasses import dataclass
from .e01_v2_design import canonical, digest, identifier, integer, Memory
from .e01_v2_file_boundary import relative_name, partition_public_files
from .e01_v2_analysis import PlannedUnit


def sha256_text(value):
    if not isinstance(value, str) or len(value) != 64 or any(x not in '0123456789abcdef' for x in value):
        raise ValueError('lowercase SHA256 required')
    return value


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    family: str
    prompt: str
    public_files: tuple[tuple[str, str], ...]
    final_files: tuple[tuple[str, str], ...]
    writable: tuple[str, ...]

    def __post_init__(self):
        identifier(self.task_id); identifier(self.family)
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError('nonempty prompt required')
        for group in (self.public_files, self.final_files):
            if type(group) is not tuple or not group:
                raise ValueError('nonempty immutable public/final file tuples required')
            for item in group:
                if type(item) is not tuple or len(item) != 2 or not isinstance(item[1], str):
                    raise ValueError('immutable name/text pair required')
                if relative_name(item[0]) != item[0]:
                    raise ValueError('file names must already use canonical slash spelling')
        pairs = self.public_files + self.final_files
        folded = [x[0].casefold() for x in pairs]
        if len(set(folded)) != len(folded):
            raise ValueError('duplicate or overlapping file identity')
        if type(self.writable) is not tuple or len(set(self.writable)) != len(self.writable):
            raise ValueError('unique immutable writable names required')
        public_names = {x[0] for x in self.public_files}
        for name in self.writable:
            if relative_name(name) != name or name not in public_names:
                raise ValueError('writable file must match a canonical public file exactly')

    def content_sha256(self):
        # Canonical file order; IDs/family/phase are deliberately excluded.
        return digest({'prompt': self.prompt, 'public_files': sorted(self.public_files),
                       'final_files': sorted(self.final_files), 'writable': sorted(self.writable)})

    def public_payload(self):
        files = dict(self.public_files + self.final_files)
        return {'task_id': self.task_id, 'prompt': self.prompt,
                'files': partition_public_files(files,
                    public_names=[x[0] for x in self.public_files],
                    final_names=[x[0] for x in self.final_files]),
                'writable': list(self.writable)}


@dataclass(frozen=True)
class ExperimentManifest:
    tasks: tuple[TaskSpec, ...]
    prepare: tuple[str, ...]
    online: tuple[str, ...]
    transfer: tuple[str, ...]
    repeats: int
    historical_content_sha256: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.tasks) is not tuple or not self.tasks or any(type(x) is not TaskSpec for x in self.tasks):
            raise ValueError('immutable task tuple required')
        integer(self.repeats, 'repeats', 1)
        ids = [x.task_id for x in self.tasks]
        if len(set(ids)) != len(ids): raise ValueError('duplicate task identity')
        assigned = []
        for phase in (self.prepare, self.online, self.transfer):
            if type(phase) is not tuple or not phase:
                raise ValueError('all three phases must be nonempty immutable sequences')
            for name in phase: identifier(name)
            assigned.extend(phase)
        if len(set(assigned)) != len(assigned) or set(assigned) != set(ids):
            raise ValueError('each task must belong to exactly one phase')
        if type(self.historical_content_sha256) is not tuple:
            raise ValueError('immutable historical commitments required')
        for sha in self.historical_content_sha256: sha256_text(sha)
        hashes = [x.content_sha256() for x in self.tasks]
        if len(set(hashes)) != len(hashes): raise ValueError('renamed identical task content')
        if set(hashes) & set(self.historical_content_sha256):
            raise ValueError('declared previously exposed task reused')
        by_id = {x.task_id: x for x in self.tasks}
        source_families = {by_id[x].family for x in self.prepare + self.online}
        final_families = {by_id[x].family for x in self.transfer}
        if source_families & final_families:
            raise ValueError('cross-family transfer families overlap source phases')

    def validate_initial_memory(self, memory):
        if type(memory) is not Memory: raise ValueError('immutable initial memory required')
        if any(x.source_phase != 'prepare' or x.source_task not in self.prepare for x in memory.items):
            raise ValueError('initial memory source outside preparation manifest')
        return memory.sha256()

    def planned_units(self):
        by_id = {x.task_id: x for x in self.tasks}
        return tuple(PlannedUnit(phase, by_id[name].family, name, repeat)
            for phase in ('online', 'transfer') for name in getattr(self, phase)
            for repeat in range(self.repeats))

    def commitment(self):
        body = {'schema': 'e01-v2-manifest-draft-1',
                'tasks': [{'task_id': x.task_id, 'family': x.family,
                           'content_sha256': x.content_sha256()}
                          for x in sorted(self.tasks, key=lambda x:x.task_id)],
                'prepare': self.prepare, 'online': self.online, 'transfer': self.transfer,
                'repeats': self.repeats,
                'historical_content_sha256': sorted(set(self.historical_content_sha256))}
        return {'manifest': body, 'sha256': digest(body),
                'limitations': ['Family names are declarations, not evidence of semantic independence.',
                    'Exact hashes do not detect paraphrases, template kinship, or unreported exposure.',
                    'Commitments do not hide low-entropy material or provide process isolation.']}
