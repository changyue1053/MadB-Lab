"""E04 public-envelope and installed-asset checks; no producer imports.

The profile/2 envelope and the original native identity are distinct layers.
This module never relaxes candidate.py's original profile/1 admission.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from candidate import (CandidateError, DIGEST, REVISION, ID, candidate_digest,
                       canonical_json, file_digest, logical_path, parse_json, semantic_digest,
                       project_digest, read_json, verify_candidate as verify_native_candidate,
                       verify_contract_digests, verify_layout_sources, verify_reference)
from e04_dart_observations import CASE_IDS

HEX = re.compile(r'[0-9a-f]{64}\Z')
ROUTE = 'org.madb.dart.c-ffi'
PROFILE = 'dart-c-ffi-sync-aarch64-apple-darwin'
TARGET = 'aarch64-apple-darwin'


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise CandidateError('FormatInvalid', f'{label} has missing or unknown fields')


def read_bound(root, row):
    name = str(logical_path(row['path']))
    path = root / name
    current = root
    for part in Path(name).parts:
        current /= part
        if current.is_symlink():
            raise CandidateError('ArtifactMismatch', f'symlink in public file path: {name}')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise CandidateError('ArtifactMismatch', f'missing or escaped public file: {name}')
    if (type(row.get('size')) is not int or row['size'] < 0
            or not isinstance(row.get('sha256'), str) or not DIGEST.fullmatch(row['sha256'])):
        raise CandidateError('FormatInvalid', 'invalid public file pin')
    data = path.read_bytes()
    if len(data) != row['size'] or file_digest(data) != row['sha256']:
        raise CandidateError('ArtifactMismatch', f'public file bytes differ: {name}')
    return data


def inventory(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise CandidateError('ArtifactMismatch', 'package root must be a real directory')
    result, spellings = {}, set()
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        folded = name.casefold()
        if folded in spellings:
            raise CandidateError('ArtifactMismatch', 'case-alias package path')
        spellings.add(folded)
        logical_path(name)
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise CandidateError('ArtifactMismatch', 'symlink/special package asset')
        if path.is_file():
            data = path.read_bytes()
            result[name] = {'path': name, 'sha256': file_digest(data), 'size': len(data)}
    return result


def verify_envelope(root, expected_digest):
    """Only candidate/1 pins and exact inventory, not execution admission."""
    actual = inventory(root)
    manifest = parse_json((root / 'candidate.json').read_bytes())
    fields(manifest, ('schema', 'candidate_digest', 'selector', 'generation_id', 'contract_digest',
                     'policy_digest', 'lock_digest', 'manifest_path', 'files', 'dependencies',
                     'public_symbols', 'required_cases', 'build_evidence'), 'candidate')
    if manifest['schema'] != 'madb.candidate/1' or manifest['manifest_path'] != 'candidate.json':
        raise CandidateError('FormatInvalid', 'unsupported candidate format')
    for name in ('candidate_digest', 'generation_id', 'contract_digest', 'policy_digest', 'lock_digest'):
        if not isinstance(manifest[name], str) or not DIGEST.fullmatch(manifest[name]):
            raise CandidateError('FormatInvalid', 'invalid candidate digest field')
    if candidate_digest(manifest) != expected_digest or manifest['candidate_digest'] != expected_digest:
        raise CandidateError('ArtifactMismatch', 'candidate differs from independent pin')
    selector = manifest['selector']
    fields(selector, ('route', 'profile_id', 'profile_digest', 'target', 'direction'), 'selector')
    wanted = {'route': ROUTE, 'profile_id': PROFILE, 'target': TARGET, 'direction': 'consumer-to-provider'}
    if any(selector[key] != value for key, value in wanted.items()) or not DIGEST.fullmatch(selector['profile_digest']):
        raise CandidateError('ProfileMismatch', 'not the selected finite Dart profile')
    for name in ('public_symbols', 'required_cases'):
        entries = manifest[name]
        if (not isinstance(entries, list) or not 1 <= len(entries) <= 4096
                or any(not isinstance(x, str) or not ID.fullmatch(x) for x in entries)
                or len(set(entries)) != len(entries)):
            raise CandidateError('FormatInvalid', 'invalid candidate ID set')
    if set(manifest['required_cases']) != set(CASE_IDS):
        raise CandidateError('CoverageMissing', 'finite resource case set differs from independent Lab obligations')
    files = {}
    for name in ('files', 'dependencies', 'build_evidence'):
        entries = manifest[name]
        if not isinstance(entries, list) or len(entries) > 4096 or (name != 'dependencies' and not entries):
            raise CandidateError('FormatInvalid', 'invalid candidate file set')
        seen = set()
        for row in entries:
            fields(row, ('path', 'sha256', 'size') if name == 'files' else ('path', 'sha256', 'size', 'schema'), name)
            if name != 'files' and (not isinstance(row['schema'], str) or len(row['schema']) > 512
                                     or not ID.fullmatch(row['schema'])):
                raise CandidateError('FormatInvalid', 'invalid public FileRef schema identity')
            if name == 'build_evidence' and row['schema'] != 'madb.build-evidence/1':
                raise CandidateError('FormatInvalid', 'build evidence must use its exact public format')
            path = str(logical_path(row['path']))
            if path == 'candidate.json' or path in seen:
                raise CandidateError('ArtifactMismatch', 'duplicate/self candidate file reference')
            seen.add(path)
            pin = {key: row[key] for key in ('path', 'sha256', 'size')}
            read_bound(root, pin)
            if path in files and files[path] != pin:
                raise CandidateError('ArtifactMismatch', 'inconsistent candidate references')
            files[path] = pin
    if set(actual) != set(files) | {'candidate.json'}:
        raise CandidateError('ArtifactMismatch', 'candidate inventory differs from exact public closure')
    return manifest


def profile_v2_digest(profile):
    """The published profile/2 projection, not the producer's implementation."""
    required = {'schema', 'id', 'route', 'provider', 'consumer', 'direction', 'target', 'abi', 'artifact_kind',
                'build_system', 'deployment_target', 'tools', 'sdk', 'macros', 'required_features',
                'supported_features', 'restrictions', 'defaults', 'backend_config', 'composition'}
    fields(profile, required | ({'extensions'} if 'extensions' in profile else set()), 'profile/2')
    if profile['schema'] != 'madb.profile/2':
        raise CandidateError('ProfileMismatch', 'E04 requires profile/2')
    projection = deepcopy({key: value for key, value in profile.items() if key != 'extensions'})
    fields(profile['composition'], ('id', 'semantic_digest', 'file'), 'composition reference')
    projection['composition'] = {key: profile['composition'][key] for key in ('id', 'semantic_digest')}
    fields(profile['defaults'], ('values', 'origin'), 'profile defaults')
    projection['defaults'] = deepcopy(profile['defaults']['values'])
    for name, key in (('tools', 'id'), ('macros', 'name'), ('restrictions', 'feature')):
        if len({item[key] for item in profile[name]}) != len(profile[name]):
            raise CandidateError('ProfileMismatch', 'duplicate profile set entry')
        projection[name] = sorted(profile[name], key=lambda item: item[key].encode('utf-16-be'))
    for name in ('required_features', 'supported_features'):
        if len(set(profile[name])) != len(profile[name]):
            raise CandidateError('ProfileMismatch', 'duplicate profile feature')
        projection[name] = sorted(profile[name], key=lambda item: item.encode('utf-16-be'))
    if 'core.extension-composition@1' not in profile['required_features']:
        raise CandidateError('ProfileMismatch', 'missing composition requirement')
    return semantic_digest('madb.profile/2', projection)


