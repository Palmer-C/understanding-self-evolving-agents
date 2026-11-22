"""Offline candidate parser. Not connected to frozen E05 v2 or any backend.

Accept one action per response, validate tool arguments, and preserve source text.
The adapter accepts the observed DSML read call and JSON string control chars;
ambiguous or malformed actions fail closed. No action is executed here.
"""
from __future__ import annotations
import json
import re
import xml.etree.ElementTree as ET


class ActionFormatError(ValueError):
    pass


SCHEMAS = {'list_files': {}, 'read_file': {'path': str},
           'write_file': {'path': str, 'content': str}, 'run_tests': {}}


def _pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise ActionFormatError('duplicate JSON key')
        out[k] = v
    return out


def validate(tool, args):
    if tool not in SCHEMAS or not isinstance(args, dict):
        raise ActionFormatError('unknown tool or non-object arguments')
    schema = SCHEMAS[tool]
    if set(args) != set(schema) or any(type(args[k]) is not v for k, v in schema.items()):
        raise ActionFormatError('argument schema mismatch')
    if 'path' in args and (not args['path'] or '\x00' in args['path']):
        raise ActionFormatError('empty or NUL path')
    return tool, args


def parse_action(text):
    if len(text) > 100000:
        raise ActionFormatError('response too long')
    calls = list(re.finditer(r'^CALL\s+(\w+)[ \t]+', text, re.M))
    finishes = list(re.finditer(r'^FINISH[ \t]*$', text, re.M))
    dsml = '<｜｜DSML｜｜' in text or '</｜｜DSML｜｜' in text
    if finishes:
        if len(finishes) != 1 or calls or dsml:
            raise ActionFormatError('ambiguous FINISH')
        return 'FINISH', {}, 'finish'
    if calls:
        if len(calls) != 1 or dsml:
            raise ActionFormatError('multiple or mixed actions')
        m = calls[0]
        raw = text[m.end():].lstrip()
        try:
            args, end = json.JSONDecoder(strict=False, object_pairs_hook=_pairs).raw_decode(raw)
        except (ValueError, TypeError) as e:
            raise ActionFormatError('invalid JSON') from e
        # Do not quietly discard a second object/action after the first one.
        if raw[end:].strip():
            raise ActionFormatError('unexpected content after action')
        tool, args = validate(m.group(1), args)
        return tool, args, 'call-json'
    if dsml:
        raw = text.strip()
        if '<!DOCTYPE' in raw.upper() or '<!ENTITY' in raw.upper():
            raise ActionFormatError('XML declarations not accepted')
        raw = raw.replace('<｜｜DSML｜｜ ', '<').replace('</｜｜DSML｜｜ ', '</')
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise ActionFormatError('malformed DSML') from e
        if root.tag != 'calls' or root.attrib or len(root) != 1 or (root.text or '').strip():
            raise ActionFormatError('expected exactly one DSML call')
        call = root[0]
        if call.tag != 'invoke' or set(call.attrib) != {'name'} or (call.text or '').strip() or (call.tail or '').strip():
            raise ActionFormatError('invalid DSML invocation')
        args = {}
        for p in call:
            if p.tag != 'parameter' or set(p.attrib) != {'name','string'} or p.attrib['string'] != 'true' or len(p) or (p.tail or '').strip():
                raise ActionFormatError('invalid DSML parameter')
            key = p.attrib['name']
            if key in args:
                raise ActionFormatError('duplicate DSML parameter')
            args[key] = p.text or ''
        tool, args = validate(call.attrib['name'], args)
        return tool, args, 'dsml'
    raise ActionFormatError('no recognized action')
