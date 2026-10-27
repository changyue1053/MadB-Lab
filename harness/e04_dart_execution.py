"""Bounded Dart processes and fresh offline dependency installation for E04."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tarfile
import time
import zipfile

from candidate import CandidateError, file_digest, logical_path
from e04_dart_candidate import inventory
from l02_reports import CommandFailure, file_reference

PACKAGE_NAME = re.compile(r'[a-z][a-z0-9_]*\Z')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z')
OUTPUT_LIMIT = 8 * 1024 * 1024
DRAIN_TIMEOUT = 0.25
REAP_TIMEOUT = 0.25


class _OutputDrain:
    """Own both pipes, cap captured bytes and never wait beyond a deadline."""
    def __init__(self, process):
        self.selector = selectors.DefaultSelector()
        self.streams = {'stdout': process.stdout, 'stderr': process.stderr}
        self.buffers = {name: bytearray() for name in self.streams}
        self.captured = 0
        self.discarded = 0
        self.limited = False
        for name, stream in self.streams.items():
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, name)

    def pump(self, deadline, *, capture=True):
        while self.selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            for key, _ in self.selector.select(min(remaining, 0.05)):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    self.selector.unregister(key.fileobj)
                    key.fileobj.close()
                elif capture:
                    available = OUTPUT_LIMIT - self.captured
                    self.buffers[key.data].extend(chunk[:available])
                    self.captured += min(len(chunk), available)
                    if len(chunk) > available:
                        self.limited = True
                        return False
                else:
                    self.discarded += len(chunk)
        return True

    @property
    def complete(self):
        return not self.selector.get_map()

    def close(self):
        self.selector.close()
        for stream in self.streams.values():
            if not stream.closed:
                stream.close()


def _stop_and_observe(process, drain, value):
    """A signal requests termination; only separately observed facts are recorded."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
        value['watchdog_killed'] = True
    except ProcessLookupError:
        value['group_signal_missing'] = True
    if drain is not None:
        drain.pump(time.monotonic() + DRAIN_TIMEOUT, capture=False)
    try:
        process.wait(timeout=REAP_TIMEOUT)
    except subprocess.TimeoutExpired:
        return
    value.update(exit_code=process.returncode, reaped=True)


