"""Consume one clean public E04 resource package with independent JIT/AOT cases."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import shutil
import sys
from urllib.parse import unquote, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'harness'))
sys.path.insert(0, str(ROOT / 'scripts'))
from candidate import CandidateError, DIGEST, file_digest, parse_json, read_json
from e04_dart_candidate import inventory, verify_candidate
from e04_dart_execution import Commands, bind_sdk, install_dependency, verify_dependencies, cleanup_private_images
from e04_dart_observations import CASE_NAMES, MODES, required_probes
from e04_dart_reports import Reports, SCOPE
from l02_reports import file_reference
from verify_l02 import lab_identity


def dependency_argument(value):
    parts = value.split('=', 3)
    if len(parts) != 4 or not DIGEST.fullmatch(parts[2]):
        raise argparse.ArgumentTypeError('dependency requires name=version=sha256:HEX=archive-path')
    return parts[0], parts[1], Path(parts[3]).resolve(strict=True), parts[2]


def bind_package_configuration(project, package, installed):
    path = project / '.dart_tool/package_config.json'
    value = read_json(path)
    if value.get('configVersion') != 2 or not isinstance(value.get('packages'), list):
        raise ValueError('unexpected actual Pub package configuration')
    expected = {'madb_lab_e04_sync': project, 'madb_dart_ffi': package,
                **{item['name']: Path(item['directory']) for item in installed}}
    actual = {}
    for row in value['packages']:
        name = row['name']
        uri = urlparse(urljoin(path.as_uri(), row['rootUri']))
        if uri.scheme != 'file' or uri.netloc or uri.query or uri.fragment or name in actual:
            raise ValueError('Pub package configuration escapes local isolated roots')
        package_root = Path(unquote(uri.path))
        resolved_root = package_root.resolve(strict=True)
        # Pub's packageUri, not rootUri alone, selects where package: imports go.
        # This finite consumer expects each package's canonical lib/ directory.
        import_uri = row.get('packageUri')
        if not isinstance(import_uri, str) or import_uri != 'lib/':
            raise ValueError('Pub packageUri must be the approved relative lib/ import root')
        import_root = package_root / 'lib'
        if (package_root != resolved_root or package_root.is_symlink() or import_root.is_symlink()
                or not import_root.is_dir() or import_root.resolve(strict=True) != resolved_root / 'lib'):
            raise ValueError('Pub import root is missing or uses a symbolic-link alias')
        actual[name] = resolved_root
    if actual != {name: root.resolve(strict=True) for name, root in expected.items()}:
        raise ValueError('actual Pub resolution imported an undeclared package or cache')
    return file_reference(path, project.parent)


def negative_packages(output, package, admitted):
    """Derived damaged copies are load-rejection inputs, never valid candidates."""
    result = {'ordinary': (package / 'native', 'success', None)}
    native_name = admitted['native']['install']['native']
    for name, kind in (('missing-native', 'missingAsset'), ('changed-native', 'digestMismatch'),
                       ('symlink-native', 'pathViolation')):
        destination = output / 'negative-assets' / name
        shutil.copytree(package / 'native', destination)
        target = destination / native_name
        if name == 'missing-native':
            target.unlink()
        elif name == 'changed-native':
            data = target.read_bytes()
            if not data:
                raise ValueError('native binary is empty')
            target.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        else:
            target.unlink()
            target.symlink_to(package / 'native' / native_name)
        facts = {'path': str(destination.resolve() / native_name), 'expected_digest': None, 'actual_digest': None}
        if name == 'changed-native':
            facts.update(expected_digest=admitted['native']['files'][native_name]['sha256'][7:],
                         actual_digest=file_digest(target.read_bytes())[7:])
        result[name] = destination, kind, facts
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--candidate-digest', required=True)
    parser.add_argument('--producer-revision', required=True)
    parser.add_argument('--lab-revision', required=True)
    parser.add_argument('--dart-sdk', type=Path, required=True)
    parser.add_argument('--dart-sdk-archive', type=Path, required=True)
    parser.add_argument('--dart-sdk-archive-digest', required=True)
    parser.add_argument('--dependency', action='append', type=dependency_argument, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    args.output = args.output.resolve()
    args.candidate = args.candidate.resolve()
    args.dart_sdk = args.dart_sdk.resolve()
    args.dart_sdk_archive = args.dart_sdk_archive.resolve()
    for root in (ROOT, args.candidate, args.dart_sdk):
        if root.is_relative_to(args.output) or args.output.is_relative_to(root):
            parser.error('output overlaps source, candidate or tool input')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'scope': SCOPE, 'result': 'error', 'observations': [], 'logs': [], 'missing': []}
    reports = commands = None
    try:
        if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
            raise ValueError('this finite E04 consumer requires actual macOS arm64')
        source_before = lab_identity(ROOT, args.lab_revision)
        candidate_before = inventory(args.candidate)
        admitted = verify_candidate(args.candidate, args.candidate_digest, args.producer_revision)
        sdk = bind_sdk(args.dart_sdk, args.dart_sdk_archive, args.dart_sdk_archive_digest)
        report.update(lab_revision=args.lab_revision, lab_inputs=source_before,
                      candidate_digest=args.candidate_digest, producer_revision=args.producer_revision,
                      candidate_inputs=candidate_before, dart_sdk=sdk)
        commands = Commands(args.output)
        installed = [install_dependency(args.output / 'pub-cache', *item) for item in args.dependency]
        report['runtime_dependencies'] = installed
        dart = args.dart_sdk / 'bin/dart'
        version, _ = commands.run([dart, '--version'], cwd=args.output)
        if not version['stdout'].startswith('Dart SDK version: 3.13.7 (stable) '):
            raise ValueError('actual Dart version is not the selected stable 3.13.7')
        environment = [{'id': 'dart', 'version': '3.13.7', 'sha256': sdk['files']['bin/dart']['sha256'],
                        'host': 'aarch64-apple-darwin', 'target': 'aarch64-apple-darwin',
                        'source': 'https://storage.googleapis.com/dart-archive/channels/stable/release/3.13.7/sdk/dartsdk-macos-arm64-release.zip',
                        'arguments': ['--version']}]
        reports = Reports(ROOT, args.output, admitted, args.lab_revision, environment)
        package = args.output / 'package'
        shutil.copytree(args.candidate, package)
        if inventory(package) != candidate_before:
            raise ValueError('isolated package copy differs from admitted bytes')
        # Check the shipped lock with Pub itself before compiling the consumer.
        commands.run([dart, 'pub', 'get', '--offline', '--enforce-lockfile'], cwd=package, timeout=120)
        project = args.output / 'consumer'
        project.mkdir()
        (project / 'lib').mkdir()
        shutil.copy2(ROOT / 'consumers/dart/e04_sync/consumer.dart', project / 'consumer.dart')
        template = (ROOT / 'consumers/dart/e04_sync/pubspec.yaml.in').read_text()
        if template.count("'@PACKAGE@'") != 1:
            raise ValueError('consumer dependency template changed')
        (project / 'pubspec.yaml').write_text(template.replace("'@PACKAGE@'", json.dumps(str(package))))
        commands.run([dart, 'pub', 'get', '--offline'], cwd=project, timeout=120)
        graph, _ = commands.run([dart, 'pub', 'deps', '--json'], cwd=project)
        report['resolved_dependencies'] = verify_dependencies(parse_json(graph['stdout'].encode()), installed)
        report['package_configuration'] = bind_package_configuration(project, package, installed)
        commands.run([dart, 'analyze', '--fatal-infos', '--fatal-warnings', 'consumer.dart'], cwd=project, timeout=120)
        executable = project / 'consumer-aot'
        commands.run([dart, 'compile', 'exe', 'consumer.dart', '-o', executable], cwd=project, timeout=180)
        report['aot_executable'] = file_reference(executable, args.output)
        prefixes = {'jit': [dart, '--packages=' + str(project / '.dart_tool/package_config.json'), project / 'consumer.dart'],
                    'aot': [executable]}
        reports.bind_commands(prefixes['jit'], prefixes['aot'])
        negatives = negative_packages(args.output, package, admitted)
        for name in CASE_NAMES:
            for mode, variant in required_probes(name):
                native, kind, facts = negatives[variant] if name == 'package' else (package / 'native', None, None)
                base = prefixes[mode]
                arguments = ['load', native, kind] if name == 'package' else [name, native]
                timeout = reports.begin(name, mode, variant, [*base, *arguments])
                _, log = commands.run([*base, *arguments], cwd=project, timeout=timeout,
                                      **reports.execution_binding())
                observed = reports.complete(log, load_kind=kind, load_facts=facts)
                report['observations'].append({'case': name, 'mode': mode, 'variant': variant,
                                               'log': log, 'observations': observed})
        if lab_identity(ROOT, args.lab_revision) != source_before or inventory(args.candidate) != candidate_before:
            raise ValueError('Lab or original candidate changed during execution')
        if bind_sdk(args.dart_sdk, args.dart_sdk_archive, args.dart_sdk_archive_digest) != sdk:
            raise ValueError('Dart tool installation changed during execution')
        for name, row in candidate_before.items():
            data = (package / name).read_bytes()
            if len(data) != row['size'] or file_digest(data) != row['sha256']:
                raise ValueError('an admitted package input changed during execution: ' + name)
        verify_dependencies(report['resolved_dependencies'], installed)
        report['file_cleanup'] = cleanup_private_images(args.output / 'tmp', process_cleanup_confirmed=commands.cleanup_confirmed)
        reports.verify()
        report['result'] = 'passed'
        error = None
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as failure:
        error = failure
        report['error'] = type(failure).__name__ + ': ' + str(failure)
        report['missing'] = [name for name in CASE_NAMES if reports is None or not reports.records[name]]
        print(report['error'], file=sys.stderr)
    if commands is not None:
        report['logs'] = commands.logs
        if 'file_cleanup' not in report:
            try:
                report['file_cleanup'] = cleanup_private_images(args.output / 'tmp', process_cleanup_confirmed=commands.cleanup_confirmed)
            except (OSError, ValueError) as cleanup_error:
                report['file_cleanup'] = {'error': str(cleanup_error),
                                          'scope': 'only-this-run-TMPDIR; SDK close remains unproved'}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if reports is not None:
        reference = reports.write(report, error)
        (args.output / 'reports.json').write_text(json.dumps([reference], indent=2) + '\n')
    return 0 if error is None else 1


if __name__ == '__main__':
    raise SystemExit(main())
