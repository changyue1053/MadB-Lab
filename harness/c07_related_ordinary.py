"""Recheck an explicitly pinned ordinary report and its actual target artifacts.

This consumes the existing report/attachment protocol. Static profile pairing is
necessary, but never substitutes for reparsing the normal and wrong-library logs.
"""
import json
from pathlib import Path
import zipfile
from candidate import CandidateError, file_digest, read_json
from c07_candidate import verify_candidate, native_inventory, identity_values
from c07_contract import case_requirements
from c07_profile_pair import verify_profile_pair
from c07_observations import parse_ordinary
from c07_ordinary_identity_observations import parse, expected_cases


def require(ok, message):
    if not ok:
        raise CandidateError('ArtifactMismatch', 'related ordinary evidence: ' + message)


def read_ref(root, item):
    require(isinstance(item, dict) and set(item) == {'path', 'sha256', 'size'}, 'invalid file reference')
    path = root / item['path']
    require(not Path(item['path']).is_absolute() and path.resolve().is_relative_to(root.resolve()), 'reference escapes report directory')
    data = path.read_bytes()
    require(file_digest(data) == item['sha256'] and len(data) == item['size'], 'changed attachment: ' + item['path'])
    return data


def verify_hap(root, build, candidate, fixture=None):
    require(build['candidate_digest'] == candidate['manifest']['candidate_digest'], 'build belongs to another candidate')
    data = read_ref(root, build['hap'])
    read_ref(root, build['source_archive']); read_ref(root, build['namecache'])
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'duplicate HAP members')
        members = {name: archive.read(name) for name in names if not name.endswith('/')}
    actual = [{'path': name, 'sha256': file_digest(raw), 'size': len(raw)} for name, raw in sorted(members.items())]
    require(actual == build['members'], 'HAP member receipt differs')
    expected = {name.removeprefix('package/'): raw for name, raw in candidate['native_members'].items()}
    if fixture:
        expected[fixture['replaced_member'].removeprefix('package/')] = fixture['library']
    require(native_inventory(members) == expected, 'HAP does not contain exactly the intended native closure')
    abc = [raw for name, raw in members.items() if name.endswith('.abc')]
    require(len(abc) == 1 and identity_values(abc[0], binary=True) == {candidate['identity']['expected_identity'].encode()}, 'HAP expected identity changed')
    app = json.loads(members['module.json'])['app']
    require(app == build['app'] and app['buildMode'] == 'release' and app['minAPIVersion'] == 60100023, 'HAP Release/API23 profile differs')
    return build['hap']


def replay(commands, prefix, observation, parser):
    pid = str(observation.get('pid', ''))
    require(pid.isdigit() and int(pid) > 0, 'missing actual positive PID')
    current_pid = None
    for path, command in commands:
        if not path.startswith(prefix) or '/' in path[len(prefix):]:
            continue
        argv = command.get('command', [])
        if command.get('timeout') is not False or command.get('exit_code') != 0:
            continue
        if argv[-3:] == ['shell', 'pidof', 'com.madb.c07probe']:
            current_pid = command.get('stdout', '').strip()
        # Exact suffix allows only a bounded, recorded hilog read, not a supplied
        # arbitrary text file that happened to contain expected markers.
        if argv[-5:] != ['shell', 'hilog', '-x', '-T', 'MadBC07Probe'] or current_pid != pid:
            continue
        value = parser(command['stdout'], pid)
        if value['status'] == 'passed':
            require(value['frames'] == observation['frames'], 'saved observation disagrees with raw log')
            return {'command': path, 'nonce': value['nonce'], 'pid': value['pid'], 'frames': value['frames']}
    raise CandidateError('ArtifactMismatch', 'related ordinary evidence: no successful PID-bound raw command observation')


