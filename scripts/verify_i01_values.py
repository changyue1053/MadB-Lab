"""Consume the initial I01 SDK through public Candidate/Case/Report v1 only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'harness'))
from candidate import CandidateError, canonical_json, file_digest, parse_json, read_json, verify_candidate
from i01_values_reports import Reports, CASE_NAMES, required_ids
from l02_reports import CommandFailure, ObservationFailure
from verify_l02 import (Commands, reference, inventory, lab_identity, native_target,
                        compiler_configuration, dependency_inputs, sdk_binding)
from verify_l02_values import public_header_probe

GROUP = 'rust-c-values'
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
REVISION = re.compile(r'[0-9a-f]{40}\Z')
SOURCE = ROOT / 'consumers/c/i01_values.c'
# These byte expectations are Lab-owned; neither the producer nor C output
# constructs this table. The C program also checks every result before printing.
EXPECTED = (
    ('ascii', 7, b'x'), ('whitespace', 7, b''),
    ('unicode', -7, bytes.fromhex('e6b8a9e5baa6')), ('empty', 0, b''),
    ('nul', 7, b'a\0b'), ('supplementary', 7, bytes.fromhex('f09f8ca1')),
    ('capacity-ascii', 7, b'x' * 64),
    ('capacity-unicode', 7, bytes.fromhex('f09f8ca1') * 16),
    ('minimum', -2147483648, b'x'), ('maximum', 2147483647, b'x'),
    ('non-whitespace', 7, bytes.fromhex('e2808b')),
)


def check_selection(candidate, pin, producer, target):
    manifest, provenance = candidate['manifest'], candidate['provenance']
    if (not DIGEST.fullmatch(pin) or provenance.get('provisional', False)
            or provenance['producer_revision'] != producer or manifest['candidate_digest'] != pin):
        raise CandidateError('ArtifactMismatch', 'candidate differs from the independent clean producer/pin')
    selector = manifest['selector']
    if (target != 'aarch64-apple-darwin' or selector['target'] != target
            or selector['profile_id'] != 'i01-native-values-macos-arm64-0-1-1' or selector['route'] != 'RUST-C-ABI'
            or selector['direction'] != 'consumer-to-provider'):
        raise CandidateError('ProfileMismatch', 'only the initial I01 macOS arm64 profile is in scope')
    if sorted(manifest['required_cases']) != sorted(required_ids(GROUP)):
        raise CandidateError('CoverageMissing', 'candidate must require exactly both independent I01 cases')
    files = {item['path'] for item in manifest['files']}
    if not {'include/madb_value_abi_v1.h', 'include/reading_demo_native.h',
            'include/reading_demo.h', 'lib/libreading_demo.dylib'} <= files:
        raise CandidateError('ArtifactMismatch', 'initial public SDK files are missing')
    contract = candidate['contract']
    if (contract['sdk_namespace'] != 'reading_demo'
            or {s['shape']['link_name'] for s in contract['symbols']}
            != {'reading_demo_bootstrap_v1', 'reading_demo_raw_normalize'}):
        raise CandidateError('AbiMismatch', 'candidate is not the initial Reading/normalize SDK')


def verify_author(candidate_root):
    expected = reference(ROOT / 'cases/i01/rust-c-values/author.rs')
    lock = read_json(candidate_root / 'madb.lock')
    matches = [item for item in lock['inputs'] if item['path'] == 'author.rs']
    if len(matches) != 1 or {key: matches[0][key] for key in expected} != expected:
        raise CandidateError('ArtifactMismatch', 'locked author differs from the fixed initial public author bytes')
    return {'fixture': 'cases/i01/rust-c-values/author.rs', 'locked_path': 'author.rs', **expected}


def inspect_output(text, mode, library, identity):
    if mode not in CASE_NAMES[GROUP]:
        raise ValueError('unknown independent I01 case')
    rows = [parse_json(line.encode()) for line in text.splitlines() if line]
    if len(rows) != (2 if mode == 'bootstrap' else 2 + len(EXPECTED)) or any(not isinstance(r, dict) for r in rows):
        raise ValueError('missing or extra actual target observations')
    binding, end = rows[0], rows[-1]
    if (set(binding) != {'event', 'image', 'identity', 'pid'}
            or any(type(binding[k]) is not str for k in ('event', 'image', 'identity'))
            or type(binding['pid']) is not int):
        raise ValueError('loaded image observation is incomplete')
    expected_identity = identity['interface_digest'][7:] + identity['profile_digest'][7:]
    if (binding['event'] != 'binding' or Path(binding['image']).resolve() != library.resolve()
            or binding['identity'] != expected_identity or binding['pid'] <= 0):
        raise ObservationFailure('actual loaded image/bootstrap differs from pinned candidate')
    if (set(end) != {'result', 'mode', 'checks', 'vectors', 'scope'}
            or type(end['checks']) is not int or type(end['vectors']) is not int
            or any(type(end[k]) is not str for k in ('result', 'mode', 'scope'))):
        raise ValueError('terminal result is incomplete')
    if (end['result'] != 'passed' or end['mode'] != mode or end['checks'] <= 0
            or end['vectors'] != (0 if mode == 'bootstrap' else len(EXPECTED))
            or end['scope'] != 'i01-initial-native-values'):
        raise ObservationFailure('terminal result contradicts the fixed independent scope')
    for row, (name, number, data) in zip(rows[1:-1], EXPECTED, strict=mode == 'ordinary'):
        expected = {'event': 'value', 'id': name, 'value': number, 'hex': data.hex(),
                    'input_preserved': True, 'tail_zero': True, 'kind': 0, 'status': 0, 'domain': 0, 'code': 0}
        if set(row) != set(expected) or any(type(row[k]) is not type(v) for k, v in expected.items()):
            raise ValueError('ordinary observation has missing or ill-typed fields')
        if row != expected:
            raise ObservationFailure('ordinary result differs from the independent expected bytes: ' + name)
    return rows


def compile_consumer(commands, clang, include, library, executable):
    argv = [clang, *commands.c_flags, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', include]
    depfile = executable.with_suffix('.d')
    commands.run([*argv, '-M', '-MT', 'madb-i01-values', '-MF', depfile, SOURCE], timeout=120)
    inputs = dependency_inputs(depfile, 'madb-i01-values', [SOURCE], [include, *commands.system_roots])
    commands.run([*argv, SOURCE, library, '-Wl,-rpath,' + str(library.parent), '-o', executable], timeout=120)
    if any(reference(Path(path)) != value for path, value in inputs.items()):
        raise ValueError('actual compiler inputs changed')
    commands.compilations.append({'executable': executable.relative_to(commands.output).as_posix(),
                                 'depfile': {'path': depfile.relative_to(commands.output).as_posix(), **reference(depfile)},
                                 'inputs': inputs})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--candidate-digest', required=True)
    parser.add_argument('--producer-revision', required=True)
    parser.add_argument('--lab-revision', required=True)
    parser.add_argument('--clang', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    args.output, args.candidate = args.output.resolve(), args.candidate.resolve()
    if any(args.output.is_relative_to(p) or p.is_relative_to(args.output) for p in (ROOT, args.candidate)):
        parser.error('output overlaps Lab source or candidate input')
    args.output.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.output)
    report = {'scope': 'I01 initial recipe independent SDK bootstrap and ordinary normalize only',
              'result': 'failed', 'full_i01_acceptance': False, 'preflight': 'started',
              'compile': 'not-run', 'runtime': 'not-run', 'observations': [],
              'limits': ['No CLI workflow, IDE, full L02, numeric allocation, new platform or publication acceptance.']}
    standard = None; failure = None
    try:
        if platform.python_version() != (ROOT / '.python-version').read_text().strip():
            raise ValueError('use the pinned Lab Python')
        if not REVISION.fullmatch(args.producer_revision):
            raise ValueError('full clean producer revision required')
        lab_files = lab_identity(ROOT, args.lab_revision)
        report['lab'] = {'revision': args.lab_revision, 'files': lab_files,
                         'source_digest': file_digest(canonical_json(lab_files))}
        candidate = verify_candidate(args.candidate)
        target = native_target(platform.system(), platform.machine(), platform.libc_ver()[0])
        check_selection(candidate, args.candidate_digest, args.producer_revision, target)
        original = inventory(args.candidate)
        install = args.output / 'install'; shutil.copytree(args.candidate, install)
        verify_candidate(install)
        report['author'] = verify_author(install)
        clang = (args.clang or Path(commands.run(['xcrun', '--find', 'clang'])[0].strip())).resolve(strict=True)
        sdk = Path(commands.run(['xcrun', '--sdk', 'macosx', '--show-sdk-path'])[0].strip()).resolve(strict=True)
        resources = Path(commands.run([clang, '-print-resource-dir'])[0].strip()).resolve(strict=True)
        commands.c_flags, compiler = compiler_configuration(target, sdk, resources)
        commands.system_roots = [sdk, resources]
        version = commands.run([clang, '--version'])[0]
        tool = reference(clang)
        matches = [t for t in candidate['profile']['tools'] if t['id'] == 'c05-clang']
        if len(matches) != 1 or matches[0]['sha256'] != tool['sha256']:
            raise CandidateError('ProfileMismatch', 'actual compiler differs from public profile')
        receipt = read_json(install / 'toolchain.json')
        if receipt['compiler'] != compiler:
            raise CandidateError('ProfileMismatch', 'compiler target/options differ from public receipt')
        sdk_inputs = sdk_binding(receipt, sdk, resources)
        environment = [{'id': 'c05-clang', 'version': version.splitlines()[0], 'sha256': tool['sha256'],
                        'host': target, 'target': target, 'source': str(clang),
                        'arguments': [*commands.c_flags, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror']},
                       {'id': 'lab-python', 'version': platform.python_version(),
                        'sha256': reference(Path(sys.executable).resolve())['sha256'], 'host': target, 'target': target,
                        'source': str(Path(sys.executable).resolve()), 'arguments': ['-B']}]
        report.update(environment=environment, sdk_inputs=sdk_inputs,
                      candidate={key: candidate[key] for key in ('manifest', 'identity', 'provenance')})
        standard = Reports(ROOT, args.output, {GROUP: candidate}, args.lab_revision, environment)
        report['case_inputs'] = standard.index
        probe = public_header_probe(commands, clang, install / 'include', args.output)
        report['public_header_probe'] = probe; report['preflight'] = 'passed'; report['compile'] = 'started'
        library = install / 'lib/libreading_demo.dylib'; executable = args.output / 'consumer'
        compile_consumer(commands, clang, install / 'include', library, executable)
        report['executable'] = reference(executable); report['compile'] = 'passed'; report['runtime'] = 'started'
        identity = candidate['identity']; expected_identity = identity['interface_digest'][7:] + identity['profile_digest'][7:]
        for name in CASE_NAMES[GROUP]:
            timeout = standard.begin(GROUP, name); start = time.monotonic_ns(); log_start = len(commands.logs)
            try:
                text, log = commands.run([executable, name, expected_identity], timeout=timeout)
            except CommandFailure as error:
                standard.note_target(error.path.relative_to(args.output).as_posix()); raise
            standard.note_target(log)
            if read_json(args.output / log)['stdout'] != text:
                raise ValueError('raw target stdout differs from observed output')
            observed = inspect_output(text, name, library, identity)
            standard.finish(start, time.monotonic_ns(), commands.logs[log_start:], observed)
            report['observations'].append({'case': name, 'log': log, 'rows': observed})
        if lab_identity(ROOT, args.lab_revision) != lab_files:
            raise ValueError('Lab source changed during execution')
        for item in environment:
            if reference(Path(item['source']))['sha256'] != item['sha256']:
                raise ValueError('actual environment image changed')
        for item in commands.logs:
            if reference(args.output / item['path']) != {k: item[k] for k in ('sha256', 'size')}:
                raise ValueError('raw command log changed')
        if reference(executable) != report['executable']:
            raise ValueError('consumer executable changed')
        for compilation in commands.compilations:
            if any(reference(Path(p)) != v for p, v in compilation['inputs'].items()):
                raise ValueError('actual compile input changed')
            dep = compilation['depfile']
            if reference(args.output / dep['path']) != {k: dep[k] for k in ('sha256', 'size')}:
                raise ValueError('compiler dependency evidence changed')
        if any(reference(Path(p)) != v for p, v in probe['inputs'].items()):
            raise ValueError('public header dependency changed')
        for key in ('source', 'depfile'):
            ref = probe[key]
            if reference(args.output / ref['path']) != {k: ref[k] for k in ('sha256', 'size')}:
                raise ValueError('public header probe changed')
        if sdk_binding(receipt, sdk, resources) != sdk_inputs:
            raise ValueError('SDK input changed')
        for path in (install, args.candidate):
            verify_candidate(path)
            if inventory(path) != original:
                raise ValueError('candidate changed during consumption')
        sources = ['consumers/c/i01_values.c', 'consumers/c/i01_values.md', 'scripts/verify_i01_values.py',
                   'scripts/verify_l02.py', 'scripts/verify_l02_values.py', 'harness/i01_values_reports.py',
                   'harness/l02_reports.py', 'harness/l02_values_reports.py', 'harness/candidate.py', 'harness/check_cases.py']
        sources += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / 'cases/i01').rglob('*')) if p.is_file()]
        with tarfile.open(args.output / 'consumer-sources.tar', 'w') as archive:
            for name in sorted(sources): archive.add(ROOT / name, arcname=name)
        report['source_archive'] = reference(args.output / 'consumer-sources.tar')
        standard.verify(); report['runtime'] = 'passed'; report['result'] = 'passed'
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        failure = error; report['error'] = str(error)
        for stage in ('preflight', 'compile', 'runtime'):
            if report[stage] == 'started': report[stage] = 'failed'
    report['logs'], report['compilations'] = commands.logs, commands.compilations
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if standard is not None: standard.write(report, failure)
    print(json.dumps({'result': report['result'], 'report': str(args.output / 'report.json'), 'error': report.get('error')}))
    return 0 if report['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