class Commands:
    def __init__(self, output):
        self.output = output
        self.logs = []
        self.cleanup_confirmed = True
        self.pending_processes = []
        for name in ('home', 'tmp', 'pub-cache', 'logs'):
            (output / name).mkdir()
        self.environment = {'HOME': str(output / 'home'), 'TMPDIR': str(output / 'tmp'),
                            'PUB_CACHE': str(output / 'pub-cache'), 'PATH': '/usr/bin:/bin',
                            'LC_ALL': 'C', 'LANG': 'C', 'DART_SUPPRESS_ANALYTICS': 'true',
                            'CI': 'true', 'PUB_ENVIRONMENT': 'madb-lab-e04-offline'}

    def run(self, argv, *, cwd, timeout=60):
        command = [str(item) for item in argv]
        path = self.output / 'logs' / f'{len(self.logs) + 1:03d}.json'
        start = time.monotonic_ns()
        process = None
        drain = None
        stopped = False
        value = {'argv': command, 'cwd': str(cwd), 'environment': dict(self.environment),
                 'pid': None, 'exit_code': None, 'timeout': False, 'duration_ns': 0,
                 'stdout': '', 'stderr': '', 'reaped': False, 'watchdog_killed': False,
                 'pipes_drained': False, 'capture_complete': False, 'output_limit_exceeded': False,
                 'process_cleanup': 'not-confirmed', 'drain_timeout_seconds': DRAIN_TIMEOUT,
                 'reap_timeout_seconds': REAP_TIMEOUT, 'output_limit_bytes': OUTPUT_LIMIT}
        try:
            process = subprocess.Popen(command, cwd=cwd, env=self.environment,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            value['pid'] = process.pid
            deadline = time.monotonic() + timeout
            drain = _OutputDrain(process)
            complete = drain.pump(deadline)
            value['output_limit_exceeded'] = drain.limited
            if complete:
                try:
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    complete = False
            if not complete:
                value['timeout'] = not drain.limited
                _stop_and_observe(process, drain, value)
                stopped = True
            else:
                value.update(exit_code=process.returncode, reaped=True)
                value['process_cleanup'] = 'leader-reaped-pipes-drained'
        except BaseException as error:
            if process is not None and not stopped:
                _stop_and_observe(process, drain, value)
            value['exception'] = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            if drain is not None:
                value['pipes_drained'] = drain.complete
                value['capture_complete'] = drain.complete and not drain.limited and not drain.discarded
                value['discarded_drain_bytes'] = drain.discarded
                for name, buffer in drain.buffers.items():
                    data = bytes(buffer)
                    value[name + '_bytes'] = {'sha256': file_digest(data), 'size': len(data),
                                              'complete': value['capture_complete']}
                    # Keep a bounded exact byte representation for invalid UTF-8 too.
                    try:
                        value[name] = data.decode('utf-8')
                    except UnicodeDecodeError:
                        value[name + '_hex'] = data.hex()
                        value['invalid_utf8'] = True
                drain.close()
            if process is not None and not value['reaped']:
                self.pending_processes.append(process)
            if (value['process_cleanup'] != 'leader-reaped-pipes-drained'
                    or not value['pipes_drained'] or not value['reaped']):
                self.cleanup_confirmed = False
            value['duration_ns'] = time.monotonic_ns() - start
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            self.logs.append(file_reference(path, self.output))
        if (value['timeout'] or value['exit_code'] != 0 or value['output_limit_exceeded']
                or not value['capture_complete'] or value.get('invalid_utf8')):
            raise CommandFailure(path, value)
        return value, self.logs[-1]


def bind_sdk(sdk, archive, digest):
    """Compare every installed SDK byte to the independently pinned official ZIP."""
    data = archive.read_bytes()
    if file_digest(data) != digest:
        raise CandidateError('ArtifactMismatch', 'Dart SDK archive differs from independent pin')
    expected = {}
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            if not item.filename.startswith('dart-sdk/'):
                raise CandidateError('ArtifactMismatch', 'unexpected Dart archive root')
            name = item.filename.removeprefix('dart-sdk/').rstrip('/')
            if not name:
                continue
            logical_path(name)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode) or (not item.is_dir() and stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise CandidateError('ArtifactMismatch', 'SDK archive has unsupported special entry')
            if item.is_dir():
                continue
            if name in expected:
                raise CandidateError('ArtifactMismatch', 'duplicate SDK archive member')
            payload = source.read(item)
            expected[name] = {'path': name, 'sha256': file_digest(payload), 'size': len(payload)}
    if inventory(sdk) != expected:
        raise CandidateError('ArtifactMismatch', 'installed Dart SDK is not the complete pinned archive')
    return {'archive': {'path': str(archive), 'sha256': digest, 'size': len(data)}, 'files': expected}


def install_dependency(cache, name, version, archive, digest):
    """Populate only this invocation's empty Pub cache from an exact official archive."""
    if not PACKAGE_NAME.fullmatch(name) or not VERSION.fullmatch(version):
        raise ValueError('dependency name/version must be exact stable Pub identities')
    data = archive.read_bytes()
    if file_digest(data) != digest:
        raise CandidateError('ArtifactMismatch', 'runtime dependency archive differs: ' + name)
    destination = cache / 'hosted/pub.dev' / (name + '-' + version)
    destination.mkdir(parents=True, exist_ok=False)
    expected = {}
    with tarfile.open(archive, mode='r:gz') as source:
        members = source.getmembers()
        if len(members) > 16384:
            raise ValueError('runtime dependency archive exceeds bounded inventory')
        spellings, total = set(), 0
        for item in members:
            name_in_archive = item.name.removeprefix('./').rstrip('/')
            if not name_in_archive:
                continue
            logical_path(name_in_archive)
            folded = name_in_archive.casefold()
            if folded in spellings or not (item.isdir() or item.isfile()):
                raise ValueError('duplicate/aliased/special runtime dependency member')
            spellings.add(folded)
            path = destination / name_in_archive
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            total += item.size
            if item.size < 0 or total > 128 * 1024 * 1024:
                raise ValueError('runtime dependency extraction exceeds byte budget')
            path.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(item) as stream:
                payload = stream.read(item.size + 1)
            if len(payload) != item.size:
                raise ValueError('runtime dependency archive size differs')
            with path.open('xb') as output:
                output.write(payload)
            expected[name_in_archive] = {'path': name_in_archive, 'sha256': file_digest(payload), 'size': len(payload)}
    if inventory(destination) != expected or 'pubspec.yaml' not in expected:
        raise ValueError('runtime dependency archive is not a complete Pub package')
    hashes = cache / 'hosted-hashes/pub.dev'
    hashes.mkdir(parents=True, exist_ok=True)
    (hashes / (name + '-' + version + '.sha256')).write_text(digest.removeprefix('sha256:'))
    return {'name': name, 'version': version, 'archive': {'path': str(archive), 'sha256': digest, 'size': len(data)},
            'directory': str(destination), 'files': expected}


def verify_dependencies(graph, installed):
    """Actual Pub resolution may not silently add a developer-cache package."""
    if not isinstance(graph, dict) or not isinstance(graph.get('packages'), list):
        raise ValueError('Dart pub deps did not return the actual package graph')
    packages = graph['packages']
    by_name = {row['name']: row for row in packages}
    expected = {item['name']: item for item in installed}
    if len(by_name) != len(packages) or len(expected) != len(installed):
        raise ValueError('duplicate actual/declaration package identity')
    if set(by_name) != set(expected) | {'madb_lab_e04_sync', 'madb_dart_ffi'}:
        raise ValueError('actual runtime dependency closure differs from the installed exact archive set')
    if {name: expected[name]['version'] for name in ('ffi', 'crypto')} != {'ffi': '2.2.0', 'crypto': '3.0.8'}:
        raise ValueError('ordinary SDK direct runtime dependencies differ from approved fixed inputs')
    for name, item in expected.items():
        if by_name[name].get('version') != item['version'] or by_name[name].get('source') != 'hosted':
            raise ValueError('resolved runtime dependency identity differs: ' + name)
        if inventory(Path(item['directory'])) != item['files']:
            raise ValueError('runtime dependency changed after offline resolution')
    return graph


def cleanup_private_images(root, *, process_cleanup_confirmed):
    """Only after all target processes exit; this is file cleanup, not Engine.close."""
    if not process_cleanup_confirmed:
        raise ValueError('process cleanup is not confirmed; owned temporary images are retained')
    before = inventory(root)
    # TMPDIR is newly created by this harness and never shared with another run.
    # Refuse links/special files instead of following another owner's path.
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    if any(root.iterdir()):
        raise ValueError('owned temporary image cleanup is incomplete')
    return {'before': before, 'after': {}, 'process_exit_precondition': True,
            'scope': 'only-this-run-TMPDIR; not-native-resource-release-proof'}
