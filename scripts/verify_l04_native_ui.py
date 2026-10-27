"""Consume a frozen public SKIE candidate in a real macOS SwiftUI application."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'harness'))
from l04_native_ui import admit_candidate, admit_package, inspect_frames, inventory, reference

SOURCE = ROOT / 'consumers/swift/l04_native_ui'
SCHEME = 'MadBL04NativeUI'


class Commands:
    def __init__(self, output: Path):
        self.output = output
        self.records = []
        self.environment = os.environ.copy()
        for key in tuple(self.environment):
            if key.startswith('DYLD_') or key in {'SDKROOT', 'SWIFT_EXEC', 'SWIFT_DRIVER_SWIFT_FRONTEND_EXEC', 'DEVELOPER_DIR'}:
                del self.environment[key]
        self.environment['CLANG_MODULE_CACHE_PATH'] = str(output / 'clang-cache')
        self.environment['SWIFTPM_MODULECACHE_OVERRIDE'] = str(output / 'swift-module-cache')
        self.environment['PYTHONDONTWRITEBYTECODE'] = '1'

    def owned_processes(self, executables):
        argv = ['/bin/ps', '-axo', 'pid=,comm=']
        result = subprocess.run(argv, cwd=self.output, env=self.environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        selected = select_owned_processes(result.stdout, executables) if result.returncode == 0 else []
        record = {'argv': argv, 'cwd': str(self.output), 'exit_code': result.returncode,
                  'stderr': result.stderr, 'exact_executables': sorted(executables), 'selected': selected,
                  'stdout_handling': 'Only exact owned executable records retained; unrelated process metadata discarded.'}
        path = self.output / 'logs' / f'{len(self.records):03d}.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        self.records.append({'path': path.relative_to(self.output).as_posix(), **reference(path)})
        if result.returncode:
            raise RuntimeError('owned process inventory failed: ' + str(path))
        return selected

    def run(self, argv, *, timeout=60, allowed=(0,), include_stderr=False):
        argv = [str(item) for item in argv]
        process = subprocess.Popen(argv, cwd=self.output, env=self.environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        record = {'argv': argv, 'cwd': str(self.output), 'exit_code': process.returncode, 'timeout': timed_out,
                  'stdout': stdout.decode(errors='replace'), 'stderr': stderr.decode(errors='replace')}
        path = self.output / 'logs' / f'{len(self.records):03d}.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        self.records.append({'path': path.relative_to(self.output).as_posix(), **reference(path)})
        if process.returncode not in allowed or timed_out:
            raise RuntimeError('command failed: ' + str(path))
        return record['stdout'] + record['stderr'] if include_stderr else record['stdout']


def source_inputs():
    paths = [ROOT / name for name in (
        'scripts/verify_l04_native_ui.py', 'scripts/test_l04_native_ui.py', 'harness/l04_native_ui.py',
        'harness/candidate.py', 'harness/c06_candidate.py', 'harness/c06_contract.py', '.python-version', 'AGENTS.md')]
    paths += [path for path in SOURCE.rglob('*') if path.is_file()]
    paths += [path for path in (ROOT / 'docs/reference').rglob('*') if path.is_file()]
    paths += [path for path in (ROOT / 'cases/c06').rglob('*') if path.is_file()]
    return {path.relative_to(ROOT).as_posix(): reference(path) for path in sorted(paths)}


def require_distinct(output: Path, *inputs: Path):
    for source in inputs:
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('output overlaps an input')


def copy_project(output: Path, package: Path, candidate: Path, nonce: str, identity: dict):
    project = output / 'project'
    project.mkdir()
    shutil.copytree(package, project / 'PublicObservation')
    shutil.copytree(candidate, project / 'PublicCandidate')
    public = project / 'PublicSkie'
    public.mkdir()
    shutil.copytree(project / 'PublicCandidate/framework/MadBSkie.framework', public / 'MadBSkie.framework')
    shutil.copyfile(project / 'PublicCandidate/swift/MadBSkieConcurrency.swift', public / 'MadBSkieConcurrency.swift')
    shutil.copyfile(project / 'PublicObservation/Integration/SKIE/MadBSkieStateSource.swift', public / 'MadBSkieStateSource.swift')
    substitutions = {'__NONCE__': nonce, '__PROFILE__': identity['profile_digest'],
                     '__INTERFACE__': identity['interface_digest'], '__LOG_PATH__': str(output / 'target-evidence.jsonl')}
    for name in ('App.swift', 'NativeOwner.swift', 'LifecycleUITests.swift'):
        text = (SOURCE / name).read_text()
        for token, value in substitutions.items():
            text = text.replace('"' + token + '"', json.dumps(value, ensure_ascii=False))
        if any(token in text for token in substitutions):
            raise ValueError('unexpanded consumer configuration token')
        (project / name).write_text(text)
    xcodeproj = project / (SCHEME + '.xcodeproj')
    xcodeproj.mkdir()
    shutil.copyfile(SOURCE / 'project.pbxproj', xcodeproj / 'project.pbxproj')
    schemes = xcodeproj / 'xcshareddata/xcschemes'
    schemes.mkdir(parents=True)
    shutil.copyfile(SOURCE / (SCHEME + '.xcscheme'), schemes / (SCHEME + '.xcscheme'))
    (output / 'consumer-configuration.json').write_text(json.dumps(substitutions, ensure_ascii=False, indent=2) + '\n')
    return project, xcodeproj


def observe_tools(commands: Commands, candidate: dict):
    xcode = commands.run(['/usr/bin/xcodebuild', '-version']).strip()
    swift = commands.run(['/usr/bin/xcrun', 'swiftc', '--version']).strip()
    sdk_version = commands.run(['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-version']).strip()
    sdk_build = commands.run(['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-build-version']).strip()
    locked = candidate['toolchain']['xcode']
    if (xcode != f"Xcode {locked['version']}\nBuild version {locked['build']}" or locked['swift'] not in swift
            or sdk_version != locked['sdk_version'] or sdk_build != locked['sdk_build']):
        raise ValueError('Apple compiler/SDK differs from the reviewed native candidate lock')
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('this native UI slice requires macOS Arm64')
    images = {}
    for name in ('swiftc', 'clang', 'ld', 'xcodebuild'):
        path = Path(commands.run(['/usr/bin/xcrun', '--find', name]).strip()).resolve(strict=True)
        images[name] = {'path': str(path), **reference(path)}
    sdk = Path(commands.run(['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-path']).strip())
    images['codesign'] = {'path': '/usr/bin/codesign', **reference(Path('/usr/bin/codesign'))}
    signing_paths = [sdk / 'SDKSettings.json',
                     sdk.parents[1] / 'Library/Xcode/Agents/XCTRunner.app/Contents/Resources/RunnerEntitlements.plist',
                     sdk.parents[1] / 'Library/Xcode/PrivatePlugIns/IDEOSXSupportCore.ideplugin/Contents/Resources/BaseEntitlements.plist']
    return {'xcode': xcode, 'swift': swift, 'sdk_version': sdk_version, 'sdk_build': sdk_build,
            'sdk_settings': {'path': str(sdk / 'SDKSettings.plist'), **reference(sdk / 'SDKSettings.plist')},
            'signing_inputs': [{'path': str(path), **reference(path)} for path in signing_paths],
            'images': images, 'host': commands.run(['/usr/bin/sw_vers']).strip()}


def verify_tools(observed):
    for record in [*observed['images'].values(), observed['sdk_settings'], *observed['signing_inputs']]:
        if reference(Path(record['path'])) != {key: record[key] for key in ('sha256', 'size')}:
            raise ValueError('consumer compiler/SDK bytes changed during execution')


def observe_signing(commands, app):
    runner = app.parent / 'MadBL04NativeUITests-Runner.app'
    bundle = runner / 'Contents/PlugIns/MadBL04NativeUITests.xctest'
    observed = {'mode': 'local-ad-hoc-development-only', 'distribution_signature': False, 'products': []}
    for name, path in (('application', app), ('test-runner', runner), ('test-bundle', bundle)):
        commands.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', path])
        details = commands.run(['/usr/bin/codesign', '-d', '--verbose=4', path], include_stderr=True)
        if 'Signature=adhoc' not in details.splitlines() or 'TeamIdentifier=not set' not in details.splitlines():
            raise ValueError('expected local ad-hoc signature without a developer team: ' + name)
        raw = commands.run(['/usr/bin/codesign', '-d', '--entitlements', '-', '--xml', path])
        entitlements = plistlib.loads(raw.encode()) if raw.strip() else {}
        if name != 'test-bundle' and entitlements.get('com.apple.security.get-task-allow') is not True:
            raise ValueError('Xcode development task entitlement is absent: ' + name)
        observed['products'].append({'name': name, 'path': str(path), 'entitlements': entitlements})
    return observed


def select_owned_processes(text, executables):
    selected = []
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].startswith('/'):
            continue
        executable = str(Path(parts[1]).resolve())
        if executable in executables:
            pid = int(parts[0])
            if pid <= 0 or any(item['pid'] == pid for item in selected):
                raise ValueError('invalid or duplicated owned process identity')
            selected.append({'pid': pid, 'executablePath': executable})
    return selected


def stop_owned_process(commands: Commands, pid: int, expected: str):
    def running():
        text = commands.run(['/bin/ps', '-p', str(pid), '-o', 'comm='], allowed=(0, 1)).strip()
        if not text:
            return False
        if not text.startswith('/') or str(Path(text).resolve()) != expected:
            # Neither PID reuse nor a truncated observation licenses a signal.
            raise RuntimeError('application PID is present with an unconfirmed executable identity')
        return True
    if not running():
        return {'state': 'exited', 'forced': False, 'pid': pid}
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while running() and time.monotonic() < deadline:
        time.sleep(0.05)
    if running():
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 3
        while running() and time.monotonic() < deadline:
            time.sleep(0.05)
    if running():
        raise RuntimeError('owned UI process survived cleanup')
    return {'state': 'exited', 'forced': True, 'pid': pid,
            'meaning': 'process cleanup only; not native owner-close proof'}


def cleanup_application(commands: Commands, log: Path, nonce: str, app: Path | None):
    receipt = Path(str(log) + '.process.json')
    if app is None:
        return {'state': 'not_observed', 'forced': False, 'reason': 'app was not built'}
    expected = str((app / 'Contents/MacOS' / SCHEME).resolve())
    if not receipt.exists():
        # A launch may stall before even the earliest application entry. Recover
        # only processes executing this fresh output's exact application image.
        found = commands.owned_processes({expected})
        recovered = [stop_owned_process(commands, item['pid'], expected) for item in found]
        return {'state': 'not_observed', 'forced': bool(recovered), 'recovered': recovered,
                'reason': 'process receipt unavailable; no normal application completion claim'}
    if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 4096:
        raise ValueError('application process receipt is not a bounded regular file')
    process = json.loads(receipt.read_text())
    if (set(process) != {'nonce', 'pid', 'executablePath'} or process['nonce'] != nonce
            or type(process['pid']) is not int or process['pid'] <= 0
            or process['executablePath'] != expected):
        raise ValueError('process receipt is not bound to this application and nonce')
    return {**stop_owned_process(commands, process['pid'], expected), 'process_receipt': reference(receipt)}


def cleanup_test_runner(commands: Commands, app: Path | None):
    if app is None:
        return {'state': 'not_needed', 'processes': []}
    name = SCHEME + 'Tests-Runner'
    executable = str((app.parent / (name + '.app') / 'Contents/MacOS' / name).resolve())
    found = commands.owned_processes({executable})
    processes = [stop_owned_process(commands, item['pid'], executable) for item in found]
    if commands.owned_processes({executable}):
        raise RuntimeError('owned XCTest runner remains after cleanup')
    return {'state': 'exited', 'processes': processes,
            'meaning': 'XCTest control-process cleanup; separate from native application close'}


def cleanup_execution(commands: Commands, log: Path, nonce: str, app: Path | None):
    result = {}
    # Stop the launcher first: it must not start an application after our final
    # application inventory. Failures in either domain never skip the other one.
    try:
        result['xctest_runner_cleanup'] = cleanup_test_runner(commands, app)
    except Exception as error:
        result['xctest_runner_cleanup_error'] = str(error)
    try:
        result['cleanup'] = cleanup_application(commands, log, nonce, app)
    except Exception as error:
        result['cleanup_error'] = str(error)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--expected-candidate-digest', required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--package-pin', type=Path, required=True)
    parser.add_argument('--expected-pin-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-dirty', action='store_true', help='development only; report remains provisional')
    parser.add_argument('--build-only', action='store_true', help='compile only; never claim target or slice pass')
    args = parser.parse_args()
    for key in ('candidate', 'package', 'package_pin', 'output'):
        setattr(args, key, getattr(args, key).resolve())
    require_distinct(args.output, ROOT, args.candidate, args.package, args.package_pin)
    args.output.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.output)
    report = {'scope': 'L04 macOS Arm64 native SKIE + public Observation + actual SwiftUI lifecycle',
              'result': 'failed', 'compile': 'not_run', 'target': 'not_run', 'owner_close': 'not_confirmed',
              'certifies_l04': False, 'certifies_c06': False, 'certifies_release': False,
              'limitations': ['no iOS/UIKit or physical/minimum-OS evidence', 'no new native candidate certification',
                              'no native fault/late-callback injection', 'no background/rotation or simultaneous-page evidence',
                              'public source supplement, not a C10 distribution release']}
    app = None
    nonce = uuid.uuid4().hex
    report['nonce'] = nonce
    try:
        if platform.python_version() != (ROOT / '.python-version').read_text().strip():
            raise ValueError('use pinned Lab Python')
        report['lab_revision'] = commands.run(['/usr/bin/git', '-C', ROOT, 'rev-parse', 'HEAD']).strip()
        report['lab_status'] = commands.run(['/usr/bin/git', '-C', ROOT, 'status', '--porcelain'])
        report['provisional'] = bool(report['lab_status'])
        if report['provisional'] and not args.allow_dirty:
            raise ValueError('formal native UI evidence requires a clean Lab revision')
        report['lab_inputs'] = source_inputs()
        package = admit_package(args.package, args.package_pin, args.expected_pin_sha256)
        candidate = admit_candidate(args.candidate, args.expected_candidate_digest)
        report['public_source'] = {'pin': {'path': str(args.package_pin), **reference(args.package_pin)}, **package}
        report['candidate'] = {key: candidate[key] for key in ('manifest', 'identity', 'provenance')}
        report['tools'] = observe_tools(commands, candidate)
        project, xcodeproj = copy_project(args.output, args.package, args.candidate, nonce, candidate['identity'])
        copied_candidate = admit_candidate(project / 'PublicCandidate', args.expected_candidate_digest)
        admit_package(project / 'PublicObservation', args.package_pin, args.expected_pin_sha256)
        report['consumer_inputs'] = inventory(project)
        report['consumer_configuration'] = reference(args.output / 'consumer-configuration.json')
        base = ['/usr/bin/xcodebuild', '-project', xcodeproj, '-scheme', SCHEME, '-configuration', 'Release',
                '-destination', 'platform=macOS,arch=arm64', '-derivedDataPath', args.output / 'DerivedData',
                '-clonedSourcePackagesDirPath', args.output / 'SourcePackages', '-packageCachePath', args.output / 'PackageCache',
                '-disableAutomaticPackageResolution',
                '-skipPackageUpdates', '-parallel-testing-enabled', 'NO', 'CODE_SIGNING_ALLOWED=YES',
                'CODE_SIGN_IDENTITY=-', 'DEVELOPMENT_TEAM=']
        report['compile'] = 'started'
        commands.run(base + ['-resultBundlePath', args.output / 'compile.xcresult', 'build-for-testing'], timeout=300)
        report['compile'] = 'passed'
        app = args.output / 'DerivedData/Build/Products/Release' / (SCHEME + '.app')
        report['app_files'] = inventory(app)
        report['signing'] = observe_signing(commands, app)
        report['linked_images'] = commands.run(['/usr/bin/otool', '-L', app / 'Contents/MacOS' / SCHEME])
        if not args.build_only:
            report['target'] = 'started'
            commands.run(base + ['-resultBundlePath', args.output / 'tests.xcresult', 'test-without-building'], timeout=240)
            summary = json.loads(commands.run(['/usr/bin/xcrun', 'xcresulttool', 'get', 'test-results', 'summary',
                                               '--path', args.output / 'tests.xcresult']))
            report['xctest_summary'] = summary
            if summary.get('result') != 'Passed' or summary.get('passedTests') != 1 or summary.get('failedTests') != 0 or summary.get('skippedTests') != 0:
                raise ValueError('actual XCTest is not one complete passing test')
            raw = args.output / 'target-evidence.jsonl'
            report['observations'] = inspect_frames(raw.read_text(), nonce, copied_candidate['identity'])
            report['raw_log'] = reference(raw)
            report['target'] = 'passed'
            report['owner_close'] = 'confirmed'
        # Check copied consumption inputs, upstream public inputs, Lab implementation and tools again.
        if inventory(project) != report['consumer_inputs'] or source_inputs() != report['lab_inputs']:
            raise ValueError('frozen consumer/source changed during verification')
        admit_package(args.package, args.package_pin, args.expected_pin_sha256)
        admit_candidate(args.candidate, args.expected_candidate_digest)
        verify_tools(report['tools'])
        if commands.run(['/usr/bin/git', '-C', ROOT, 'rev-parse', 'HEAD']).strip() != report['lab_revision']:
            raise ValueError('Lab revision changed during verification')
        report['result'] = 'compiled-only' if args.build_only else ('development-passed' if report['provisional'] else 'passed')
    except Exception as error:
        report['error'] = str(error)
        for stage in ('compile', 'target'):
            if report[stage] == 'started':
                report[stage] = 'failed'
    finally:
        report.update(cleanup_execution(commands, args.output / 'target-evidence.jsonl', nonce, app))
        if 'cleanup_error' in report or 'xctest_runner_cleanup_error' in report:
            report['result'] = 'failed'
        if not args.build_only and report['result'] in ('passed', 'development-passed'):
            cleanup = report['cleanup']
            if cleanup['state'] != 'exited' or cleanup['forced']:
                report['cleanup_error'] = 'normal application exit was not independently confirmed'
                report['result'] = 'failed'
            elif cleanup['pid'] != report['observations']['pid']:
                report['cleanup_error'] = 'native evidence differs from the owned application process'
                report['result'] = 'failed'
        report['commands'] = commands.records
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report.get(key) for key in ('result', 'compile', 'target', 'cleanup', 'error', 'cleanup_error')}))
    return 0 if report['result'] in ('passed', 'development-passed', 'compiled-only') else 1


if __name__ == '__main__':
    raise SystemExit(main())