def verify_install(native_root):
    """Check the generated asset layout without treating it as public authority."""
    actual = inventory(native_root)
    install = parse_json((native_root / 'install.json').read_bytes())
    fields(install, ('bridge', 'native', 'identity', 'files'), 'private installed assets')
    paths = [str(logical_path(install[key])) for key in ('bridge', 'native', 'identity')]
    if len(set(path.casefold() for path in paths)) != 3 or 'install.json' in paths:
        raise CandidateError('ArtifactMismatch', 'aliased installed asset roles')
    if not isinstance(install['files'], list) or len(install['files']) != 3:
        raise CandidateError('ArtifactMismatch', 'installed asset inventory must have three pinned files')
    bound = {}
    for item in install['files']:
        fields(item, ('path', 'sha256', 'size'), 'installed asset pin')
        name = str(logical_path(item['path']))
        if name in bound or not isinstance(item['sha256'], str) or not HEX.fullmatch(item['sha256']):
            raise CandidateError('ArtifactMismatch', 'duplicate or malformed installed asset pin')
        row = dict(item, sha256='sha256:' + item['sha256'])
        read_bound(native_root, row)
        bound[name] = row
    if set(bound) != set(paths) or set(actual) != set(paths) | {'install.json'}:
        raise CandidateError('ArtifactMismatch', 'installed files differ from the exact native asset closure')
    identity = parse_json(read_bound(native_root, bound[install['identity']]))
    fields(identity, ('schema', 'bootstrap_version', 'interface_digest', 'profile_digest'), 'native identity')
    if identity['schema'] != 'madb.native-identity/1' or type(identity['bootstrap_version']) is not int or identity['bootstrap_version'] != 1:
        raise CandidateError('AbiMismatch', 'wrong original native identity format')
    if any(not isinstance(identity[key], str) or not DIGEST.fullmatch(identity[key]) for key in ('interface_digest', 'profile_digest')):
        raise CandidateError('AbiMismatch', 'malformed original native digest')
    # It is intentionally NOT compared with the outer Dart selector digest.
    return {'install': install, 'files': bound, 'identity': identity,
            'install_pin': actual['install.json']}


