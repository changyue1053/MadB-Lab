"""Literal ADR-0026 resource expectations, independent of generated bindings."""
from __future__ import annotations

from candidate import parse_json
from l02_reports import ObservationFailure

CASE_NAMES = ('values', 'ranges', 'close', 'isolate', 'package')
MODES = ('jit', 'aot')
CASE_IDS = tuple('e04.dart-sync.' + name for name in CASE_NAMES)


def expected_rows(name):
    if name == 'values':
        return [
            {'id': label, 'length': length, 'sum': total, 'input_preserved': True, 'state': 'open'}
            for label, length, total in [('empty', 0, 0), ('zero', 1, 0), ('byte-max', 1, 255),
                                          ('mixed', 5, 511), ('max-length', 65536, 16711680)]
        ] + [{'id': 'explicit-close', 'state': 'closed'},
             {'id': 'sequential-reopen', 'sum': 256, 'state': 'open'},
             {'id': 'second-close', 'state': 'closed'}]
    if name == 'ranges':
        return [{'id': 'too-long', 'error': 'RangeError', 'state': 'open', 'input_preserved': True},
                {'id': 'timeout--1', 'error': 'RangeError', 'state': 'open'},
                {'id': 'timeout-4294967296', 'error': 'RangeError', 'state': 'open'},
                {'id': 'after-rejection', 'sum': 5, 'state': 'open'},
                {'id': 'explicit-close', 'state': 'closed'}]
    if name == 'close':
        return [row for timeout in (1000, 4294967295) for row in (
            {'id': f'before-{timeout}', 'state': 'open'},
            {'id': f'closed-{timeout}', 'state': 'closed'},
            {'id': f'repeat-{timeout}', 'state': 'closed'},
            {'id': f'after-{timeout}', 'error': 'StateError', 'state': 'closed'})]
    if name == 'isolate':
        return [{'id': 'library', 'error': 'ArgumentError'}, {'id': 'engine', 'error': 'ArgumentError'},
                {'id': 'original-owner', 'sum': 23, 'state': 'open'},
                {'id': 'explicit-close', 'state': 'closed'},
                {'id': 'receiver-exit', 'normal': True, 'errors': 0}]
    raise ValueError('unknown ordinary resource case')


def _exact_shape(actual, expected):
    if type(actual) is not type(expected):
        raise ValueError('observation type differs (including bool versus int)')
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            raise ValueError('observation keys differ')
        for key in expected:
            _exact_shape(actual[key], expected[key])
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError('observation count differs')
        for item, want in zip(actual, expected):
            _exact_shape(item, want)


def inspect_output(stdout, name, *, expected_pid, load_kind=None, load_facts=None):
    """One complete target response, not a success marker or producer oracle."""
    value = parse_json(stdout.encode('utf-8'))
    if not isinstance(value, dict) or set(value) != {'case', 'pid', 'observations'}:
        raise ValueError('missing/extra target response fields')
    if type(expected_pid) is not int or expected_pid < 1 or type(value['pid']) is not int:
        raise ValueError('target must bind an actual positive process ID')
    if value['pid'] != expected_pid or value['case'] != name:
        raise ObservationFailure('response case/process differs from actual invocation')
    if name != 'load':
        expected = expected_rows(name)
        _exact_shape(value['observations'], expected)
        if value['observations'] != expected:
            raise ObservationFailure('ordinary Dart observation differs from literal expectation')
    else:
        if load_kind == 'success':
            expected = [{'id': 'load', 'kind': 'success', 'sum': 3}]
            _exact_shape(value['observations'], expected)
            if value['observations'] != expected:
                raise ObservationFailure('loaded SDK ordinary value differs')
        elif load_kind in {'missingAsset', 'digestMismatch', 'pathViolation', 'invalidPackage'}:
            rows = value['observations']
            if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
                    or set(rows[0]) != {'id', 'kind', 'path', 'expected_digest', 'actual_digest'}):
                raise ValueError('load rejection lacks typed load exception facts')
            row = rows[0]
            if row['id'] != 'load' or row['kind'] != load_kind:
                raise ObservationFailure('load rejection kind differs')
            if not isinstance(row['path'], str) or not row['path']:
                raise ValueError('load rejection lacks actual path')
            for key in ('expected_digest', 'actual_digest'):
                if row[key] is not None and (not isinstance(row[key], str)
                                             or len(row[key]) != 64
                                             or any(c not in '0123456789abcdef' for c in row[key])):
                    raise ValueError('load exception digest is malformed')
            if not isinstance(load_facts, dict) or set(load_facts) != {'path', 'expected_digest', 'actual_digest'}:
                raise ValueError('load rejection lacks independently pinned path/byte facts')
            if {key: row[key] for key in load_facts} != load_facts:
                raise ObservationFailure('load error path or original/actual digest differs from damaged copy facts')
        else:
            raise ValueError('load case lacks an independently chosen expectation')
    return value['observations']


def required_probes(name):
    if name not in CASE_NAMES:
        raise ValueError('unknown E04 case')
    variants = ('ordinary', 'missing-native', 'changed-native', 'symlink-native') if name == 'package' else ('ordinary',)
    return tuple((mode, variant) for mode in MODES for variant in variants)
