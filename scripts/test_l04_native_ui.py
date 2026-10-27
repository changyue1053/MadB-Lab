"""Independent negative checks for L04 native UI evidence admission; no UI execution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'harness'))
from l04_native_ui import admit_package, inspect_frames, inventory, sha

IDENTITY = {'profile_digest': 'sha256:' + '1' * 64, 'interface_digest': 'sha256:' + '2' * 64}
VALUES = [
    ('ascii', 'native page one', [0, 127, 128, 255]), ('after-1', 'after one', [255, 0]),
    ('unicode', '你好é🙂', [0, 195, 169, 255]), ('after-2', '页面退出后', [128, 1]),
    ('nul', 'left\0right', []), ('after-3', '', [0]),
]


def sample(index):
    name, text, octets = VALUES[index - 1]
    return {'id': name, 'text': text, 'bytes': octets, 'sequence': None, 'phase': 'open'}


def synthetic_frames():
    rows = []
    state = {'nonce': 'nonce', 'pid': 1234, 'mainThread': True, 'profile': IDENTITY['profile_digest'],
             'interface': IDENTITY['interface_digest'], 'pageID': None, 'pageSnapshot': None,
             'ordinarySnapshot': None, 'status': 'idle', 'createdPages': 0, 'drainedPages': 0,
             'releasedPages': 0, 'pageFactories': 0, 'ordinaryDeliveries': 0, 'publishedIndex': 0,
             'native': {'activeSubscriptions': 0, 'activeOperations': 0, 'queuedItems': 0,
                        'inflightItems': 0, 'retainedBytes': 0, 'activeWaiters': 0, 'closed': False}}
    def emit(event):
        rows.append(deepcopy({**state, 'event': event}))
    state['wrongProfileCode'] = 'ProfileMismatch'
    emit('bootstrap-verified')
    state['native']['activeSubscriptions'] = 1
    emit('owner-started')
    for index in range(1, 4):
        state['pageID'] = str(uuid.UUID(int=index))
        state['createdPages'] = index
        state['pageSnapshot'] = None
        state['status'] = 'idle'
        emit('page-created')
        state['pageFactories'] = index
        state['native']['activeSubscriptions'] = 2
        state['status'] = 'observing'
        emit('page-started'); emit('page-refreshed')
        state['duplicateCode'] = 'alreadyActive'
        emit('duplicate-rejected')
        state['pageSnapshot'] = sample(index * 2 - 1)
        state['ordinarySnapshot'] = sample(index * 2 - 1)
        state['ordinaryDeliveries'] = state['publishedIndex'] = index * 2 - 1
        emit('page-value')
        state['status'] = 'stopping'
        emit('page-disappeared')
        state['native']['activeSubscriptions'] = 1
        state['drainedPages'] = index
        state['status'] = 'stopped'
        emit('page-drained')
        state['releasedPages'] = index
        emit('model-release-observed')
        state['ordinarySnapshot'] = sample(index * 2)
        state['ordinaryDeliveries'] = state['publishedIndex'] = index * 2
        emit('after-page-value')
    state['native']['activeSubscriptions'] = 0
    emit('ordinary-drained')
    state['native']['closed'] = True
    emit('owner-closed'); emit('application-terminated')
    return rows


class EvidenceTests(unittest.TestCase):
    def inspect(self, rows):
        return inspect_frames('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows), 'nonce', IDENTITY)

    def test_complete_synthetic_observation(self):
        self.assertEqual(self.inspect(synthetic_frames())['fresh_swiftui_pages'], 3)

    def test_reject_each_resource_leak(self):
        for field in ('activeOperations', 'queuedItems', 'inflightItems', 'retainedBytes', 'activeWaiters', 'activeSubscriptions'):
            with self.subTest(field=field):
                rows = synthetic_frames(); rows[-2]['native'][field] = 1
                with self.assertRaises(ValueError): self.inspect(rows)

    def test_exact_independent_values(self):
        for index in (6, 15, 24):
            with self.subTest(index=index):
                rows = synthetic_frames(); rows[index]['pageSnapshot']['text'] += 'wrong'
                with self.assertRaisesRegex(ValueError, 'value differs'): self.inspect(rows)

    def test_ordinary_survives_each_page(self):
        rows = synthetic_frames(); rows[10]['ordinarySnapshot'] = sample(1)
        with self.assertRaisesRegex(ValueError, 'survive'): self.inspect(rows)

    def test_drain_precedes_model_release(self):
        rows = synthetic_frames(); rows[8], rows[9] = rows[9], rows[8]
        with self.assertRaisesRegex(ValueError, 'order'): self.inspect(rows)

    def test_page_cannot_close_shared_engine(self):
        rows = synthetic_frames(); rows[8]['native']['closed'] = True
        with self.assertRaisesRegex(ValueError, 'prematurely'): self.inspect(rows)

    def test_duplicate_start_cannot_resubscribe(self):
        rows = synthetic_frames(); rows[5]['pageFactories'] = 2
        with self.assertRaisesRegex(ValueError, 'factory'): self.inspect(rows)

    def test_profile_rejection_must_be_typed(self):
        rows = synthetic_frames(); rows[0]['wrongProfileCode'] = 'any failure'
        with self.assertRaisesRegex(ValueError, 'typed rejection'): self.inspect(rows)

    def test_bound_identity_nonce_thread_and_pid(self):
        for key, value in [('profile', 'wrong'), ('interface', 'wrong'), ('nonce', 'wrong'), ('mainThread', False), ('pid', 8)]:
            with self.subTest(key=key):
                rows = synthetic_frames(); rows[7][key] = value
                with self.assertRaises(ValueError): self.inspect(rows)

    def test_missing_termination_is_not_success(self):
        rows = synthetic_frames()[:-1]
        with self.assertRaisesRegex(ValueError, 'frame count'): self.inspect(rows)

    def test_no_initial_replay(self):
        rows = synthetic_frames(); rows[3]['pageSnapshot'] = sample(1)
        with self.assertRaisesRegex(ValueError, 'replay'): self.inspect(rows)

    def test_boolean_is_not_resource_count(self):
        rows = synthetic_frames(); rows[8]['native']['activeSubscriptions'] = True
        with self.assertRaisesRegex(ValueError, 'invalid count'): self.inspect(rows)

    def test_boolean_is_not_snapshot_octet(self):
        rows = synthetic_frames(); rows[6]['pageSnapshot']['bytes'][0] = False
        with self.assertRaisesRegex(ValueError, 'value types'): self.inspect(rows)

    def test_duplicate_json_keys_rejected(self):
        text = '\n'.join(json.dumps(row) for row in synthetic_frames())
        text = text.replace('"pid": 1234', '"pid": 1234, "pid": 1234', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate'): inspect_frames(text, 'nonce', IDENTITY)


class CleanupTests(unittest.TestCase):
    def test_unknown_live_pid_identity_is_not_signalled_or_called_exited(self):
        from verify_l04_native_ui import cleanup_application
        class Commands:
            def run(self, argv, **kwargs):
                return '/unrelated/application\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); log = root / 'trace.jsonl'
            executable = root / 'app/Contents/MacOS/MadBL04NativeUI'
            executable.parent.mkdir(parents=True); executable.write_bytes(b'owned executable')
            Path(str(log) + '.process.json').write_text(json.dumps({'nonce': 'owned', 'pid': 1234,
                'executablePath': str((root / 'app/Contents/MacOS/MadBL04NativeUI').resolve())}))
            with patch('verify_l04_native_ui.os.kill') as kill:
                with self.assertRaisesRegex(RuntimeError, 'unconfirmed executable'):
                    cleanup_application(Commands(), log, 'owned', root / 'app')
                kill.assert_not_called()

    def test_missing_or_wrong_receipt_cannot_claim_process_cleanup(self):
        from verify_l04_native_ui import cleanup_application
        class Commands:
            def owned_processes(self, executables):
                return []
            def run(self, argv, **kwargs):
                raise AssertionError('untrusted PID must not be queried')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); log = root / 'trace.jsonl'
            result = cleanup_application(Commands(), log, 'owned', root / 'app')
            self.assertEqual(result['state'], 'not_observed')
            receipt = Path(str(log) + '.process.json')
            receipt.write_text(json.dumps({'nonce': 'wrong', 'pid': 1234,
                'executablePath': str((root / 'app/Contents/MacOS/MadBL04NativeUI').resolve())}))
            with patch('verify_l04_native_ui.os.kill') as kill:
                with self.assertRaisesRegex(ValueError, 'bound'):
                    cleanup_application(Commands(), log, 'owned', root / 'app')
                kill.assert_not_called()

    def test_receipt_absolute_alias_resolves_to_exact_owned_image(self):
        from verify_l04_native_ui import cleanup_application
        class Commands:
            def run(self, argv, **kwargs): return ''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); app = root / 'app'; log = root / 'trace.jsonl'
            executable = app / 'Contents/MacOS/MadBL04NativeUI'
            executable.parent.mkdir(parents=True); executable.write_bytes(b'owned')
            alias = root / 'alias'; alias.symlink_to(app, target_is_directory=True)
            Path(str(log) + '.process.json').write_text(json.dumps({'nonce': 'owned', 'pid': 1234,
                'executablePath': str(alias / 'Contents/MacOS/MadBL04NativeUI')}))
            with patch('verify_l04_native_ui.os.kill') as kill:
                result = cleanup_application(Commands(), log, 'owned', app)
                self.assertEqual(result['state'], 'exited'); self.assertFalse(result['forced'])
                kill.assert_not_called()

    def test_receipt_relative_missing_and_other_same_bytes_image_rejected(self):
        from verify_l04_native_ui import cleanup_application
        class Commands:
            def run(self, argv, **kwargs): raise AssertionError('untrusted PID must not be queried')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); app = root / 'app'; log = root / 'trace.jsonl'
            executable = app / 'Contents/MacOS/MadBL04NativeUI'
            executable.parent.mkdir(parents=True); executable.write_bytes(b'same bytes')
            other = root / 'other'; other.write_bytes(executable.read_bytes())
            alias = root / 'wrong-alias'; alias.symlink_to(other)
            for path in ('app/Contents/MacOS/MadBL04NativeUI', str(root / 'missing'), str(other), str(alias), 42):
                Path(str(log) + '.process.json').write_text(json.dumps({'nonce': 'owned', 'pid': 1234,
                    'executablePath': path}))
                with self.subTest(path=path), patch('verify_l04_native_ui.os.kill') as kill:
                    with self.assertRaises(ValueError): cleanup_application(Commands(), log, 'owned', app)
                    kill.assert_not_called()

    def test_launcher_finishes_before_final_application_cleanup(self):
        from verify_l04_native_ui import cleanup_execution
        events = []
        state = {'app_started': False}
        def runner(*args):
            events.append('runner')
            state['app_started'] = True  # Launch crosses the controller stop window.
            return {'state': 'exited'}
        def application(*args):
            events.append('application')
            self.assertTrue(state['app_started'])
            state['app_started'] = False
            return {'state': 'exited', 'forced': True}
        with patch('verify_l04_native_ui.cleanup_test_runner', side_effect=runner), \
                patch('verify_l04_native_ui.cleanup_application', side_effect=application):
            result = cleanup_execution(None, Path('trace'), 'nonce', Path('app'))
        self.assertEqual(events, ['runner', 'application'])
        self.assertFalse(state['app_started'])
        self.assertTrue(result['cleanup']['forced'])  # Cannot claim normal native exit.

    def test_launcher_cleanup_failure_does_not_skip_application(self):
        from verify_l04_native_ui import cleanup_execution
        with patch('verify_l04_native_ui.cleanup_test_runner', side_effect=RuntimeError('controller cleanup failed')), \
                patch('verify_l04_native_ui.cleanup_application', return_value={'state': 'exited'}) as application:
            result = cleanup_execution(None, Path('trace'), 'nonce', Path('app'))
            application.assert_called_once()
            self.assertEqual(result['xctest_runner_cleanup_error'], 'controller cleanup failed')

    def test_exact_output_image_filter_rejects_similar_names(self):
        from verify_l04_native_ui import select_owned_processes
        wanted = '/private/tmp/owned/Runner.app/Contents/MacOS/Runner'
        text = '17 /other/Runner.app/Contents/MacOS/Runner\n18 ' + wanted + '\n19 Runner\n'
        self.assertEqual(select_owned_processes(text, {wanted}), [{'pid': 18, 'executablePath': wanted}])

    def test_xctest_runner_cleanup_even_without_application_receipt(self):
        from verify_l04_native_ui import cleanup_test_runner
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary).resolve() / 'App.app'
            expected = str(app.parent / 'MadBL04NativeUITests-Runner.app/Contents/MacOS/MadBL04NativeUITests-Runner')
            class Commands:
                def __init__(self): self.inventories = 0; self.probes = 0
                def owned_processes(self, executables):
                    self.inventories += 1
                    if executables != {expected}: raise AssertionError('wrong owned image')
                    return [{'pid': 1234, 'executablePath': expected}] if self.inventories == 1 else []
                def run(self, argv, **kwargs):
                    self.probes += 1
                    return expected if self.probes == 1 else ''
            with patch('verify_l04_native_ui.os.kill') as kill:
                result = cleanup_test_runner(Commands(), app)
                self.assertEqual(result['state'], 'exited')
                self.assertTrue(result['processes'][0]['forced'])
                self.assertEqual(kill.call_count, 1)

    def test_absent_owned_pid_is_observed_without_signal(self):
        from verify_l04_native_ui import cleanup_application
        class Commands:
            def run(self, argv, **kwargs):
                return ''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); log = root / 'trace.jsonl'
            executable = root / 'app/Contents/MacOS/MadBL04NativeUI'
            executable.parent.mkdir(parents=True); executable.write_bytes(b'owned executable')
            Path(str(log) + '.process.json').write_text(json.dumps({'nonce': 'owned', 'pid': 1234,
                'executablePath': str((root / 'app/Contents/MacOS/MadBL04NativeUI').resolve())}))
            with patch('verify_l04_native_ui.os.kill') as kill:
                result = cleanup_application(Commands(), log, 'owned', root / 'app')
                self.assertEqual({key: result[key] for key in ('state', 'forced', 'pid')},
                                 {'state': 'exited', 'forced': False, 'pid': 1234})
                kill.assert_not_called()


class SigningTests(unittest.TestCase):
    def observe(self, entitlements, details='Signature=adhoc\nTeamIdentifier=not set\n'):
        import plistlib
        sys.path.insert(0, str(ROOT / 'scripts'))
        import verify_l04_native_ui as runner
        class Commands:
            def run(self, argv, **kwargs):
                if '--entitlements' in argv:
                    return plistlib.dumps(entitlements).decode()
                return details if kwargs.get('include_stderr') else ''
        return runner.observe_signing(Commands(), Path('/private/output/MadBL04NativeUI.app'))

    def test_xcode_ad_hoc_receipts_keep_distribution_unclaimed(self):
        result = self.observe({'com.apple.security.get-task-allow': True})
        self.assertEqual(result['mode'], 'local-ad-hoc-development-only')
        self.assertIs(result['distribution_signature'], False)
        self.assertEqual(len(result['products']), 3)

    def test_absent_or_false_development_task_entitlement_rejected(self):
        for entitlements in ({}, {'com.apple.security.get-task-allow': False}):
            with self.subTest(entitlements=entitlements), self.assertRaisesRegex(ValueError, 'entitlement is absent'):
                self.observe(entitlements)

    def test_developer_or_other_signature_cannot_claim_ad_hoc(self):
        with self.assertRaisesRegex(ValueError, 'ad-hoc signature'):
            self.observe({'com.apple.security.get-task-allow': True}, 'Signature size=4442\nTeamIdentifier=EXAMPLE\n')


class SchemeTests(unittest.TestCase):
    def test_macos_runner_uses_observed_xcode_default_launcher(self):
        scheme = ET.parse(ROOT / 'consumers/swift/l04_native_ui/MadBL04NativeUI.xcscheme').getroot()
        # These are the actual Xcode 27 macOS autogenerated identities. The old
        # iOS-only blank/PosixSpawn override does not define this host recipe.
        for name in ('TestAction', 'LaunchAction'):
            action = scheme.find(name)
            self.assertEqual(action.get('selectedDebuggerIdentifier'), 'Xcode.DebuggerFoundation.Debugger.LLDB')
            self.assertEqual(action.get('selectedLauncherIdentifier'), 'Xcode.DebuggerFoundation.Launcher.LLDB')
            self.assertEqual(action.get('buildConfiguration'), 'Release')
        testable = scheme.find('TestAction/Testables/TestableReference')
        self.assertEqual(testable.get('skipped'), 'NO')
        self.assertEqual(testable.get('parallelizable'), 'NO')


class PublicSourceTests(unittest.TestCase):
    def test_pinned_public_inventory_and_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); package = root / 'package'; package.mkdir()
            for name in ('Package.swift', 'LICENSE', 'NOTICE', 'Sources/MadBObservation/MadBStateModel.swift',
                         'Sources/MadBObservation/MadBStateSource.swift', 'Integration/SKIE/MadBSkieStateSource.swift'):
                path = package / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(name)
            value = {'product_revision': '3' * 40,
                     'files': [{'path': path, **item} for path, item in inventory(package, modes=True).items()]}
            pin = root / 'pin.json'; pin.write_text(json.dumps(value)); digest = sha(pin.read_bytes())
            admit_package(package, pin, digest)
            with self.assertRaisesRegex(ValueError, 'trust'): admit_package(package, pin, '0' * 64)
            (package / 'extra.swift').write_text('untrusted')
            with self.assertRaisesRegex(ValueError, 'inventory'): admit_package(package, pin, digest)
            (package / 'extra.swift').unlink()
            (package / 'NOTICE').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'inventory'): admit_package(package, pin, digest)


if __name__ == '__main__':
    unittest.main()
