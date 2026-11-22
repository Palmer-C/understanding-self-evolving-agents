"""Versioned local file-tool boundary, NOT an untrusted-code OS sandbox.

No command execution is exposed here. Existing frozen experiment dependencies
are left unchanged. A future runner must separately restrict the process that
executes generated code; cwd/protected filenames do not provide that isolation.
Single writer; protection does not claim race-proof handling of adversarial
filesystem replacement or Windows reparse-point races.
"""
from __future__ import annotations
from pathlib import Path, PurePosixPath, PureWindowsPath
import os


class FileBoundaryViolation(ValueError): pass


def relative_name(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise FileBoundaryViolation('nonempty relative path required')
    normalized = value.replace('\\', '/')
    if PurePosixPath(normalized).is_absolute() or PureWindowsPath(value).drive:
        raise FileBoundaryViolation('absolute/drive/UNC path forbidden')
    parts = normalized.split('/')
    if any(x in ('', '.', '..') or ':' in x or x.endswith((' ', '.')) for x in parts):
        raise FileBoundaryViolation('ambiguous, alternate-stream, or traversal path')
    for part in parts:
        base = part.split('.')[0].upper()
        if base in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(10)),*(f'LPT{i}' for i in range(10))}:
            raise FileBoundaryViolation('reserved device name')
    return '/'.join(parts)


class PublicFileBoundary:
    """Only explicitly listed public material can be read; writable subset only."""
    def __init__(self, root, *, readable, writable):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir(): raise FileBoundaryViolation('root is not a directory')
        self.readable = frozenset(relative_name(x).casefold() for x in readable)
        self.writable = frozenset(relative_name(x).casefold() for x in writable)
        if not self.writable <= self.readable:
            raise FileBoundaryViolation('writable paths must be publicly readable')

    def _resolve(self, name, *, writing=False):
        rel = relative_name(name)
        allowed = self.writable if writing else self.readable
        if rel.casefold() not in allowed:
            raise FileBoundaryViolation('path is not in the declared public manifest')
        target = (self.root / rel).resolve()
        try: target.relative_to(self.root)
        except ValueError: raise FileBoundaryViolation('resolved target is outside root') from None
        # Windows is case-insensitive for our workspace; resolve plus relative_to
        # avoids the old raw string-prefix sibling-directory mistake.
        if target == self.root: raise FileBoundaryViolation('file target required')
        current = self.root
        for part in Path(rel).parts:
            current = current / part
            if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
                raise FileBoundaryViolation('links/reparse junctions are not public material')
        if target.exists() and (not target.is_file() or target.stat().st_nlink > 1):
            raise FileBoundaryViolation('target must be an ordinary single-link file')
        return target

    def read(self, name):
        return self._resolve(name).read_text(encoding='utf-8')

    def write(self, name, text):
        if not isinstance(text, str): raise TypeError('text required')
        target = self._resolve(name, writing=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')


def partition_public_files(files, *, public_names, final_names):
    """Build model-facing payload using an explicit disjoint manifest.

    Returning only named public bytes avoids accidental bundling of final tests.
    It does not prevent arbitrary executed code from accessing the host system.
    """
    names = {relative_name(x).casefold():x for x in files}
    if len(names) != len(files): raise FileBoundaryViolation('case-insensitive filename collision')
    public = {relative_name(x).casefold() for x in public_names}
    final = {relative_name(x).casefold() for x in final_names}
    if public & final: raise FileBoundaryViolation('public/final file overlap')
    if public | final != set(names): raise FileBoundaryViolation('every input file must be classified exactly once')
    if any(not isinstance(x,str) for x in files.values()): raise FileBoundaryViolation('text file payload required')
    return {names[k]:files[names[k]] for k in sorted(public)}