def verify_provenance(provenance, producer_revision):
    allowed = {'schema', 'producer_revision', 'input_digest', 'tool_digest'}
    fields(provenance, allowed | ({'provisional'} if 'provisional' in provenance else set()), 'provenance')
    if (provenance['schema'] != 'madb.native-provenance/1'
            or not REVISION.fullmatch(producer_revision)
            or provenance['producer_revision'] != producer_revision
            or provenance.get('provisional', False) is not False):
        raise CandidateError('ArtifactMismatch', 'formal clean producer identity is missing or differs')
    for name in ('input_digest', 'tool_digest'):
        if not isinstance(provenance[name], str) or not DIGEST.fullmatch(provenance[name]):
            raise CandidateError('ArtifactMismatch', 'invalid provenance digest')


def verify_build_evidence(root, manifest, contract, profile):
    """Bind this outer package's three real Build stages, never provider receipts."""
    available = {row['path']: {key: row[key] for key in ('path', 'sha256', 'size')}
                 for section in ('files', 'dependencies', 'build_evidence') for row in manifest[section]}
    tools = {tool['id']: tool for tool in profile['tools']}
    phases, tasks = {}, set()
    for reference in manifest['build_evidence']:
        if reference['schema'] != 'madb.build-evidence/1':
            raise CandidateError('FormatInvalid', 'wrong BuildEvidence reference schema')
        value = parse_json(read_bound(root, reference))
        fields(value, ('schema', 'task_id', 'task_digest', 'input_digest', 'profile_digest', 'generation_id',
                       'tool', 'phase', 'target', 'status', 'exit_code', 'outputs', 'logs'), 'BuildEvidence')
        if value['schema'] != 'madb.build-evidence/1':
            raise CandidateError('FormatInvalid', 'wrong BuildEvidence payload schema')
        for key in ('task_id', 'target'):
            if not isinstance(value[key], str) or len(value[key]) > 512 or not ID.fullmatch(value[key]):
                raise CandidateError('FormatInvalid', 'invalid BuildEvidence identity')
        for key in ('task_digest', 'input_digest', 'profile_digest', 'generation_id'):
            if not isinstance(value[key], str) or not DIGEST.fullmatch(value[key]):
                raise CandidateError('FormatInvalid', 'invalid BuildEvidence digest')
        phase = value['phase']
        if phase not in ('compile', 'link', 'run') or phase in phases or value['task_id'] in tasks:
            raise CandidateError('ArtifactMismatch', 'missing/duplicate/unsupported Dart Build stage')
        if (value['status'] != 'passed' or type(value['exit_code']) is not int or value['exit_code'] != 0
                or value['target'] != manifest['selector']['target']
                or value['profile_digest'] != manifest['selector']['profile_digest']
                or value['generation_id'] != manifest['generation_id']
                or value['input_digest'] != contract['source_digest']):
            raise CandidateError('ArtifactMismatch', 'Build receipt is unsuccessful or belongs to different source/profile/generation/target')
        fields(value['tool'], ('id', 'version', 'sha256'), 'BuildEvidence tool')
        if not isinstance(value['tool']['sha256'], str) or not DIGEST.fullmatch(value['tool']['sha256']):
            raise CandidateError('FormatInvalid', 'invalid BuildEvidence tool image digest')
        worker = tools.get('e04-python')
        if (worker is None or value['tool'] != {key: worker[key] for key in ('id', 'version', 'sha256')}
                or value['tool']['version'] != '3.14.4'):
            raise CandidateError('ArtifactMismatch', 'Build receipt tool differs from the locked finite-recipe worker')
        for collection in ('outputs', 'logs'):
            rows = value[collection]
            if not isinstance(rows, list) or len(rows) > 4096 or (collection == 'logs' and not rows):
                raise CandidateError('FormatInvalid', 'invalid BuildEvidence file collection')
            seen = set()
            for row in rows:
                fields(row, ('path', 'sha256', 'size'), 'BuildEvidence file')
                path = str(logical_path(row['path']))
                if (path in seen or not isinstance(row['sha256'], str) or not DIGEST.fullmatch(row['sha256'])
                        or type(row['size']) is not int or not 0 <= row['size'] <= 9007199254740991):
                    raise CandidateError('FormatInvalid', 'invalid/duplicate BuildEvidence file pin')
                seen.add(path)
                if collection == 'logs' or path in available:
                    if available.get(path) != row:
                        raise CandidateError('ArtifactMismatch', 'Build log/output is absent or differs from public candidate bytes')
                    read_bound(root, row)
        phases[phase] = value
        tasks.add(value['task_id'])
    if set(phases) != {'compile', 'link', 'run'}:
        raise CandidateError('ArtifactMismatch', 'new Dart package needs complete compile/link/run evidence')
    outputs = {row['path']: row for row in phases['link']['outputs']}
    for path in ('native/bridge.dylib', 'native/install.json', 'lib/src/package_pins.dart'):
        built = 'build/' + path
        if (built not in outputs or outputs[built] != available.get(built) or path not in available
                or any(outputs[built][key] != available[path][key] for key in ('sha256', 'size'))):
            raise CandidateError('ArtifactMismatch', 'linked bridge/install/pins output does not bind the actual package')
        read_bound(root, available[path])
    for phase, value in phases.items():
        log, commands = 'logs/' + phase + '.json', 'build/' + phase + '.commands.json'
        if ({row['path']: row for row in value['logs']} != {log: available.get(log)}
                or log not in available or commands not in available
                or any(available[log][key] != available[commands][key] for key in ('sha256', 'size'))):
            raise CandidateError('ArtifactMismatch', 'stage log and actual commands are not the same candidate-bound bytes')
        read_bound(root, available[commands])
    return phases


