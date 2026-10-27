"""Independent oracle and public-input checks for the L04 macOS native UI slice."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import uuid

from candidate import CandidateError, read_json
from c06_candidate import verify_candidate

SNAPSHOTS = (
    {'id': 'ascii', 'text': 'native page one', 'bytes': [0, 127, 128, 255]},
    {'id': 'after-1', 'text': 'after one', 'bytes': [255, 0]},
    {'id': 'unicode', 'text': '你好é🙂', 'bytes': [0, 195, 169, 255]},
    {'id': 'after-2', 'text': '页面退出后', 'bytes': [128, 1]},
    {'id': 'nul', 'text': 'left\0right', 'bytes': []},
    {'id': 'after-3', 'text': '', 'bytes': [0]},
)
PAGE_EVENTS = ('page-created', 'page-started', 'page-refreshed', 'duplicate-rejected',
               'page-value', 'page-disappeared', 'page-drained', 'model-release-observed',
               'after-page-value')
NATIVE_ZERO = ('activeOperations', 'queuedItems', 'inflightItems', 'retainedBytes', 'activeWaiters')
HEX = re.compile(r'[0-9a-f]{64}\Z')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def reference(path: Path) -> dict:
    data = path.read_bytes()
    return {'sha256': sha(data), 'size': len(data)}


def inventory(root: Path, *, modes=False) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ValueError('input root must be a real directory')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError('symlink/special input: ' + str(path))
        if path.is_file():
            item = reference(path)
            if modes:
                item['mode'] = path.stat().st_mode & 0o777
            result[path.relative_to(root).as_posix()] = item
    return result


def admit_package(package: Path, pin: Path, expected_digest: str) -> dict:
    if not HEX.fullmatch(expected_digest) or sha(pin.read_bytes()) != expected_digest:
        raise ValueError('public source pin differs from independent trust input')
    document = read_json(pin)
    expected = {}
    for item in document['files']:
        if set(item) != {'path', 'sha256', 'size', 'mode'} or item['path'] in expected:
            raise ValueError('public source pin entry is invalid or duplicated')
        expected[item['path']] = {key: item[key] for key in ('sha256', 'size', 'mode')}
    required = {'Package.swift', 'LICENSE', 'NOTICE', 'Sources/MadBObservation/MadBStateModel.swift',
                'Sources/MadBObservation/MadBStateSource.swift', 'Integration/SKIE/MadBSkieStateSource.swift'}
    if not required <= set(expected) or inventory(package, modes=True) != expected:
        raise ValueError('public source package bytes/modes differ from exact inventory')
    if not re.fullmatch(r'[0-9a-f]{40}', document.get('product_revision', '')):
        raise ValueError('public source supplement needs its exact producer revision')
    return document


def admit_candidate(root: Path, expected_digest: str) -> dict:
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', expected_digest):
        raise ValueError('expected candidate must be an independently pinned digest')
    selected = verify_candidate(root, 'swift-kotlin')
    if selected['manifest']['candidate_digest'] != expected_digest:
        raise CandidateError('ArtifactMismatch', 'candidate differs from independent trust input')
    if selected['provenance'].get('provisional', False):
        raise CandidateError('ArtifactMismatch', 'provisional native candidate cannot enter this slice')
    required = {'framework/MadBSkie.framework/MadBSkie', 'swift/MadBSkieConcurrency.swift'}
    if not required <= {item['path'] for item in selected['manifest']['files']}:
        raise CandidateError('ArtifactMismatch', 'missing public SKIE artifacts')
    return selected


def snapshot(index: int) -> dict:
    return {**SNAPSHOTS[index - 1], 'sequence': None, 'phase': 'open'}


def display(index: int) -> str:
    value = SNAPSHOTS[index - 1]
    return value['id'] + '|' + value['text'].encode().hex() + '|' + bytes(value['bytes']).hex()


def _require(condition: bool, message: str):
    if not condition:
        raise ValueError(message)


def _integer(value, label):
    _require(type(value) is int and value >= 0, 'invalid count: ' + label)
    return value


def _resources(row: dict, subscriptions: int, *, closed=False):
    native = row.get('native', {})
    _require(set(native) == set(NATIVE_ZERO) | {'activeSubscriptions', 'closed'}, 'native statistic fields differ')
    _require(all(_integer(native[key], key) == 0 for key in NATIVE_ZERO), 'native work/payload/waiter not drained')
    _require(_integer(native['activeSubscriptions'], 'activeSubscriptions') == subscriptions,
             'native subscription count differs')
    _require(native['closed'] is closed, 'native owner close state differs')


def inspect_frames(text: str, nonce: str, identity: dict) -> dict:
    """Fixed independent expectations; no expected values are read from the app."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, 'duplicate frame key')
            result[key] = value
        return result
    rows = [json.loads(line, object_pairs_hook=unique) for line in text.splitlines()]
    _require(len(rows) == 32, 'native UI frame count differs')
    pids = {row.get('pid') for row in rows}
    _require(len(pids) == 1 and all(type(pid) is int and pid > 0 for pid in pids), 'trace PID differs')
    for row in rows:
        _require(row.get('nonce') == nonce and row.get('mainThread') is True, 'nonce/main-thread observation differs')
        _require(row.get('profile') == identity['profile_digest'] and row.get('interface') == identity['interface_digest'],
                 'loaded native identity differs')
        for key in ('createdPages', 'drainedPages', 'releasedPages', 'pageFactories', 'ordinaryDeliveries', 'publishedIndex'):
            _integer(row.get(key), key)
        native = row.get('native', {})
        _require(set(native) == set(NATIVE_ZERO) | {'activeSubscriptions', 'closed'}, 'native statistic fields differ')
        _require(type(native['closed']) is bool, 'native close observation must be boolean')
        for key in (*NATIVE_ZERO, 'activeSubscriptions'):
            _integer(native[key], key)
        for key in ('ordinarySnapshot', 'pageSnapshot'):
            value = row.get(key)
            if value is not None:
                _require(isinstance(value, dict) and set(value) == {'id', 'text', 'bytes', 'sequence', 'phase'},
                         'snapshot shape differs')
                _require(all(type(value[field]) is str for field in ('id', 'text', 'phase'))
                         and value['sequence'] is None and isinstance(value['bytes'], list)
                         and all(type(octet) is int and 0 <= octet <= 255 for octet in value['bytes']),
                         'snapshot value types differ')
        _require(row.get('native', {}).get('closed') is False or row['event'] in ('owner-closed', 'application-terminated'),
                 'page prematurely closed shared native owner')
    _require([row['event'] for row in rows[:2]] == ['bootstrap-verified', 'owner-started'], 'bootstrap/start boundaries differ')
    _require(rows[0].get('wrongProfileCode') == 'ProfileMismatch', 'wrong profile did not produce exact typed rejection')
    _resources(rows[0], 0)
    _resources(rows[1], 1)
    _require(rows[1].get('ordinarySnapshot') is None, 'ordinary subscription invented initial replay')
    for row in rows[:2]:
        _require(all(row[key] == 0 for key in ('createdPages', 'drainedPages', 'releasedPages', 'pageFactories', 'ordinaryDeliveries', 'publishedIndex')),
                 'registration/value occurred before explicit ordinary start')
    identities = set()
    for index in range(1, 4):
        group = rows[2 + (index - 1) * 9:2 + index * 9]
        _require(tuple(row['event'] for row in group) == PAGE_EVENTS, 'page lifecycle/action order differs')
        page = group[0].get('pageID')
        try:
            uuid.UUID(page)
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError('page identity is not a UUID') from error
        _require(page not in identities, 'page identity was reused')
        identities.add(page)
        _require(all(row.get('pageID') == page for row in group[:-1]), 'page identity changed within session')
        _require(all(row['createdPages'] == index for row in group), 'page creation count differs')
        _require(group[0]['pageFactories'] == index - 1, 'constructing page registered native source')
        _resources(group[0], 1)
        for row in group[1:]:
            _require(row['pageFactories'] == index, 'duplicate or missing native source factory')
        for row in group[1:5]:
            _resources(row, 2)
            _require(row['drainedPages'] == index - 1 and row['releasedPages'] == index - 1, 'early drain/release claim')
        _require(group[1].get('pageSnapshot') is None, 'page start invented replay')
        _require(group[3].get('duplicateCode') == 'alreadyActive', 'duplicate start lacks exact rejection')
        value = group[4]
        _require(value.get('ordinarySnapshot') == snapshot(2 * index - 1) and value.get('pageSnapshot') == snapshot(2 * index - 1),
                 'ordinary/page value differs from independent input')
        _require(value['ordinaryDeliveries'] == 2 * index - 1 and value['publishedIndex'] == 2 * index - 1,
                 'native ordinary delivery/publication count differs')
        # Disappearance records the actual callback; requestStop itself is not a drain assertion.
        for row in group[6:]:
            _resources(row, 1)
            _require(row['drainedPages'] == index, 'page stop was not confirmed')
        _require(group[6].get('status') == 'stopped', 'page drain lacks stopped status')
        _require(group[6]['releasedPages'] == index - 1 and group[7]['releasedPages'] == index,
                 'model was not released after drain')
        after = group[-1]
        _require(after.get('ordinarySnapshot') == snapshot(2 * index) and after['ordinaryDeliveries'] == 2 * index,
                 'ordinary observer did not survive page exit')
        _require(after['publishedIndex'] == 2 * index and after['releasedPages'] == index,
                 'post-page publication/release observation differs')
    final = rows[-3:]
    _require([row['event'] for row in final] == ['ordinary-drained', 'owner-closed', 'application-terminated'],
             'explicit owner/application completion boundaries differ')
    for row in final:
        _resources(row, 0, closed=row['event'] != 'ordinary-drained')
        _require(all(row[key] == 3 for key in ('createdPages', 'drainedPages', 'releasedPages', 'pageFactories')),
                 'final page cleanup counts differ')
        _require(row['ordinaryDeliveries'] == 6 and row['publishedIndex'] == 6 and row.get('ordinarySnapshot') == snapshot(6),
                 'final ordinary observation differs')
    return {'frames': 32, 'pid': next(iter(pids)), 'fresh_swiftui_pages': 3,
            'ordinary_publications': 6, 'normal_owner_close': True, 'application_termination_callback': True}
