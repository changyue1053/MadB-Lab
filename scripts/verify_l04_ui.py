"""Independent pure Swift Observation source-package UI consumption; no native certification."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import signal
import shutil
import subprocess
import sys
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'consumers/swift/l04_ui'
BUNDLE = 'org.madb.lab.l04ui'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reference(path):
    data = path.read_bytes()
    return {'sha256': sha(data), 'size': len(data)}


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError('symlink/special input: ' + str(path))
        if path.is_file():
            result[path.relative_to(root).as_posix()] = reference(path)
    return result


def inspect_frames(text, nonce):
    """Assertions are independently fixed, not derived from the consumer or SDK."""
    rows = [json.loads(line) for line in text.splitlines()]
    if len(rows) != 62 or any(r.get('nonce') != nonce or r.get('mainThread') is not True for r in rows):
        raise ValueError('frame count, nonce, or main-thread observation differs')
    pids = {r.get('pid') for r in rows}
    if len(pids) != 1 or any(type(p) is not int or p <= 0 for p in pids):
        raise ValueError('trace must belong to one real application PID')
    if rows[0]['event'] != 'owner-started' or rows[-1]['event'] != 'owner-closed':
        raise ValueError('owner boundaries differ')
    first = rows[0]
    if first['counts'] != {'created': 1, 'active': 1, 'drained': 0, 'sourceClosed': 0} or first['ordinaryValue'] != -1:
        raise ValueError('ordinary initial state differs')
    page_events = ('page-created', 'page-started', 'page-refreshed', 'duplicate-rejected',
                   'page-value', 'page-disappeared', 'page-drained', 'controller-destroyed', 'model-release-observed')
    seen = set()
    cursor = 1
    for index in range(1, 7):
        group = rows[cursor:cursor + 10]
        cursor += 10
        if group[-1]['event'] != 'after-page-value':
            raise ValueError('missing independent post-page publication')
        events = [r['event'] for r in group[:-1]]
        if sorted(events) != sorted(page_events):
            raise ValueError('missing/duplicate/unknown lifecycle event')
        by_event = {r['event']: r for r in group}
        positions = {r['event']: i for i, r in enumerate(group)}
        ordered = ['page-created', 'page-started', 'page-refreshed', 'duplicate-rejected', 'page-value', 'page-disappeared']
        if [positions[k] for k in ordered] != sorted(positions[k] for k in ordered):
            raise ValueError('page action order differs')
        if not (positions['page-disappeared'] < positions['page-drained'] < positions['model-release-observed']
                and positions['page-disappeared'] < positions['controller-destroyed'] < positions['model-release-observed']):
            raise ValueError('drain/controller release order differs')
        identity = group[0].get('pageID')
        uuid.UUID(identity)
        if identity in seen or any(r.get('pageID') != identity for r in group[:-1]):
            raise ValueError('page identity reused or mismatched')
        seen.add(identity)
        framework = 'swiftui' if index <= 3 else 'uikit'
        if any(r.get('framework') != framework for r in group[:-1]):
            raise ValueError('framework attribution differs')
        for event in ('page-started', 'page-refreshed', 'duplicate-rejected', 'page-value'):
            if by_event[event]['counts'] != {'created': index + 1, 'active': 2, 'drained': index - 1, 'sourceClosed': 0}:
                raise ValueError('duplicate registration or shared-source damage')
        if by_event['page-started']['pageValue'] != -1:
            raise ValueError('new page invented replay')
        value = by_event['page-value']
        if value['ordinaryValue'] != 2 * index - 1 or value['pageValue'] != 2 * index - 1:
            raise ValueError('page and ordinary observers did not receive exact publication')
        drained = by_event['page-drained']
        if drained['status'] != 'stopped' or drained['counts'] != {'created': index + 1, 'active': 1, 'drained': index, 'sourceClosed': 0}:
            raise ValueError('page stop was not confirmed independently of shared owner')
        released = by_event['model-release-observed']
        if released['released'] != index or released['destroyed'] != index:
            raise ValueError('model/controller remained retained')
        after = group[-1]
        if after['ordinaryValue'] != 2 * index or after['counts'] != drained['counts']:
            raise ValueError('shared ordinary observer did not remain usable')
    final = rows[-1]
    if final['counts'] != {'created': 7, 'active': 0, 'drained': 7, 'sourceClosed': 1} or final['ordinaryValue'] != 12 or final['destroyed'] != 6 or final['released'] != 6:
        raise ValueError('owner completion did not preserve exact resource postconditions')
    if any(r['counts']['sourceClosed'] != 0 for r in rows[:-1]):
        raise ValueError('page closed the shared source')
    return {'frames': len(rows), 'pid': next(iter(pids)), 'fresh_pages': 6,
            'frameworks': {'swiftui': 3, 'uikit': 3}, 'normal_owner_close': True}


class Commands:
    def __init__(self, output):
        self.output, self.count = output, 0

    def run(self, argv, timeout=60, expected_failure=None):
        self.count += 1
        path = self.output / 'logs' / f'{self.count:03d}.json'
        path.parent.mkdir(exist_ok=True)
        process = subprocess.Popen([str(x) for x in argv], cwd=self.output, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        path.write_text(json.dumps({'argv': [str(x) for x in argv], 'exit_code': process.returncode,
                                   'timeout': timed_out, 'stdout': stdout.decode(errors='replace'),
                                   'stderr': stderr.decode(errors='replace'), 'expected_failure': expected_failure}, indent=2) + '\n')
        if expected_failure:
            if process.returncode == 0 or timed_out or expected_failure not in stderr.decode(errors='replace'):
                raise RuntimeError('expected precise negative was not observed: ' + str(path))
            return stdout.decode()
        if process.returncode or timed_out:
            raise RuntimeError('command failed: ' + str(path))
        return stdout.decode()


def source_inputs():
    paths = [Path(__file__), ROOT / 'scripts/test_l04_ui.py', ROOT / '.python-version', ROOT / 'AGENTS.md']
    paths += [p for p in SOURCE.rglob('*') if p.is_file()]
    paths += [p for p in (ROOT / 'docs/reference').rglob('*') if p.is_file()]
    return {str(p.relative_to(ROOT)): reference(p) for p in sorted(paths)}


def source_barrier(commands, project):
    manifest = '''// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "L04SourceBarrier", platforms: [.macOS(.v14)],
    dependencies: [.package(path: "../PublicObservation")],
    targets: [.executableTarget(name: "SourceBarrier", dependencies:
        [.product(name: "MadBObservation", package: "PublicObservation")])])
'''
    for name, mutation in [('source-barrier', False), ('source-barrier-early', True)]:
        package = project / name
        source = package / 'Sources/SourceBarrier'; source.mkdir(parents=True)
        (package / 'Package.swift').write_text(manifest)
        body = (SOURCE / 'LocalSource.swift').read_text()
        if mutation:
            before = 'if ended { return true }'
            if body.count(before) != 1:
                raise ValueError('controlled early-confirmation mutation no longer matches')
            body = body.replace(before, 'if ended || finishing { return true }')
        (source / 'LocalSource.swift').write_text(body)
        shutil.copyfile(SOURCE / 'SourceBarrierTests.swift', source / 'Main.swift')
        output = commands.run(['xcrun', 'swift', 'run', '--disable-sandbox', '--package-path', package,
                               '--scratch-path', commands.output / (name + '-build'),
                               '--cache-path', commands.output / 'spm-cache',
                               '--config-path', commands.output / 'spm-config',
                               '--security-path', commands.output / 'spm-security',
                               '--manifest-cache', 'local', '-c', 'release'], timeout=180,
                              expected_failure='L04_EARLY_STOP_CONFIRMATION' if mutation else None)
        if not mutation and output.strip() != 'L04_SOURCE_BARRIER_OK cleanup-before-confirmation duplicate-collector-rejected':
            raise ValueError('source barrier did not complete exact positive assertions')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--package-pin', type=Path, required=True)
    parser.add_argument('--expected-pin-sha256', required=True)
    parser.add_argument('--runtime', default='com.apple.CoreSimulator.SimRuntime.iOS-26-5')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output, args.package = args.output.resolve(), args.package.resolve()
    if any(args.output.is_relative_to(p) or p.is_relative_to(args.output) for p in (ROOT, args.package)):
        parser.error('output overlaps an input')
    args.output.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.output)
    report = {'scope': 'L04 pure Swift public Observation package; actual SwiftUI/UIKit navigation',
              'native_composition': 'not_requested', 'certifies_l04': False, 'result': 'failed',
              'source_barrier': 'not_run', 'compile': 'not_run', 'target': 'not_run', 'owner_close': 'not_confirmed', 'cleanup': 'not_needed',
              'limitations': ['no native SDK or C06/iOS composition', 'no physical target or minimum-OS certification',
                              'no background/rotation/concurrent-page coverage', 'no native late-callback or close-failure injection',
                              'source package development delivery; no C10 release certification']}
    device = None
    try:
        report['lab_inputs'] = source_inputs()
        if platform.python_version() != (ROOT / '.python-version').read_text().strip():
            raise ValueError('use pinned Lab Python')
        pin_bytes = args.package_pin.read_bytes()
        if sha(pin_bytes) != args.expected_pin_sha256:
            raise ValueError('package pin differs from independent trust input')
        expected = json.loads(pin_bytes)['files']
        if inventory(args.package) != expected or not {'Package.swift', 'LICENSE', 'Sources/MadBObservation/MadBStateModel.swift', 'Sources/MadBObservation/MadBStateSource.swift'} <= set(expected):
            raise ValueError('public package bytes differ from fixed inventory')
        report['package_pin'] = {'path': str(args.package_pin), **reference(args.package_pin), 'files': expected}
        report['lab_revision'] = commands.run(['git', '-C', ROOT, 'rev-parse', 'HEAD']).strip()
        report['lab_status'] = commands.run(['git', '-C', ROOT, 'status', '--porcelain'])
        xcode = commands.run(['xcodebuild', '-version']).strip()
        swift = commands.run(['xcrun', 'swift', '--version']).strip()
        sdk_version = commands.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version']).strip()
        sdk_build = commands.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-build-version']).strip()
        if xcode != 'Xcode 27.0\nBuild version 27A266a' or 'Apple Swift version 6.4 (swiftlang-6.4.0.34.1 clang-2100.3.34.1)' not in swift or (sdk_version, sdk_build) != ('27.0', '24A430'):
            raise ValueError('Apple toolchain differs from this reviewed UI recipe')
        report['tools'] = {'xcode': xcode, 'swift': swift, 'sdk_version': sdk_version, 'sdk_build': sdk_build}
        existing = json.loads(commands.run(['xcrun', 'simctl', 'list', '--json']))
        selected = [r for r in existing['runtimes'] if r['identifier'] == args.runtime and r['isAvailable']]
        if len(selected) != 1:
            raise ValueError('selected installed runtime is unavailable')
        report['runtime'] = selected[0]
        nonce = uuid.uuid4().hex
        report['nonce'] = nonce
        project = args.output / 'project'; project.mkdir()
        shutil.copytree(args.package, project / 'PublicObservation')
        for name in ('App.swift', 'Owner.swift', 'LocalSource.swift', 'LifecycleUITests.swift'):
            (project / name).write_bytes((SOURCE / name).read_bytes().replace(b'__NONCE__', nonce.encode()))
        xcodeproj = project / 'MadBL04UI.xcodeproj'; xcodeproj.mkdir()
        shutil.copyfile(SOURCE / 'project.pbxproj', xcodeproj / 'project.pbxproj')
        schemes = xcodeproj / 'xcshareddata/xcschemes'; schemes.mkdir(parents=True)
        shutil.copyfile(SOURCE / 'MadBL04UI.xcscheme', schemes / 'MadBL04UI.xcscheme')
        report['source_barrier'] = 'started'
        source_barrier(commands, project)
        report['source_barrier'] = 'passed_with_exact_early_confirmation_rejection'
        with tarfile.open(args.output / 'sources.tar', 'w') as archive:
            archive.add(project, arcname='project')
        report['source_archive'] = reference(args.output / 'sources.tar')
        device = commands.run(['xcrun', 'simctl', 'create', 'MadB-L04-' + nonce,
                               'com.apple.CoreSimulator.SimDeviceType.iPhone-17', args.runtime]).strip()
        uuid.UUID(device); report['device'] = device; report['cleanup'] = 'required'
        commands.run(['xcrun', 'simctl', 'boot', device])
        commands.run(['xcrun', 'simctl', 'bootstatus', device, '-b'], timeout=180)
        base = ['xcodebuild', '-project', xcodeproj, '-scheme', 'MadBL04UI', '-configuration', 'Release',
                '-destination', 'platform=iOS Simulator,id=' + device, '-derivedDataPath', args.output / 'DerivedData',
                '-clonedSourcePackagesDirPath', args.output / 'SourcePackages', '-disableAutomaticPackageResolution', '-skipPackageUpdates',
                '-parallel-testing-enabled', 'NO', 'CODE_SIGNING_ALLOWED=NO']
        report['compile'] = 'started'
        commands.run(base + ['-resultBundlePath', args.output / 'compile.xcresult', 'build-for-testing'], timeout=300)
        report['compile'] = 'passed'
        app = args.output / 'DerivedData/Build/Products/Release-iphonesimulator/MadBL04UI.app'
        report['app_files'] = inventory(app)
        report['target'] = 'started'
        commands.run(base + ['-resultBundlePath', args.output / 'tests.xcresult', 'test-without-building'], timeout=360)
        summary = json.loads(commands.run(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', args.output / 'tests.xcresult']))
        report['xctest_summary'] = summary
        if summary.get('result') != 'Passed' or summary.get('passedTests') != 1 or summary.get('failedTests') != 0 or summary.get('skippedTests') != 0:
            raise ValueError('XCTest actual result is not one complete passing test')
        container = Path(commands.run(['xcrun', 'simctl', 'get_app_container', device, BUNDLE, 'data']).strip())
        raw = (container / 'Documents/l04-evidence.jsonl').read_bytes()
        (args.output / 'target-evidence.jsonl').write_bytes(raw)
        report['observations'] = inspect_frames(raw.decode(), nonce)
        report['raw_log'] = reference(args.output / 'target-evidence.jsonl')
        report['target'] = 'passed'; report['owner_close'] = 'confirmed'
        if source_inputs() != report['lab_inputs'] or inventory(args.package) != expected:
            raise ValueError('frozen source changed during verification')
        report['result'] = 'passed'
    except Exception as error:
        report['error'] = str(error)
        for stage in ('source_barrier', 'compile', 'target'):
            if report[stage] == 'started': report[stage] = 'failed'
    finally:
        if device:
            try:
                state = json.loads(commands.run(['xcrun', 'simctl', 'list', '--json', 'devices']))
                own = [d for values in state['devices'].values() for d in values if d['udid'] == device]
                if own and own[0]['state'] == 'Booted': commands.run(['xcrun', 'simctl', 'shutdown', device])
                commands.run(['xcrun', 'simctl', 'delete', device])
                state = json.loads(commands.run(['xcrun', 'simctl', 'list', '--json', 'devices']))
                if any(d['udid'] == device for values in state['devices'].values() for d in values):
                    raise RuntimeError('owned simulator still exists')
                report['cleanup'] = 'passed'
            except Exception as error:
                report['cleanup'] = 'failed'; report['cleanup_error'] = str(error); report['result'] = 'failed'
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'result': report['result'], 'compile': report['compile'], 'target': report['target'],
                      'cleanup': report['cleanup'], 'error': report.get('error'), 'report': str(args.output / 'report.json')}))
    return 0 if report['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