def _unique(items, key, label):
    keys = [key(item) for item in items]
    if len(set(keys)) != len(keys):
        raise CandidateError('ArtifactMismatch', 'duplicate ' + label)
    return sorted(items, key=key)


def composition_digest(value):
    """ADR-0018's published collection ordering; no behavior oracle is imported."""
    fields(value, ('schema', 'id', 'recipe', 'selection', 'packages', 'components', 'assets',
                   'dependencies', 'responsibilities'), 'composition')
    if value['schema'] != 'madb.composition/1':
        raise CandidateError('FormatInvalid', 'wrong composition format')
    result = deepcopy(value)
    text = lambda x: x.encode('utf-16-be')
    for name in ('packages', 'components', 'assets'):
        result[name] = _unique(result[name], lambda row: text(row['id']), name)
    for package in result['packages']:
        fields(package, ('id', 'version', 'manifest', 'source', 'source_digest'), 'composition package')
        fields(package['source'], ('kind', 'files'), 'composition package source')
        if package['source']['kind'] != 'file-set':
            raise CandidateError('FormatInvalid', 'wrong package source kind')
        package['source']['files'] = _unique(package['source']['files'], lambda row: text(row['path']), 'package file')
        if semantic_digest('madb.source/1', package['source']['files']) != package['source_digest']:
            raise CandidateError('ArtifactMismatch', 'package source digest differs from complete declared bytes')
    for asset in result['assets']:
        fields(asset, ('id', 'package', 'source'), 'composition asset')
        source = asset['source']
        if source['kind'] == 'source':
            fields(source, ('kind', 'files'), 'source asset')
            source['files'] = _unique(source['files'], lambda row: text(row['path']), 'source asset file')
        elif source['kind'] == 'generated':
            fields(source, ('kind', 'producer', 'output_slot', 'paths'), 'generated asset')
            source['paths'] = _unique(source['paths'], text, 'generated output path')
        else:
            raise CandidateError('FormatInvalid', 'unknown asset source kind')
    result['dependencies'] = _unique(result['dependencies'], lambda row: tuple(text(row[k]) for k in ('from', 'to', 'scope')), 'dependency')
    result['responsibilities'] = _unique(result['responsibilities'],
        lambda row: (text(row['boundary']), canonical_json(row['subject']), text(row['stage']), canonical_json(row['scope'])),
        'declared responsibility')
    return semantic_digest('madb.composition/1', result)


