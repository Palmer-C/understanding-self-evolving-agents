#!/usr/bin/env python3
"""Offline source-index audit; matches describe identity links, not source approval.

Default CLI retains the A--F informational report. --root selects a repository;
--json prints the same report data as JSON. No imports read or write repository
files. Only modern arXiv IDs in eprint/arXiv URL fields participate in matching.
An arXiv match is paper-level: it never verifies a version or PDF content.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
KEY_SHAPE = re.compile(r"^[A-Za-z0-9_.:/-]+$")
ARXIV_ID = re.compile(r"(?:arxiv\s*:\s*)?(\d{4}\.\d{4,5})(v[1-9]\d*)?", re.I)


def slug(value):
    """Retain the existing alphabetic slug convention; collisions are not choices."""
    return re.sub(r"[^a-z]", "", value.lower())


def _group(text, start):
    """Return a balanced {...}, (...), or [...] group and the next offset."""
    opening = text[start]
    closing = {"{": "}", "(": ")", "[": "]"}[opening]
    depth, braces, quoted = 1, 0, False
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '%' and not quoted and ((opening == '{' and depth == 1) or
                                          (opening != '{' and braces == 0)):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end + 1
            continue
        if opening == '{':
            if ch == '"' and depth == 1:
                quoted = not quoted
            if ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
        else:
            if ch == '"' and braces == 0:
                quoted = not quoted
            if ch == '{':
                braces += 1
            elif ch == '}':
                braces -= 1
            elif not quoted and braces == 0:
                if ch == opening:
                    depth += 1
                elif ch == closing:
                    depth -= 1
        if depth == 0:
            return text[start + 1:i], i + 1
        i += 1
    raise ValueError('unclosed balanced group')


def _top_parts(text):
    """Split entry fields at top-level commas, respecting braces and quotes."""
    parts, begin, braces, quoted, i = [], 0, 0, False, 0
    while i < len(text):
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch == '"' and braces == 0:
            quoted = not quoted
        elif ch == '{':
            braces += 1
        elif ch == '}':
            braces -= 1
        elif ch == ',' and not quoted and braces == 0:
            parts.append(text[begin:i])
            begin = i + 1
        i += 1
    parts.append(text[begin:])
    return parts


def _unquote(value):
    value = value.strip()
    if value.startswith('{'):
        try:
            body, end = _group(value, 0)
        except ValueError:
            return value
        if end == len(value):
            return body.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1].strip()
    return value


def _strip_bib_field_comments(text):
    """Remove comments outside field values, preserving literal percent text."""
    kept, braces, quoted, i = [], 0, False, 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            kept.extend(text[i:i + 2])
            i += 2
            continue
        if ch == '%' and braces == 0 and not quoted:
            end = text.find('\n', i)
            if end < 0:
                break
            kept.append('\n')
            i = end + 1
            continue
        if ch == '"' and braces == 0:
            quoted = not quoted
        elif ch == '{':
            braces += 1
        elif ch == '}':
            braces -= 1
        kept.append(ch)
        i += 1
    return ''.join(kept)


def parse_bibtex(text):
    """Return complete balanced entries and visible parse limitations.

    This is a literal-field reader, not a BibTeX expansion engine. @string,
    @preamble and @comment are skipped; concatenated/macro ID values do not
    become arXiv IDs. Malformed entries are reported rather than sliced into
    their neighbours.
    """
    entries, warnings, i = [], [], 0
    header = re.compile(r'@([A-Za-z]+)\s*([{(])')
    while i < len(text):
        if text[i] == '%':
            end = text.find('\n', i)
            i = len(text) if end < 0 else end + 1
            continue
        if text[i] != '@':
            i += 1
            continue
        match = header.match(text, i)
        if not match:
            i += 1
            continue
        line = text.count('\n', 0, i) + 1
        try:
            body, i = _group(text, match.end() - 1)
        except ValueError:
            warnings.append({'kind': 'unclosed_bib_entry', 'line': line})
            break
        entry_type = match.group(1).lower()
        if entry_type in {'string', 'preamble', 'comment'}:
            if entry_type == 'string':
                warnings.append({'kind': 'bib_string_not_expanded', 'line': line})
            continue
        body = _strip_bib_field_comments(body)
        parts = _top_parts(body)
        key = parts[0].strip()
        if not key or not KEY_SHAPE.fullmatch(key):
            warnings.append({'kind': 'invalid_bib_key', 'line': line, 'key': key})
            continue
        fields = defaultdict(list)
        for part in parts[1:]:
            if not part.strip():
                continue
            field = re.fullmatch(r'\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(.*?)\s*', part, re.S)
            if field:
                fields[field.group(1).lower()].append(_unquote(field.group(2)))
            else:
                warnings.append({'kind': 'unparsed_bib_field', 'line': line, 'key': key})
        for name, values in fields.items():
            if len(values) > 1:
                warnings.append({'kind': 'duplicate_bib_field', 'key': key, 'field': name})
        entries.append({'key': key, 'type': entry_type, 'line': line, 'fields': dict(fields)})
    return entries, warnings


def arxiv_identity(value, *, url_only=False):
    """Recognize one whole modern arXiv identifier or an actual arXiv URL."""
    value = value.strip()
    if not url_only:
        match = ARXIV_ID.fullmatch(value)
        if match:
            return {'paper_id': match.group(1), 'version': (match.group(2) or '').lower() or None}
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {'http', 'https'} or (parsed.hostname or '').lower() not in {
        'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'
    }:
        return None
    match = re.fullmatch(r'/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(v[1-9]\d*)?(?:\.pdf)?/?',
                         parsed.path, re.I)
    if not match:
        return None
    return {'paper_id': match.group(1), 'version': (match.group(2) or '').lower() or None}


def entry_arxiv_identities(entry):
    """Ignore titles, notes, arbitrary numeric text and non-arXiv URLs."""
    identities = []
    fields = entry['fields']
    prefixes = fields.get('archiveprefix', [])
    if not prefixes or all(p.casefold() == 'arxiv' for p in prefixes):
        for value in fields.get('eprint', []):
            identity = arxiv_identity(value)
            if identity:
                identities.append(dict(identity, field='eprint', value=value))
    for value in fields.get('url', []):
        identity = arxiv_identity(value, url_only=True)
        if identity:
            identities.append(dict(identity, field='url', value=value))
    return identities


def strip_tex_comments(text):
    lines = []
    for line in text.splitlines():
        for i, ch in enumerate(line):
            if ch == '%':
                slashes = 0
                for previous in reversed(line[:i]):
                    if previous != '\\':
                        break
                    slashes += 1
                if slashes % 2 == 0:
                    line = line[:i]
                    break
        lines.append(line)
    return '\n'.join(lines)


def cited_keys(text):
    """Read citation commands with optional args; exclude the numeric cited macro."""
    text = strip_tex_comments(text)
    # Literal code examples are not rendered citations.
    text = re.sub(r'\\begin\{(verbatim\*?|lstlisting|minted)\}.*?\\end\{\1\}', '', text, flags=re.S)
    found = set()
    command = re.compile(r'\\((?:cite|Cite)[A-Za-z]*)(?![A-Za-z])\*?')
    for match in command.finditer(text):
        if match.group(1).casefold() == 'cited':
            continue
        i = match.end()
        while i < len(text) and text[i].isspace():
            i += 1
        try:
            while i < len(text) and text[i] == '[':
                _, i = _group(text, i)
                while i < len(text) and text[i].isspace():
                    i += 1
            if i >= len(text) or text[i] != '{':
                continue
            body, _ = _group(text, i)
        except ValueError:
            continue
        for key in body.split(','):
            key = key.strip()
            if KEY_SHAPE.fullmatch(key):
                found.add(key)
    return found


def _index(items, values):
    result = defaultdict(set)
    for i, item in enumerate(items):
        for value in values(item):
            if value:
                result[value].add(i)
    return result


def build_report(root):
    """Read a repository and return one mapping shared by report sections B/C/D/F."""
    root = Path(root)
    with (root / 'references/sources.csv').open(encoding='utf-8-sig', newline='') as handle:
        sources = []
        for line, row in enumerate(csv.DictReader(handle), 2):
            key = (row.get('short_name') or '').strip()
            if key:
                sources.append({'key': key, 'line': line, 'row': row,
                                'aliases': [a.strip() for a in (row.get('bib_alias') or '').split(',') if a.strip()],
                                'arxiv': arxiv_identity(row.get('arxiv_id') or '')})
    entries, warnings = parse_bibtex((root / 'book/bib/references.bib').read_text(encoding='utf-8-sig'))
    for entry in entries:
        entry['arxiv'] = entry_arxiv_identities(entry)
    cited, tex_files = set(), []
    for path in sorted((root / 'book').rglob('*.tex')):
        if any(part.casefold() == 'build' for part in path.relative_to(root / 'book').parts[:-1]):
            continue
        tex_files.append(str(path.relative_to(root)).replace('\\', '/'))
        cited.update(cited_keys(path.read_text(encoding='utf-8-sig')))
    csv_key = _index(sources, lambda s: [s['key']])
    csv_slug = _index(sources, lambda s: [slug(s['key'])])
    csv_alias = _index(sources, lambda s: s['aliases'])
    csv_arxiv = _index(sources, lambda s: [s['arxiv']['paper_id']] if s['arxiv'] else [])
    bib_key = _index(entries, lambda b: [b['key']])
    bib_arxiv = _index(entries, lambda b: {a['paper_id'] for a in b['arxiv']})
    ambiguities = []
    for kind, index, items in [('duplicate_source_key', csv_key, sources),
                               ('duplicate_source_slug', csv_slug, sources),
                               ('duplicate_alias', csv_alias, sources),
                               ('duplicate_source_arxiv', csv_arxiv, sources),
                               ('duplicate_bib_key', bib_key, entries),
                               ('duplicate_bib_arxiv', bib_arxiv, entries)]:
        for value, indexes in sorted(index.items()):
            if len(indexes) > 1:
                ambiguities.append({'kind': kind, 'value': value,
                                    'severity': 'informational' if kind == 'duplicate_bib_arxiv' else 'unresolved_identity',
                                    'records': [{'key': items[i]['key'], 'line': items[i]['line']} for i in sorted(indexes)]})
    mappings, ambiguous_bib, ambiguous_sources = [], set(), set()
    for bi, entry in enumerate(entries):
        key = entry['key']
        ids = {a['paper_id'] for a in entry['arxiv']}
        signals = {'bib_alias': csv_alias.get(key, set()),
                   'exact': csv_key.get(key, set()),
                   'slug': csv_slug.get(slug(key), set()),
                   'arxiv': set().union(*(csv_arxiv.get(a, set()) for a in ids)) if ids else set()}
        candidates = set().union(*signals.values())
        reasons = []
        if len(candidates) > 1:
            reasons.append('multiple_source_candidates')
        if len(bib_key[key]) > 1:
            reasons.append('duplicate_bib_key')
        if len(ids) > 1:
            reasons.append('conflicting_arxiv_fields')
        if any(len(csv_arxiv[a]) > 1 for a in ids):
            reasons.append('duplicate_source_arxiv')
        if len(candidates) == 1:
            si = next(iter(candidates))
            source = sources[si]
            if ids and source['arxiv'] and source['arxiv']['paper_id'] not in ids:
                reasons.append('key_match_conflicts_with_arxiv')
        if reasons:
            ambiguous_bib.add(bi)
            if key in cited:
                ambiguous_sources.update(candidates)
            ambiguities.append({'kind': 'unresolved_bib_mapping', 'bib_key': key, 'line': entry['line'],
                                'reasons': reasons,
                                'candidate_sources': [{'key': sources[i]['key'], 'line': sources[i]['line']} for i in sorted(candidates)],
                                'methods': {method: [sources[i]['key'] for i in sorted(values)]
                                            for method, values in signals.items() if values}})
            continue
        if not candidates:
            continue
        si = next(iter(candidates))
        mappings.append({'bib_index': bi, 'source_index': si, 'bib_key': key,
                         'csv_key': sources[si]['key'], 'csv_line': sources[si]['line'],
                         'methods': [method for method, values in signals.items() if si in values],
                         'arxiv_paper_ids': sorted(ids), 'bib_arxiv_metadata': entry['arxiv'],
                         'csv_arxiv_metadata': sources[si]['arxiv'],
                         'identity_scope': 'paper-level only; version not verified' if ids else 'key correspondence only; content and version not verified',
                         'version_verified': False})
    mapped_bib = {m['bib_index'] for m in mappings}
    mapped_csv = {m['source_index'] for m in mappings}
    cited_csv = {m['source_index'] for m in mappings if m['bib_key'] in cited}
    missing_pdf, undeclared_pdf = [], []
    for mapping in mappings:
        source = sources[mapping['source_index']]
        declared = (source['row'].get('local_pdf') or '').strip()
        info = {'bib_key': mapping['bib_key'], 'csv_key': source['key'], 'local_pdf': declared}
        if not declared:
            undeclared_pdf.append(info)
        else:
            path = root / 'references' / declared
            if not path.is_file():
                missing_pdf.append(dict(info, checked_path=str(path)))
    return {
        'root': str(root),
        'counts': {'sources_csv_rows': len(sources), 'sources_csv_keys': len(csv_key),
                   'bib_entries': len(entries), 'cited_keys': len(cited), 'tex_files': len(tex_files)},
        'cited_keys': sorted(cited), 'tex_files': tex_files,
        'cited_not_in_bib': sorted(cited - set(bib_key)),
        'bib_without_csv': [b['key'] for i, b in enumerate(entries) if i not in mapped_bib],
        'csv_without_bib': [s['key'] for i, s in enumerate(sources) if i not in mapped_csv],
        'missing_local_pdf': missing_pdf, 'local_pdf_not_declared': undeclared_pdf,
        'bib_not_cited': sorted(set(bib_key) - cited),
        'csv_not_cited': [s['key'] for i, s in enumerate(sources) if i not in cited_csv and i not in ambiguous_sources],
        'csv_citation_unresolved': [s['key'] for i, s in enumerate(sources) if i in ambiguous_sources and i not in cited_csv],
        'mappings': mappings, 'ambiguities': ambiguities, 'parse_warnings': warnings,
        'identity_scope': 'Correspondence audit only; arXiv matches are paper-level, never version/PDF-content verification.',
    }


def format_report(report):
    lines = ['SOURCE-INDEX AUDIT',
             'sources.csv keys : %d' % report['counts']['sources_csv_keys'],
             'bib entries      : %d' % report['counts']['bib_entries'],
             'cited keys       : %d' % report['counts']['cited_keys']]
    sections = [('A. cited-but-not-in-bib (undefined-reference risk)', 'cited_not_in_bib', 'MISSING'),
                ('B. bib key without resolved sources.csv entry', 'bib_without_csv', 'BIB-NO-CSV'),
                ('C. sources.csv key without resolved bib entry', 'csv_without_bib', 'CSV-NO-BIB'),
                ('D. declared local PDF missing (per sources.csv local_pdf)', 'missing_local_pdf', 'NO-PDF'),
                ('E. bib entries never cited (informational)', 'bib_not_cited', 'NOT-CITED'),
                ('F. sources.csv entries not cited through resolved mapping (informational)', 'csv_not_cited', 'NOT-CITED')]
    for title, field, label in sections:
        lines.extend(['', '=' * 70, title, '=' * 70, '  count=%d' % len(report[field])])
        for value in report[field]:
            if isinstance(value, dict):
                value = 'bib={bib_key} csv={csv_key} path={local_pdf}'.format(**value)
            lines.append('  %s: %s' % (label, value))
    lines.extend(['', 'G. Ambiguities and parse limitations (not silently resolved)',
                  '  ambiguities=%d parse_warnings=%d' % (len(report['ambiguities']), len(report['parse_warnings']))])
    for value in report['ambiguities'] + report['parse_warnings']:
        lines.append('  ' + json.dumps(value, ensure_ascii=False, sort_keys=True))
    lines.append('  citation mapping unresolved: ' + ', '.join(report['csv_citation_unresolved']))
    lines.append('  mapped bib entries with no declared local_pdf: %d (not a file-existence PASS)' % len(report['local_pdf_not_declared']))
    for value in report['local_pdf_not_declared']:
        lines.append('  PDF-UNDECLARED: bib={bib_key} csv={csv_key}'.format(**value))
    lines.extend(['', 'SUMMARY: A=%d B=%d C=%d D=%d (E/F informational)' % tuple(
        len(report[k]) for k in ('cited_not_in_bib', 'bib_without_csv', 'csv_without_bib', 'missing_local_pdf')),
        report['identity_scope']])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT, help='repository root (default: parent of tools/)')
    parser.add_argument('--json', action='store_true', help='print structured report to stdout; do not write files')
    args = parser.parse_args(argv)
    try:
        report = build_report(args.root)
    except (OSError, csv.Error, UnicodeError) as error:
        parser.exit(2, 'SOURCE-INDEX INPUT ERROR: %s\n' % error)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report))
    # Compatibility: findings are reported, not converted into a new gate.
    return 0


if __name__ == '__main__':
    sys.exit(main())
