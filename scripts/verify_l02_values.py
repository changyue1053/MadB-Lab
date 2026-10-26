"""Independent C11 consumers for frozen bounded-value SDK candidates.

Only public candidate bytes and Lab-owned author/oracle fixtures are consumed.
No producer generator, private crate or rule engine is imported.
"""
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
from l02_reports import CommandFailure, ObservationFailure
from l02_values_reports import Reports, GROUPS, CASE_NAMES, required_ids
from verify_l02 import (Commands, reference, inventory, lab_identity, native_target, compiler_configuration,
                        dependency_inputs, sdk_binding, linux_sdk_binding)

DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
REVISION = re.compile(r'[0-9a-f]{40}\Z')
SOURCES = {'normal': ROOT / 'consumers/c/l02_values.c', 'aux': ROOT / 'consumers/c/l02_values_aux.c'}
METHODS = {'author-0': ('normalize',), 'author-1': ('normalize', 'offset'),
           'author-2': ('normalize', 'offset'), 'author-3': ('canonicalize', 'offset'),
           'author-4': ('canonicalize',), 'aux-grow': ('grow',), 'aux-panic': ('explode',)}


def parse_pins(values):
    pins = {}
    for entry in values:
        group, separator, digest = entry.partition('=')
        if not separator or group not in GROUPS or group in pins or not DIGEST.fullmatch(digest):
            raise ValueError('one independently supplied group=sha256:... pin per fixed candidate is required')
        pins[group] = digest
    if set(pins) != set(GROUPS): raise ValueError('all five business and two auxiliary candidates must be pinned')
    return pins


def check_selection(group, candidate, pin, producer, target):
    manifest, provenance = candidate['manifest'], candidate['provenance']
    selector = manifest['selector']
    if (provenance.get('provisional', False) or provenance['producer_revision'] != producer
            or manifest['candidate_digest'] != pin):
        raise CandidateError('ArtifactMismatch', 'candidate differs from exact clean producer and independent pin')
    if (selector['profile_id'] != 'l02-native-values-' + group + '-' + target or selector['target'] != target
            or selector['route'] != 'RUST-C-ABI' or selector['direction'] != 'consumer-to-provider'):
        raise CandidateError('ProfileMismatch', 'candidate is not the fixed value author and actual host target')
    files = {item['path'] for item in manifest['files']}
    if not {'include/madb_value_abi_v1.h', 'include/reading_demo_native.h', 'include/reading_demo.h'} <= files:
        raise CandidateError('ArtifactMismatch', 'candidate lacks ordinary or physical value headers')
    if set(manifest['required_cases']) != set(required_ids(group)):
        raise CandidateError('CoverageMissing', 'required cases differ from the independent fixed obligations')
    if candidate['contract']['sdk_namespace'] != 'reading_demo':
        raise CandidateError('ArtifactMismatch', 'candidate is not the independent Reading business')


def verify_author(root, group):
    expected = reference(ROOT / 'fixtures/l02/native-values' / (group + '.rs'))
    lock = read_json(root / 'madb.lock')
    matching = [item for item in lock['inputs'] if item['path'] == 'author.rs']
    if len(matching) != 1 or {k: matching[0][k] for k in expected} != expected:
        raise CandidateError('ArtifactMismatch', 'locked natural Rust author differs from independent change fixture')
    return {'fixture': 'fixtures/l02/native-values/' + group + '.rs', 'locked_path': 'author.rs', **expected}


def expected_exports(group):
    return {'reading_demo_bootstrap_v1'} | {'reading_demo_raw_' + name for name in METHODS[group]}


def inspect_exports(text, group, contract):
    actual = {line.split()[-1].removeprefix('_') for line in text.splitlines() if line.split()}
    if actual != expected_exports(group):
        raise CandidateError('ArtifactMismatch', 'exact dynamic native export set differs from the source version')
    if {item['shape']['link_name'] for item in contract['symbols']} != expected_exports(group):
        raise CandidateError('AbiMismatch', 'logical contract links differ from independent expected native links')
    return sorted(actual)