def verify_composition(root, profile, lock):
    reference = profile['composition']
    verify_reference(root, reference['file'], 'madb.composition/1', 'composition.json')
    composition = read_json(root / 'composition.json')
    expected_selection = {'profile_id': profile['id'], **{k: profile[k] for k in ('route', 'direction', 'target')}}
    if (composition['id'] != reference['id'] or composition['selection'] != expected_selection
            or composition_digest(composition) != reference['semantic_digest']):
        raise CandidateError('ProfileMismatch', 'composition identity/selection differs')
    packages = {p['id']: p for p in composition['packages']}
    if packages.get('org.madb.dart-ffi', {}).get('version') != '0.1.0':
        raise CandidateError('ProfileMismatch', 'approved Dart extension package/version is missing')
    for package in packages.values():
        base = root / 'packages' / package['id'] / package['version']
        expected_files = {}
        for row in package['source']['files']:
            fields(row, ('path', 'sha256', 'size'), 'package source file')
            read_bound(base, row)
            expected_files[row['path']] = row
        if inventory(base) != expected_files:
            raise CandidateError('ArtifactMismatch', 'extension package source closure is incomplete or has extra bytes')
        manifest_ref = package['manifest']
        verify_reference(base, manifest_ref, 'madb.extension/1')
        manifest = parse_json(read_bound(base, manifest_ref))
        if manifest.get('id') != package['id'] or manifest.get('version') != package['version']:
            raise CandidateError('ArtifactMismatch', 'extension manifest differs from declared source package')
    locked = {row['id']: row for row in lock['components']}
    if len(locked) != len(lock['components']):
        raise CandidateError('ArtifactMismatch', 'duplicate locked component')
    for component in composition['components']:
        fields(component, ('id', 'version', 'sha256'), 'composition component')
        if locked.get(component['id']) != component:
            raise CandidateError('ArtifactMismatch', 'composition component image differs from lock')
    return composition


