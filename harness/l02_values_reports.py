"""Frozen Lab-owned value cases and existing public report/1 records."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from candidate import read_json
from check_cases import errors as case_errors
from l02_reports import case_digest, catalog_digest, file_reference, CommandFailure, ObservationFailure

GROUPS = tuple('author-' + str(n) for n in range(5)) + ('aux-grow', 'aux-panic')
CASE_NAMES = {group: ('values', 'raw-rejections', 'bootstrap', 'exports', 'helper-protocol') for group in GROUPS[:5]}
CASE_NAMES['author-2'] += ('mixed-candidates',)
CASE_NAMES['author-4'] += ('removed-api',)
CASE_NAMES.update({'aux-grow': ('output-capacity',), 'aux-panic': ('unwind',)})
LEVELS = {'exports': 'static', 'removed-api': 'compiled'}
BUDGETS = {'exports': 480000, 'removed-api': 480000, 'mixed-candidates': 480000}


def required_ids(group):
    return ['l02.native-values.' + group + '.' + name for name in CASE_NAMES[group]]


def failure_status(error):
    if isinstance(error, ObservationFailure):
        return 'failed'
    if isinstance(error, CommandFailure):
        value = error.value
        if (value.get('timeout') is False and value.get('exit_code') == 2
                and re.search(r'(?m)^L02 values assertion:[0-9]+:.+$', value.get('stderr', ''))):
            return 'failed'
    return 'error'


class Reports:
    def __init__(self, root, output, candidates, revision, environment):
        findings = case_errors(root)
        if findings:
            raise ValueError('; '.join(findings))
        if set(candidates) != set(GROUPS):
            raise ValueError('all independently fixed value candidates are required')
        self.root, self.output = root, output
        self.candidates = deepcopy({g: {k: c[k] for k in ('manifest', 'provenance')} for g, c in candidates.items()})
        self.revision, self.environment = revision, deepcopy(environment)
        self.started_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        self.catalog = catalog_digest(root)
        self.cases, self.refs, self.completed, self.logs = {}, {}, {}, {}
        self.active = None
        self.attempted = {}
        for group in GROUPS:
            if set(candidates[group]['manifest']['required_cases']) != set(required_ids(group)):
                raise ValueError('candidate required case set differs from independent obligations')
            for name in CASE_NAMES[group]:
                case = read_json(root / 'cases/l02/native-values' / group / (name + '.json'))
                expected_id = 'l02.native-values.' + group + '.' + name
                if (case['id'] != expected_id or case['expected_result'] != {'kind': 'success'}
                        or case['steps'] != [{'id': name, 'action': 'environment' if name in LEVELS else 'call',
                                               'entrypoint': name, 'arguments': [{'kind': 'string', 'value': 'author=' + group}]}]
                        or case['timeout_policy'] != {'timeout_ms': BUDGETS.get(name, 180000), 'on_timeout': 'error', 'recovery': 'isolate'}):
                    raise ValueError('case identity, order or budget differs from fixed obligation')
                case['kind'] = 'instance'; case['selector'] = deepcopy(candidates[group]['manifest']['selector'])
                case['requires']['environment'] = [{'id': e['id'], 'version': e['version']} for e in environment]
                path = output / 'cases' / group / (name + '.json'); path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + '\n')
                key = group, name; self.cases[key] = case; self.refs[key] = file_reference(path, output); self.logs[key] = []
        index = {'started_at': self.started_at, 'lab_revision': revision, 'case_catalog_digest': self.catalog,
                 'cases': [{'id': c['id'], 'case_digest': case_digest(c), 'instance': self.refs[k],
                            'candidate_digest': self.candidates[k[0]]['manifest']['candidate_digest']} for k, c in self.cases.items()]}
        p = output / 'case-inputs.json'; p.write_text(json.dumps(index, indent=2) + '\n'); self.index = file_reference(p, output)

    def begin(self, group, name):
        key = group, name
        if self.active is not None or key not in self.cases or key in self.completed:
            raise ValueError('case invocation differs from frozen obligations')
        self.active = key
        return self.cases[key]['timeout_policy']['timeout_ms'] / 1000

    def note_target(self, log):
        if self.active is None:
            raise ValueError('target has no frozen active case')
        path = self.output / log
        value = read_json(path)
        if (type(value.get('duration_ns')) is not int or value['duration_ns'] < 0
                or type(value.get('exit_code')) is not int or type(value.get('timeout')) is not bool):
            raise ValueError('target attempt lacks complete timed process evidence')
        ref = file_reference(path, self.output)
        self.attempted.setdefault(self.active, []).append({'log': ref, 'duration_ns': value['duration_ns']})

    def finish(self, start_ns, end_ns, log_refs, observations):
        if self.active is None or type(start_ns) is not int or type(end_ns) is not int or end_ns < start_ns:
            raise ValueError('case has no actual monotonic execution interval')
        key = self.active
        if end_ns - start_ns > self.cases[key]['timeout_policy']['timeout_ms'] * 1000000:
            raise RuntimeError('case exhausted its fixed time budget')
        if not log_refs or not observations:
            raise ValueError('case lacks raw command and independent observation')
        for ref in log_refs:
            if file_reference(self.output / ref['path'], self.output) != ref:
                raise ValueError('case evidence changed while checking it')
        self.logs[key] = deepcopy(log_refs)
        self.completed[key] = {'duration_ns': end_ns - start_ns, 'observations': deepcopy(observations)}
        self.active = None

    def verify(self):
        if set(self.completed) != set(self.cases) or self.active is not None:
            raise ValueError('mandatory independent value cases are incomplete')
        if catalog_digest(self.root) != self.catalog or case_errors(self.root):
            raise ValueError('case catalog or fixture changed after freeze')
        if file_reference(self.output / self.index['path'], self.output) != self.index:
            raise ValueError('pre-execution case index changed')
        for key, ref in self.refs.items():
            if file_reference(self.output / ref['path'], self.output) != ref:
                raise ValueError('frozen case instance changed')
            for log in self.logs[key]:
                if file_reference(self.output / log['path'], self.output) != log:
                    raise ValueError('raw case log changed')

    def write(self, local, error=None):
        if error is None:
            self.verify()
            if local['result'] != 'passed':
                raise ValueError('failed engineering run cannot produce a passed report')
        owner = self.active or next(iter(self.cases))
        failure_id = self.cases[owner]['id']
        shared = [file_reference(self.output / 'report.json', self.output), self.index]
        shared += [file_reference(self.output / item['path'], self.output) for item in local['logs']]
        if (self.output / 'consumer-sources.tar').is_file():
            shared.append(file_reference(self.output / 'consumer-sources.tar', self.output))
        outputs = []
        for group in GROUPS:
            manifest = self.candidates[group]['manifest']; provenance = self.candidates[group]['provenance']
            results = []
            for name in CASE_NAMES[group]:
                key = group, name; c = self.cases[key]; complete = self.completed.get(key)
                status = 'passed' if error is None else failure_status(error) if key == owner else 'blocked'
                reason = ('fixed independent case, actual raw evidence and final input closure passed' if error is None else str(error)[:3000])
                if error is not None and key != owner: reason += '; blocked by shared final qualification: ' + failure_id
                attempts = self.attempted.get(key, [])
                level = LEVELS.get(name, 'target-run') if complete else 'target-run' if attempts else 'static'
                results.append({'case_id': c['id'], 'case_digest': case_digest(c), 'status': status,
                    'expected': c['expected_result'],
                    'actual': {'kind': 'success' if status == 'passed' else 'rejection' if status == 'failed' else 'unavailable' if key == owner or complete else 'not-run',
                               'code': 'AssertionFailed' if status == 'failed' else None, 'stage': 'run' if status == 'failed' else None,
                               'exit_code': 0 if status == 'passed' else None, 'reason': reason},
                    'evidence_level': level, 'duration_ms': (sum(a['duration_ns'] for a in attempts) if complete is None else complete['duration_ns']) // 1000000,
                    'resource_observations': [],
                    'diagnostics': [{'code': 'LAB.ValuesScope', 'message': 'Inline values need no consumer free/close. Process reaping and output checks are evidenced; no numeric Rust allocation or author-call counter is claimed. Helper-provider results prove only the generated inline helper.', 'location': None}],
                    'cleanup': 'complete' if error is None and complete else 'failed' if complete or attempts else 'not-run',
                    'attachments': [self.refs[key], *shared], 'blocked_by': [failure_id] if status == 'blocked' else []})
            report = {'schema': 'madb.report/1', 'run_id': 'l02.' + manifest['selector']['profile_id'],
                      'identity': {'input_digest': provenance['input_digest'], 'tool_digest': provenance['tool_digest'],
                                   'profile_digest': manifest['selector']['profile_digest'], 'candidate_digest': manifest['candidate_digest'],
                                   'lab_revision': self.revision, 'case_catalog_digest': self.catalog},
                      'selector': manifest['selector'], 'started_at': self.started_at, 'environment': self.environment, 'results': results}
            path = self.output / (group + '.report.json'); path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
            outputs.append(file_reference(path, self.output))
        return outputs