def inspect_output(text, group, mode, library, identity):
    rows = [parse_json(line.encode()) for line in text.splitlines() if line]
    stub = mode == 'helper-protocol'
    if len(rows) != (1 if stub else 2) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('missing or extra actual target evidence rows')
    end = rows[-1]
    expected_keys = {'result', 'mode', 'author', 'checks', 'helper_vectors', 'scope'}
    if (set(end) != expected_keys or type(end['author']) is not int or type(end['checks']) is not int or type(end['helper_vectors']) is not int
            or any(not isinstance(end[key], str) for key in ('result', 'mode', 'scope'))):
        raise ValueError('terminal evidence shape/type is incomplete')
    author = GROUPS.index(group)
    vectors = (24 if group in ('author-1', 'author-2', 'author-3') else 22) if stub else 0
    if (end['result'] != 'passed' or end['mode'] != mode or end['author'] != author or end['checks'] <= 0
            or end['helper_vectors'] != vectors or end['scope'] != ('helper-only' if stub else 'native-sdk')):
        raise ObservationFailure('complete terminal evidence contradicts independent scope or vector count')
    if not stub:
        row = rows[0]
        if set(row) != {'event', 'image', 'identity', 'pid'} or not isinstance(row['image'], str) or type(row['pid']) is not int or not isinstance(row['identity'], str) or not isinstance(row['event'], str):
            raise ValueError('actual loaded image evidence is missing/malformed')
        expected = identity['interface_digest'][7:] + identity['profile_digest'][7:]
        if (row['event'] != 'binding' or Path(row['image']).resolve() != library.resolve() or row['pid'] <= 0 or row['identity'] != expected):
            raise ObservationFailure('target loaded a different candidate image or bootstrap identity')
    return rows


def public_header_probe(commands, clang, include, directory):
    source = directory / 'public-headers.c'
    headers = ('madb_value_abi_v1.h', 'reading_demo_native.h', 'reading_demo.h')
    source.write_text(''.join('#include "' + name + '"\n' for name in headers))
    depfile = directory / 'public-headers.d'
    before = reference(source)
    commands.run([clang, *commands.c_flags, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', include,
                  '-M', '-MT', 'madb-values-public', '-MF', depfile, source], timeout=120)
    inputs = dependency_inputs(depfile, 'madb-values-public', [source, *(include / name for name in headers)], [include, *commands.system_roots])
    if reference(source) != before: raise ValueError('header probe source changed')
    dependencies = {p: r for p, r in inputs.items() if Path(p) != source.resolve() and not Path(p).is_relative_to(include.resolve())}
    return {'source': {'path': source.relative_to(commands.output).as_posix(), **before},
            'depfile': {'path': depfile.relative_to(commands.output).as_posix(), **reference(depfile)},
            'inputs': inputs, 'system_dependencies': dependencies}