def verify_related_ordinary(report_path, report_pin, companion, *, lab_revision):
    path = Path(report_path).resolve(); root = path.parent
    require(file_digest(path.read_bytes()) == report_pin, 'report pin differs')
    report = read_json(path)
    require(report.get('schema') == 'madb.report/1' and not report.get('extensions') and not report['run_id'].startswith('provisional.'), 'report is not formal')
    require(report['identity']['lab_revision'] == lab_revision, 'ordinary and companion Lab revisions differ')
    refs = {}
    for result in report['results']:
        for item in result['attachments']:
            require(item['path'] not in refs or refs[item['path']] == item, 'conflicting attachment references')
            refs[item['path']] = item
    for item in refs.values(): read_ref(root, item)
    def load(name):
        require(name in refs, 'required attachment absent: ' + name)
        return json.loads(read_ref(root, refs[name]))
    admission = load('admission.json')
    ordinary = verify_candidate(Path(admission['candidate_file']['source']), companion['route'], companion=False)
    require(file_digest((ordinary['root']/'candidate.json').read_bytes()) == admission['candidate_file']['sha256'], 'ordinary candidate file changed')
    digest = ordinary['manifest']['candidate_digest']
    require(digest == admission['candidate_digest'] == report['identity']['candidate_digest'] and report['selector'] == ordinary['manifest']['selector'], 'ordinary report candidate differs')
    require(not ordinary['provenance'].get('provisional', False), 'ordinary candidate is provisional')
    required = {row['id'] for row in case_requirements(ordinary['profile']['id'])}
    require(len(report['results']) == len(required) and {r['case_id'] for r in report['results']} == required and all(r['status'] == 'passed' and r['cleanup'] == 'complete' for r in report['results']), 'ordinary required results incomplete')
    pair = verify_profile_pair(ordinary, companion)
    require(pair.get('status') == 'bound', 'ordinary/test source profile pair is not bound')
    commands = [(item['path'], json.loads(read_ref(root, item))) for item in load('command-manifest.json')['commands']]
    require(len(commands) == len({p for p, _ in commands}), 'duplicate commands')
    normal = [(name, json.loads(read_ref(root, item))) for name, item in refs.items() if '-observation-' in name and '/' not in name]
    normal = [(name, value) for name, value in normal if value.get('status') == 'passed']
    require(len(normal) == 1, 'normal positive control is absent/ambiguous')
    observation = normal[0][1]; nonce = observation['nonce']
    normal_raw = replay(commands, 'commands/', observation, lambda raw,pid: parse_ordinary(raw, nonce=nonce, pid=pid))
    positive_build = load(nonce+'-build.json'); require(positive_build['nonce'] == nonce, 'positive build nonce differs')
    verify_hap(root, positive_build, ordinary)
    negatives = load('ordinary-identity-results.json')
    require(negatives['status'] == 'passed' and negatives['candidate_digest'] == digest and negatives['route'] == companion['route'], 'ordinary negative batch incomplete')
    wanted = expected_cases(companion['route'])
    require(set(negatives['observations']) == set(wanted), 'wrong-library cases not exact')
    collection = negatives['fixture_inputs'][0]
    if companion['route'] == 'kotlin':
        from c07_kotlin_identity_fixtures import admit_kotlin_identity_fixtures as admit
    else:
        from c07_identity_fixtures import admit_identity_fixtures as admit
    fixtures, fixture_refs = admit(Path(collection['path']), collection['sha256'], ordinary)
    observed = {}
    for case in wanted:
        envelope = negatives['observations'][case]
        require(envelope['candidate_digest'] == digest and envelope['run_id'] == negatives['run_id'] and envelope['cleanup'] == 'complete', 'negative envelope binding differs')
        value = envelope['observation']
        require(value['status'] == 'passed' and value['case'] == case and value['route'] == companion['route'], 'negative result differs')
        for item in envelope['attachments']: read_ref(root, item)
        prefix = 'ordinary-identity/'+case+'/'
        childrefs = {item['path']: item for item in envelope['attachments']}
        buildpath = prefix+value['nonce']+'-build.json'
        require(buildpath in childrefs, 'negative build receipt absent')
        build = json.loads(read_ref(root, childrefs[buildpath])); require(build['nonce'] == value['nonce'], 'negative build nonce differs')
        hap = verify_hap(root/prefix, build, ordinary, fixtures[case.removeprefix('ordinary-identity-')])
        raw = replay(commands, prefix+'commands/', value, lambda raw,pid: parse(raw,nonce=value['nonce'],pid=pid,case=case,route=companion['route']))
        observed[case] = dict(raw, hap=dict(hap,path=prefix+hap['path']))
    return {'status':'bound','route':companion['route'],'ordinary_candidate_digest':digest,
        'companion_candidate_digest':companion['manifest']['candidate_digest'],'report':{'path':str(path),'sha256':report_pin,'size':path.stat().st_size},
        'pair':pair,'positive':normal_raw,'negatives':observed,'fixture_inputs':fixture_refs,
        'scope':'ordinary unchanged facade actual 3/6 rejected libraries; owner-count claims require this companion independent observations'}
