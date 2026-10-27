"""Existing case/report v1 records for E04's finite resource consumer slice."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import re

from candidate import read_json, file_digest, parse_json
from check_cases import errors as case_errors
from e04_dart_observations import CASE_NAMES, CASE_IDS, required_probes, inspect_output
from l02_reports import (case_digest, catalog_digest, file_reference,
                         CommandFailure, ObservationFailure)

SCOPE = ('E04 finite macOS arm64 resource slice: JIT and AOT ordinary API, parameter rejection, '
         'explicit close, isolate transfer rejection and package asset rejection. '
         'No native counters, fault/timeout schedule, loader-graph fault, second value business, '
         'disabled/version isolation, full EXT acceptance or release claim.')


def read_command_log(path):
    # The 8 MiB bounded byte capture can expand to six times its size in JSON.
    with path.open('rb') as stream:
        return parse_json(stream.read(64 * 1024 * 1024 + 1), limit=64 * 1024 * 1024)


def case_steps(name):
    return [{'id': mode + '-' + variant, 'action': 'call', 'entrypoint': name,
             'arguments': [{'kind': 'string', 'value': mode}, {'kind': 'string', 'value': variant}]}
            for mode, variant in required_probes(name)]


def failure_status(error):
    if isinstance(error, ObservationFailure):
        return 'failed'
    if isinstance(error, CommandFailure):
        value = error.value
        if (value.get('timeout') is False and value.get('exit_code') == 2
                and re.search(r'(?m)^E04 assertion: .+$', value.get('stderr', ''))):
            return 'failed'
    return 'error'


class Reports:
    def __init__(self, root, output, candidate, revision, environment):
        findings = case_errors(root)
        if findings:
            raise ValueError('; '.join(findings))
        if set(candidate['manifest']['required_cases']) != set(CASE_IDS):
            raise ValueError('candidate required cases do not equal fixed independent resource cases')
        self.root, self.output = root, output
        self.candidate = deepcopy({key: candidate[key] for key in ('manifest', 'provenance')})
        self.revision, self.environment = revision, deepcopy(environment)
        self.catalog = catalog_digest(root)
        self.started_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        self.cases, self.references, self.records, self.attempts = {}, {}, {}, {}
        self.active = None
        self.commands = None
        self.active_command = None
        for name in CASE_NAMES:
            case = read_json(root / 'cases/e04/dart-sync' / (name + '.json'))
            if (case['id'] != 'e04.dart-sync.' + name or case['expected_result'] != {'kind': 'success'}
                    or case['steps'] != case_steps(name)
                    or case['timeout_policy'] != {'timeout_ms': len(required_probes(name)) * 60000,
                                                   'on_timeout': 'error', 'recovery': 'isolate'}):
                raise ValueError('case identity, steps, expectation or budget differs from fixed obligations')
            case['kind'] = 'instance'
            case['selector'] = deepcopy(candidate['manifest']['selector'])
            case['requires']['environment'] = [{'id': e['id'], 'version': e['version']} for e in environment]
            path = output / 'cases' / (name + '.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + '\n')
            self.cases[name], self.references[name] = case, file_reference(path, output)
            self.records[name], self.attempts[name] = [], []
        index = {'lab_revision': revision, 'case_catalog_digest': self.catalog,
                 'candidate_digest': candidate['manifest']['candidate_digest'],
                 'cases': [{'id': case['id'], 'case_digest': case_digest(case), 'instance': self.references[name]}
                           for name, case in self.cases.items()]}
        path = output / 'case-inputs.json'
        path.write_text(json.dumps(index, indent=2) + '\n')
        self.index = file_reference(path, output)

    def bind_commands(self, jit, aot):
        """Freeze separate actual JIT/AOT images and the compiled source/config."""
        if self.commands is not None or self.active is not None:
            raise ValueError('consumer commands can only be bound once before target execution')
        if len(jit) != 3 or len(aot) != 1 or not str(jit[1]).startswith('--packages='):
            raise ValueError('expected explicit Dart VM package configuration and separate AOT executable')
        from pathlib import Path
        dart, source, executable = Path(jit[0]), Path(jit[2]), Path(aot[0])
        config = Path(str(jit[1]).removeprefix('--packages='))
        if any(not p.is_absolute() or p.is_symlink() or not p.is_file() for p in (dart, source, executable, config)):
            raise ValueError('consumer command inputs must be actual absolute regular files')
        if dart == executable:
            raise ValueError('JIT and AOT cannot use the same program')
        source_data = source.read_bytes()
        fixtures = {case['fixture']['sha256'] for case in self.cases.values()}
        if fixtures != {file_digest(source_data)}:
            raise ValueError('compiled consumer source differs from fixed independent fixture')
        dart_tools = [item for item in self.environment if item['id'] == 'dart']
        if len(dart_tools) != 1 or dart_tools[0]['sha256'] != file_digest(dart.read_bytes()):
            raise ValueError('actual Dart command differs from recorded tool identity')
        self.commands = {'jit': [str(item) for item in jit], 'aot': [str(item) for item in aot]}
        self.command_files = {str(path): {'sha256': file_digest(path.read_bytes()), 'size': path.stat().st_size}
                              for path in (dart, source, executable, config)}
        path = self.output / 'consumer-commands.json'
        path.write_text(json.dumps({'commands': self.commands, 'files': self.command_files}, indent=2) + '\n')
        self.command_reference = file_reference(path, self.output)

    def begin(self, name, mode, variant, argv):
        if self.active is not None or name not in self.cases:
            raise ValueError('unknown or nested target case')
        planned = required_probes(name)
        index = len(self.records[name])
        if index >= len(planned) or planned[index] != (mode, variant):
            raise ValueError('target step differs from frozen JIT/AOT case order')
        command = [str(item) for item in argv]
        if self.commands is None or command[:len(self.commands[mode])] != self.commands[mode]:
            raise ValueError('target command does not use its separately frozen JIT/AOT entry')
        self.active = (name, mode, variant)
        self.active_command = command
        return 60

    def note_attempt(self, reference):
        if self.active is None:
            raise ValueError('target evidence has no selected case')
        if file_reference(self.output / reference['path'], self.output) != reference:
            raise ValueError('target log changed')
        raw = read_command_log(self.output / reference['path'])
        if raw.get('argv') != self.active_command:
            raise ValueError('actual command differs from the frozen target invocation')
        if (type(raw.get('pid')) is not int or raw['pid'] <= 0
                or type(raw.get('duration_ns')) is not int or raw['duration_ns'] < 0
                or type(raw.get('timeout')) is not bool or type(raw.get('reaped')) is not bool
                or (type(raw.get('exit_code')) is not int
                    and not (raw.get('exit_code') is None and raw['reaped'] is False))):
            raise ValueError('target log lacks actual PID/timing/exit facts')
        self.attempts[self.active[0]].append(deepcopy(reference))
        return raw

    def complete(self, reference, *, load_kind=None, load_facts=None):
        raw = self.note_attempt(reference)
        if (raw['exit_code'] != 0 or raw['timeout'] or raw.get('reaped') is not True
                or raw.get('watchdog_killed') is not False or raw.get('pipes_drained') is not True
                or raw.get('capture_complete') is not True or raw.get('output_limit_exceeded') is not False
                or raw.get('process_cleanup') != 'leader-reaped-pipes-drained'):
            raise ValueError('failed, timed out or unreaped process cannot satisfy an E04 case')
        name, mode, variant = self.active
        if raw['duration_ns'] > 60000 * 1000000:
            raise ValueError('target exhausted its fixed budget')
        observations = inspect_output(raw['stdout'], 'load' if name == 'package' else name,
                                      expected_pid=raw['pid'], load_kind=load_kind, load_facts=load_facts)
        self.records[name].append({'mode': mode, 'variant': variant, 'log': deepcopy(reference),
                                   'duration_ns': raw['duration_ns'], 'observations': observations})
        self.active = None
        self.active_command = None
        return observations

    def verify(self):
        if self.active is not None or any(tuple((r['mode'], r['variant']) for r in self.records[name]) != required_probes(name)
                                          for name in CASE_NAMES):
            raise ValueError('not all fixed resource cases have both actual JIT and AOT observations')
        if any(self.attempts[name] != [r['log'] for r in self.records[name]] for name in CASE_NAMES):
            raise ValueError('case actual target attempts are duplicated or incomplete')
        if catalog_digest(self.root) != self.catalog or case_errors(self.root):
            raise ValueError('case catalog changed')
        from pathlib import Path
        for name, expected in self.command_files.items():
            path = Path(name)
            if path.is_symlink() or {'sha256': file_digest(path.read_bytes()), 'size': path.stat().st_size} != expected:
                raise ValueError('frozen consumer command input changed')
        for ref in [self.index, self.command_reference, *self.references.values(), *(r['log'] for rows in self.records.values() for r in rows)]:
            if file_reference(self.output / ref['path'], self.output) != ref:
                raise ValueError('frozen case or evidence bytes changed')

    def write(self, local, error=None):
        if error is None:
            self.verify()
            if local['result'] != 'passed' or local.get('file_cleanup', {}).get('after') != {}:
                raise ValueError('unqualified engineering result cannot produce a passed public report')
        owner = self.active[0] if self.active else next((n for n in CASE_NAMES if not self.records[n]), CASE_NAMES[0])
        manifest, provenance = self.candidate['manifest'], self.candidate['provenance']
        results = []
        common = [self.index, file_reference(self.output / 'report.json', self.output), *local['logs']]
        if self.commands is not None:
            common.append(self.command_reference)
        for name in CASE_NAMES:
            status = 'passed' if error is None else failure_status(error) if name == owner else 'blocked'
            attempts = self.attempts[name]
            results.append({'case_id': self.cases[name]['id'], 'case_digest': case_digest(self.cases[name]),
                'status': status, 'expected': {'kind': 'success'},
                'actual': {'kind': 'success' if status == 'passed' else 'rejection' if status == 'failed' else 'unavailable' if attempts else 'not-run',
                           'code': 'AssertionFailed' if status == 'failed' else None,
                           'stage': 'run' if status == 'failed' else None,
                           'exit_code': 0 if status == 'passed' else None,
                           'reason': 'fixed JIT/AOT observations and input closure passed' if error is None else str(error)[:3000]},
                'evidence_level': 'target-run' if attempts else 'static',
                'duration_ms': sum(read_command_log(self.output / ref['path'])['duration_ns'] for ref in attempts) // 1000000,
                'resource_observations': [], 'diagnostics': [{'code': 'LAB.E04ResourceScope', 'message': SCOPE, 'location': None}],
                'cleanup': 'complete' if error is None else 'failed' if attempts else 'not-run',
                'attachments': [self.references[name], *common],
                'blocked_by': [self.cases[owner]['id']] if status == 'blocked' else []})
        report = {'schema': 'madb.report/1', 'run_id': 'e04.' + manifest['selector']['profile_id'],
                  'identity': {'input_digest': provenance['input_digest'], 'tool_digest': provenance['tool_digest'],
                               'profile_digest': manifest['selector']['profile_digest'], 'candidate_digest': manifest['candidate_digest'],
                               'lab_revision': self.revision, 'case_catalog_digest': self.catalog},
                  'selector': manifest['selector'], 'started_at': self.started_at,
                  'environment': self.environment, 'results': results}
        path = self.output / 'dart-sync.report.json'
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        return file_reference(path, self.output)