def compile_consumer(commands, clang, include, library, executable, group, stub=False, mismatch=False):
    if mismatch and (stub or group not in ('author-0', 'author-2')):
        raise ValueError('mixed consumer requires the shared ordinary author-0/author-2 entry')
    auxiliary = group.startswith('aux-')
    source = SOURCES['aux' if auxiliary else 'normal']
    flags = ['-DMADB_LAB_AUX=' + str(GROUPS.index(group) - 4)] if auxiliary else ['-DMADB_LAB_AUTHOR=' + str(GROUPS.index(group))]
    if stub: flags += ['-DMADB_LAB_STUB=1']
    if mismatch: flags += ['-DMADB_LAB_MISMATCH_ONLY=1']
    argv = [clang, *commands.c_flags, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', *flags, '-I', include]
    depfile = executable.with_suffix('.d')
    commands.run([*argv, '-M', '-MT', 'madb-values', '-MF', depfile, source], timeout=120)
    inputs = dependency_inputs(depfile, 'madb-values', [source], [include, *commands.system_roots])
    argv += [source]
    if not stub:
        argv += [library, '-Wl,-rpath,' + str(library.parent)]
        if platform.system() != 'Darwin': argv += ['-ldl']
    argv += ['-o', executable]
    commands.run(argv, timeout=120)
    if any(reference(Path(path)) != value for path, value in inputs.items()):
        raise ValueError('actual compile inputs changed')
    commands.compilations.append({'executable': executable.relative_to(commands.output).as_posix(),
                                 'depfile': {'path': depfile.relative_to(commands.output).as_posix(), **reference(depfile)}, 'inputs': inputs})


def expect_rejection(commands, argv, symbol, stage):
    try:
        commands.run(argv, timeout=120)
    except CommandFailure as error:
        value = error.value
        if value.get('timeout') is not False or value.get('exit_code') != 1:
            raise
        stderr = value.get('stderr', '')
        if stage == 'declaration':
            matched = re.search(r"undeclared identifier ['\"]" + re.escape(symbol) + r"['\"]", stderr)
        else:
            matched = ('undefined reference' in stderr.lower() or 'undefined symbols' in stderr.lower()) and re.search(r'(?<![A-Za-z0-9_])_?' + re.escape(symbol) + r'\b', stderr)
        if not matched or any(text in stderr.lower() for text in ('fatal error:', 'segmentation fault', 'unable to execute', 'killed by signal')):
            raise ObservationFailure('rejection did not identify the independently expected missing API: ' + symbol) from error
        return {'symbol': symbol, 'stage': stage, 'exit_code': 1, 'log': error.path.relative_to(commands.output).as_posix()}
    raise ObservationFailure('removed or unavailable API unexpectedly compiled/linked: ' + symbol)


def rejected_declaration(commands, clang, include, directory, method):
    symbol = 'reading_demo_' + method
    source = directory / ('absent-' + method + '.c')
    source.write_text('#include "reading_demo.h"\nint main(void) { (void)&' + symbol + '; return 0; }\n')
    return expect_rejection(commands, [clang, *commands.c_flags, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', include, '-fsyntax-only', source], symbol, 'declaration')


def rejected_link(commands, clang, include, library, directory, method):
    symbol = 'reading_demo_raw_' + method
    source = directory / ('missing-' + method + '.c')
    extra_type = ', int32_t' if method == 'offset' else ''
    extra_arg = ', 1' if method == 'offset' else ''
    source.write_text('#include "reading_demo_native.h"\nextern MadbValueStatus ' + symbol + '(const reading_demo_Reading *' + extra_type + ', reading_demo_Reading *, MadbValueError *);\nint main(void) { reading_demo_Reading in={0}, out={0}; MadbValueError error={0}; return (int)' + symbol + '(&in' + extra_arg + ', &out, &error); }\n')
    executable = directory / ('must-not-link-' + method)
    return expect_rejection(commands, [clang, *commands.c_flags, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', include, source, library, '-o', executable], symbol, 'link')


def run_target(commands, standard, argv):
    try:
        text, log = commands.run(argv)
    except CommandFailure as error:
        standard.note_target(error.path.relative_to(commands.output).as_posix())
        raise
    standard.note_target(log)
    return text, log


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--candidate-digest', action='append', required=True)
    parser.add_argument('--producer-revision', required=True)
    parser.add_argument('--lab-revision', required=True)
    parser.add_argument('--clang', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    args.output, args.candidates = args.output.resolve(), args.candidates.resolve()
    if any(args.output.is_relative_to(p) or p.is_relative_to(args.output) for p in (ROOT, args.candidates)):
        parser.error('output overlaps source or candidate inputs')
    args.output.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.output)
    report = {'scope': 'L02 bounded-value second-business candidates; five versions and two auxiliary authors',
              'result': 'failed', 'full_l02_acceptance': False, 'preflight': 'started', 'compile': 'not_run', 'runtime': 'not_run',
              'observations': [], 'executables': {}, 'public_header_probes': {},
              'limits': ['helper-provider vectors prove inline protocol only, not SDK allocation/author counts',
                         'try_reserve failure and allocator cleanup require separately bound generated-shim evidence',
                         'QEMU is not physical x86 performance certification; no threshold is invented',
                         'no C++/async/resource/general-Rust/publication claim']}
    standard = None; failure = None
    try:
        if platform.python_version() != (ROOT / '.python-version').read_text().strip(): raise ValueError('use pinned Lab Python')
        if not REVISION.fullmatch(args.producer_revision): raise ValueError('full clean producer revision required')
        pins = parse_pins(args.candidate_digest)
        lab_files = lab_identity(ROOT, args.lab_revision)
        report['lab'] = {'revision': args.lab_revision, 'files': lab_files, 'source_digest': file_digest(canonical_json(lab_files))}
        target = native_target(platform.system(), platform.machine(), platform.libc_ver()[0])
        report['environment'] = {'target': target, 'platform': platform.platform(), 'python': platform.python_version()}
        if target == 'aarch64-apple-darwin':
            clang = args.clang or Path(commands.run(['xcrun', '--find', 'clang'])[0].strip())
            nm = Path(commands.run(['xcrun', '--find', 'nm'])[0].strip()).resolve(strict=True)
            sdk = Path(commands.run(['xcrun', '--sdk', 'macosx', '--show-sdk-path'])[0].strip()).resolve(strict=True)
        else:
            clang = args.clang or Path('/usr/bin/clang'); sdk = None
            inspector = shutil.which('llvm-nm') or shutil.which('nm')
            if inspector is None: raise ValueError('native symbol inspector missing')
            nm = Path(inspector).resolve(strict=True)
        clang = clang.resolve(strict=True); resources = Path(commands.run([clang, '-print-resource-dir'])[0].strip()).resolve(strict=True)
        commands.c_flags, compiler = compiler_configuration(target, sdk, resources)
        commands.system_roots = [sdk, resources] if sdk else [Path('/usr/include').resolve(strict=True), resources]
        version = commands.run([clang, '--version'])[0]
        report['tools'] = {'clang': {'path': str(clang), **reference(clang), 'version': version},
                           'nm': {'path': str(nm), **reference(nm), 'version': commands.run([nm, '--version'])[0]}}
        candidates, originals, installs, toolchains, receipts = {}, {}, {}, {}, {}
        for group in GROUPS:
            path = args.candidates / group; value = verify_candidate(path)
            check_selection(group, value, pins[group], args.producer_revision, target)
            for tool_name in ('clang', 'nm'):
                tools = [item for item in value['profile']['tools'] if item['id'] == 'c05-' + tool_name]
                if len(tools) != 1 or tools[0]['sha256'] != report['tools'][tool_name]['sha256']:
                    raise CandidateError('ProfileMismatch', 'actual tool image differs from selected public profile: ' + tool_name)
            receipt = read_json(path / 'toolchain.json')
            if receipt['compiler'] != compiler: raise CandidateError('ProfileMismatch', 'consumer compiler target/options differ')
            if sdk: receipts[group] = sdk_binding(receipt, sdk, resources)
            originals[group] = inventory(path); candidates[group] = value; toolchains[group] = receipt
            install = args.output / group / 'install'; install.parent.mkdir(); shutil.copytree(path, install)
            verify_candidate(install); installs[group] = install
        if len({v['identity']['profile_digest'] for v in candidates.values()}) != len(GROUPS):
            raise CandidateError('ProfileMismatch', 'each source selection must have its own profile identity')
        report['candidates'] = {g: {k: v[k] for k in ('manifest', 'identity', 'provenance')} for g, v in candidates.items()}
        report['authors'] = {g: verify_author(installs[g], g) for g in GROUPS}
        environment = [{'id': 'c05-clang', 'version': version.splitlines()[0], 'sha256': reference(clang)['sha256'], 'host': target, 'target': target,
                        'source': str(clang), 'arguments': [*commands.c_flags, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror']},
                       {'id': 'lab-python', 'version': platform.python_version(), 'sha256': reference(Path(sys.executable).resolve())['sha256'],
                        'host': target, 'target': target, 'source': str(Path(sys.executable).resolve()), 'arguments': ['-B']}]
        standard = Reports(ROOT, args.output, candidates, args.lab_revision, environment)
        report['case_inputs'] = standard.index
        for group, install in installs.items():
            probe = public_header_probe(commands, clang, install / 'include', install.parent)
            report['public_header_probes'][group] = probe
            if not sdk: receipts[group] = linux_sdk_binding(toolchains[group], resources, commands.system_roots[0], probe['system_dependencies'])
        report['sdk_inputs'] = receipts; report['preflight'] = 'passed'; report['compile'] = 'started'
        suffix = 'dylib' if target.endswith('darwin') else 'so'
        libraries = {g: p / ('lib/libreading_demo.' + suffix) for g, p in installs.items()}
        executables, stubs = {}, {}
        for group, install in installs.items():
            exe = install.parent / 'consumer'; compile_consumer(commands, clang, install / 'include', libraries[group], exe, group)
            executables[group] = exe; report['executables'][exe.relative_to(args.output).as_posix()] = reference(exe)
            if group.startswith('author-'):
                stub = install.parent / 'helper-provider'; compile_consumer(commands, clang, install / 'include', None, stub, group, stub=True)
                stubs[group] = stub; report['executables'][stub.relative_to(args.output).as_posix()] = reference(stub)
        report['compile'] = 'passed'; report['runtime'] = 'started'
        for group in GROUPS:
            for name in CASE_NAMES[group]:
                standard.begin(group, name); start = time.monotonic_ns(); log_start = len(commands.logs); observations = []
                if name == 'exports':
                    flags = ['-gU'] if target.endswith('darwin') else ['-D', '-g', '--defined-only']
                    text, log = commands.run([nm, *flags, libraries[group]])
                    observations.append({'exports': inspect_exports(text, group, candidates[group]['contract']), 'log': log})
                    for method in sorted({'normalize', 'canonicalize', 'offset'} - set(METHODS[group])):
                        observations.append(rejected_declaration(commands, clang, installs[group] / 'include', installs[group].parent, method))
                elif name == 'removed-api':
                    for method in ('normalize', 'offset'):
                        observations.append(rejected_link(commands, clang, installs[group] / 'include', libraries[group], installs[group].parent, method))
                elif name == 'mixed-candidates':
                    for header_group, provider in (('author-0', 'author-2'), ('author-2', 'author-0')):
                        if candidates[header_group]['identity']['interface_digest'] == candidates[provider]['identity']['interface_digest']:
                            raise ValueError('mixed versions must differ in actual ABI identity')
                        exe = args.output / ('mixed-' + header_group + '-to-' + provider)
                        compile_consumer(commands, clang, installs[header_group] / 'include', libraries[provider], exe, header_group, mismatch=True)
                        report['executables'][exe.relative_to(args.output).as_posix()] = reference(exe)
                        identity = candidates[provider]['identity']; text, log = run_target(commands, standard, [exe, 'mismatch', libraries[provider], identity['interface_digest'][7:] + identity['profile_digest'][7:]])
                        observations.append({'header': header_group, 'provider': provider, 'rows': inspect_output(text, header_group, 'mismatch', libraries[provider], identity), 'log': log})
                else:
                    if group.startswith('aux-'):
                        flags = ['-gU'] if target.endswith('darwin') else ['-D', '-g', '--defined-only']
                        text, log = commands.run([nm, *flags, libraries[group]])
                        observations.append({'exports': inspect_exports(text, group, candidates[group]['contract']), 'log': log})
                    identity = candidates[group]['identity']; hex_identity = identity['interface_digest'][7:] + identity['profile_digest'][7:]
                    argv = [stubs[group], name, hex_identity] if name == 'helper-protocol' else [executables[group], name, libraries[group], hex_identity]
                    text, log = run_target(commands, standard, argv)
                    observations.append({'rows': inspect_output(text, group, name, libraries[group], identity), 'log': log})
                standard.finish(start, time.monotonic_ns(), commands.logs[log_start:], observations)
                report['observations'].append({'group': group, 'case': name, 'observations': observations})
        if lab_identity(ROOT, args.lab_revision) != lab_files: raise ValueError('Lab source changed during execution')
        for name, details in report['tools'].items():
            if reference(Path(details['path'])) != {k: details[k] for k in ('sha256', 'size')}: raise ValueError('actual tool changed: ' + name)
        for item in environment:
            if reference(Path(item['source']))['sha256'] != item['sha256']: raise ValueError('report environment image changed')
        for item in commands.logs:
            if reference(args.output / item['path']) != {k: item[k] for k in ('sha256', 'size')}: raise ValueError('raw command log changed')
        for name, expected in report['executables'].items():
            if reference(args.output / name) != expected: raise ValueError('consumer binary changed')
        for compilation in commands.compilations:
            if any(reference(Path(p)) != v for p, v in compilation['inputs'].items()): raise ValueError('actual compiler input changed')
        for group, probe in report['public_header_probes'].items():
            if any(reference(Path(p)) != v for p, v in probe['inputs'].items()): raise ValueError('public header dependency changed')
            for key in ('source', 'depfile'):
                ref = probe[key]
                if reference(args.output / ref['path']) != {k: ref[k] for k in ('sha256', 'size')}: raise ValueError('public header probe bytes changed')
            actual_receipt = sdk_binding(toolchains[group], sdk, resources) if sdk else linux_sdk_binding(toolchains[group], resources, commands.system_roots[0], probe['system_dependencies'])
            if actual_receipt != receipts[group]: raise ValueError('SDK receipt inputs changed')
        for group, install in installs.items():
            verify_candidate(install); verify_candidate(candidates[group]['root'])
            if inventory(install) != originals[group] or inventory(candidates[group]['root']) != originals[group]: raise ValueError('candidate bytes changed')
        source_names = ['consumers/c/l02_values.c', 'consumers/c/l02_values_aux.c', 'consumers/c/l02_values.md', 'scripts/verify_l02_values.py', 'scripts/test_l02_values.py', 'scripts/verify_l02.py', 'harness/l02_values_reports.py', 'harness/l02_reports.py', 'harness/candidate.py', 'harness/check_cases.py']
        source_names += [p.relative_to(ROOT).as_posix() for parent in ('cases/l02/native-values', 'fixtures/l02/native-values') for p in sorted((ROOT / parent).rglob('*')) if p.is_file()]
        with tarfile.open(args.output / 'consumer-sources.tar', 'w') as archive:
            for name in sorted(source_names): archive.add(ROOT / name, arcname=name)
        report['source_archive'] = reference(args.output / 'consumer-sources.tar')
        standard.verify(); report['runtime'] = 'passed'; report['result'] = 'passed'
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        failure = error; report['error'] = str(error)
        for stage in ('preflight', 'compile', 'runtime'):
            if report[stage] == 'started': report[stage] = 'failed'
    report['logs'] = commands.logs; report['compilations'] = commands.compilations
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if standard is not None: standard.write(report, failure)
    print(json.dumps({'result': report['result'], 'report': str(args.output / 'report.json'), 'error': report.get('error')}))
    return 0 if report['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