def verify_candidate(root, expected_digest, producer_revision):
    """Finite E04 package admission, keeping original C identity independently bound."""
    root = Path(root).resolve(strict=True)
    manifest = verify_envelope(root, expected_digest)
    profile = read_json(root / 'profile.json')
    selector = manifest['selector']
    if (profile_v2_digest(profile) != selector['profile_digest'] or profile['id'] != selector['profile_id']
            or any(profile[key] != selector[key] for key in ('route', 'target', 'direction'))
            or profile['provider'] != {'language': 'c', 'runtime': 'native'}
            or profile['consumer'] != {'language': 'dart', 'runtime': 'dart-native'}):
        raise CandidateError('ProfileMismatch', 'outer Dart profile identity differs')
    provenance = read_json(root / 'provenance.json')
    verify_provenance(provenance, producer_revision)
    contract = read_json(root / 'contract.json')
    if (contract.get('schema') != 'madb.contract-ir/1' or contract.get('selector') != selector
            or contract.get('source_digest') != provenance['input_digest']
            or contract.get('structure_digest') != manifest['contract_digest']
            or contract.get('policy_digest') != manifest['policy_digest']):
        raise CandidateError('ArtifactMismatch', 'outer contract and candidate identities differ')
    verify_contract_digests(contract)
    verify_layout_sources(contract, profile)
    if not (set(contract['required_features']) | set(profile['required_features'])) <= set(profile['supported_features']):
        raise CandidateError('ProfileMismatch', 'selected profile lacks required contract/composition semantics')
    build_evidence = verify_build_evidence(root, manifest, contract, profile)
    if sorted(symbol['public_id'] for symbol in contract['symbols']) != sorted(manifest['public_symbols']):
        raise CandidateError('ArtifactMismatch', 'Dart public symbols differ from contract')
    lock = read_json(root / 'madb.lock')
    if lock.get('schema') != 'madb.lock/1' or file_digest((root / 'madb.lock').read_bytes()) != manifest['lock_digest']:
        raise CandidateError('ArtifactMismatch', 'outer lock identity differs')
    for name in ('inputs', 'schemas', 'profiles', 'components', 'tools'):
        if not isinstance(lock.get(name), list) or not 1 <= len(lock[name]) <= 4096:
            raise CandidateError('FormatInvalid', 'missing bounded locked ' + name)
    inputs = _unique(lock['inputs'], lambda row: row['path'].encode('utf-16-be'), 'source input')
    public_files = {row['path']: row for row in manifest['files']}
    for row in inputs:
        fields(row, ('path', 'sha256', 'size'), 'locked source input')
        logical_path(row['path'])
        if not DIGEST.fullmatch(row['sha256']) or type(row['size']) is not int or row['size'] < 0:
            raise CandidateError('ArtifactMismatch', 'invalid source input pin')
        if row['path'] in public_files and row != public_files[row['path']]:
            raise CandidateError('ArtifactMismatch', 'available frozen source bytes differ from public candidate')
    if semantic_digest('madb.source/1', inputs) != contract['source_digest']:
        raise CandidateError('ArtifactMismatch', 'outer source input digest differs')
    selected = [row for row in lock['profiles'] if row['id'] == profile['id']]
    if len(selected) != 1 or selected[0]['semantic_digest'] != selector['profile_digest']:
        raise CandidateError('ProfileMismatch', 'lock does not select exactly the Dart profile')
    verify_reference(root, selected[0]['file'], 'madb.profile/2', 'profile.json')
    tools = {row['id']: row for row in lock['tools']}
    if len(tools) != len(lock['tools']) or any(tools.get(row['id']) != row for row in profile['tools']):
        raise CandidateError('ArtifactMismatch', 'profile tools differ from public lock')
    verify_reference(root, profile['sdk'], profile['sdk']['schema'])
    project = read_json(root / 'project.json')
    if project.get('schema') != 'madb.project/1' or project_digest(project) != lock['project_digest']:
        raise CandidateError('ArtifactMismatch', 'project digest differs from lock')
    boundaries = [b for b in project['boundaries'] if b['id'] == contract['boundary_id']]
    if len(boundaries) != 1 or any(boundaries[0][k] != selector[k] for k in ('route', 'target', 'direction')):
        raise CandidateError('ProfileMismatch', 'Dart contract boundary differs from project')
    verify_reference(root, boundaries[0]['profile'], 'madb.profile/2', 'profile.json')
    composition = verify_composition(root, profile, lock)
    provider = verify_native_candidate(root / 'provider')
    if provider['provenance'].get('provisional', False):
        raise CandidateError('ArtifactMismatch', 'original C candidate is provisional')
    native = verify_install(root / 'native')
    if ((root / 'native' / native['install']['native']).read_bytes() != (root / 'provider/lib/libmadb_engine.dylib').read_bytes()
            or (root / 'native' / native['install']['identity']).read_bytes() != (root / 'provider/identity.json').read_bytes()):
        raise CandidateError('ArtifactMismatch', 'loaded native bytes/identity differ from complete original C candidate')
    provider_pin = file_digest((root / 'provider/candidate.json').read_bytes())
    if not any(row['sha256'] == provider_pin for row in inputs):
        raise CandidateError('ArtifactMismatch', 'outer frozen source does not bind the original public C candidate')
    for name in ('pubspec.yaml', 'pubspec.lock', 'lib/madb_dart_ffi.dart', 'lib/src/package_pins.dart'):
        if name not in public_files:
            raise CandidateError('ArtifactMismatch', 'ordinary package lacks ' + name)
    return {'root': root, 'manifest': manifest, 'profile': profile, 'provenance': provenance,
            'contract': contract, 'lock': lock, 'composition': composition,
            'provider': provider, 'native': native, 'build_evidence': build_evidence}
