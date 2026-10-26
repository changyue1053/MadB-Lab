"""Host rejection checks for L05 evidence; this does not run an SDK or a device."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'harness'))
from l05_execution import BUNDLE, ExecutionError, L05Session, source_delivery
from l05_observations import NATIVE_EXPECTED, UI_EXPECTED, click_center, find_node, parse

NONCE = 'l05-test-run'
PID = '123'


def line(message, pid=PID):
    return '10-26 12:00:00.000 ' + pid + ' 123 I A00000/MadBL05Probe: ' + message


def evidence():
    messages = ['L05_CASE ' + NONCE + ' ' + name + ' ' + json.dumps(values)
                for name, values in {**NATIVE_EXPECTED, **UI_EXPECTED}.items()]
    messages.insert(len(NATIVE_EXPECTED), 'L05_NATIVE_COMPLETE ' + NONCE)
    messages.append('L05_COMPLETE ' + NONCE)
    return [line(message) for message in messages]


class ObservationTests(unittest.TestCase):
    def parsed(self, lines, **kwargs):
        return parse('\n'.join(lines), nonce=NONCE, pid=PID, complete=True, **kwargs)

    def rejects(self, lines):
        result = self.parsed(lines)
        self.assertTrue(result['errors'])
        self.assertFalse(result['complete'])

    def test_full_native_and_ui_evidence(self):
        result = self.parsed(evidence())
        self.assertEqual(result['errors'], [])
        self.assertTrue(result['native_complete'])
        self.assertTrue(result['complete'])

    def test_partial_evidence_is_never_complete(self):
        result = parse(evidence()[0], nonce=NONCE, pid=PID)
        self.assertEqual(result['errors'], [])
        self.assertFalse(result['complete'])
        self.assertFalse(result['native_complete'])

    def test_requires_both_completions_and_all_frames(self):
        rows = evidence()
        for index in range(len(rows)):
            with self.subTest(missing=index):
                self.rejects(rows[:index] + rows[index + 1:])

    def test_rejects_duplicates(self):
        rows = evidence()
        for value in rows:
            with self.subTest(value=value):
                self.rejects(rows + [value])

    def test_rejects_wrong_process_or_missing_process(self):
        rows = evidence()
        self.rejects([rows[0].replace(' 123 123 ', ' 999 123 '), *rows[1:]])
        for pid in ('', '0', '123 124'):
            result = parse('\n'.join(rows), nonce=NONCE, pid=pid, complete=True)
            self.assertTrue(result['errors'])

    def test_rejects_target_failure_and_unknown_case(self):
        self.rejects(evidence() + [line('L05_FAILED ' + NONCE + ' injected')])
        self.rejects(evidence() + [line('L05_CASE ' + NONCE + ' extra [1]')])

    def test_rejects_malformed_and_inexact_values(self):
        rows = evidence()
        for value in ('[true,1,11]', '[1.0,1,11]', '[1,1,12]', 'null', '{', '[]'):
            with self.subTest(value=value):
                self.rejects([line('L05_CASE ' + NONCE + ' native-two-observers ' + value), *rows[1:]])

    def test_rejects_case_reordering(self):
        rows = evidence()
        rows[0], rows[1] = rows[1], rows[0]
        self.rejects(rows)

    def test_rejects_completion_with_suffix(self):
        rows = evidence()
        self.rejects(rows[:-1] + [rows[-1] + '-other-run'])

    def test_other_run_does_not_supply_missing_frames(self):
        self.rejects([row.replace(NONCE, 'another-run') for row in evidence()])


class SourceDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='madb-l05-source-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ('StateObservation.ets', 'ArkUIStateModel.ets', 'README.md', 'LICENSE', 'NOTICE'):
            (self.root / name).write_text('independent fixture ' + name)
        self.state = self.digest('StateObservation.ets')
        self.ui = self.digest('ArkUIStateModel.ets')
        self.inventory()

    def digest(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def inventory(self):
        rows = [{'path': p.name, 'sha256': self.digest(p.name), 'size': p.stat().st_size}
                for p in self.root.iterdir() if p.name != 'source-inputs.json']
        (self.root / 'source-inputs.json').write_text(json.dumps({'files': rows}))

    def verify(self):
        return source_delivery(self.root, self.state, self.ui)

    def test_accepts_exact_independently_trusted_sources(self):
        self.assertEqual(self.verify()['files']['StateObservation.ets']['sha256'], self.state)

    def test_rejects_self_consistent_untrusted_change(self):
        (self.root / 'StateObservation.ets').write_text('changed source')
        self.inventory()
        with self.assertRaisesRegex(ValueError, 'independently trusted'):
            self.verify()

    def test_rejects_unchanged_sources_with_stale_notice_inventory(self):
        (self.root / 'NOTICE').write_text('changed notice')
        with self.assertRaisesRegex(ValueError, 'inventory/bytes'):
            self.verify()

    def test_rejects_unlisted_file(self):
        (self.root / 'unlisted').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            self.verify()

    def test_rejects_symlink(self):
        (self.root / 'NOTICE').unlink()
        (self.root / 'NOTICE').symlink_to(self.root / 'LICENSE')
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            self.verify()

    def test_rejects_malformed_inventory(self):
        for value in ([], {'files': [None] * 5}, {'files': []}):
            with self.subTest(value=value):
                (self.root / 'source-inputs.json').write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, 'invalid public source inventory'):
                    self.verify()


class UiEvidenceTests(unittest.TestCase):
    def test_requires_unique_exact_node(self):
        row = {'attributes': {'id': 'l05-value', 'text': 'UI-1'}}
        self.assertEqual(find_node({'children': [row]}, 'l05-value')['text'], 'UI-1')
        for layout in ({}, {'children': [row, row]}):
            with self.assertRaises(ValueError):
                find_node(layout, 'l05-value')

    def test_click_uses_valid_observed_bounds(self):
        self.assertEqual(click_center({'bounds': '[10,20][30,60]'}), (20, 40))
        for bounds in ('', '10,20,30,60', '[-1,2][3,4]', '[4,2][3,4]', '[1,2][3,2]', None):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                click_center({'bounds': bounds})


class CleanupTests(unittest.TestCase):
    def session(self, responses):
        directory = tempfile.TemporaryDirectory(prefix='madb-l05-cleanup-test-')
        self.addCleanup(directory.cleanup)
        session = object.__new__(L05Session)
        session.args = SimpleNamespace(output=Path(directory.name))
        session.device_started = True
        session.calls = []
        def hdc(label, *arguments, **options):
            session.calls.append((label, arguments))
            return {'stdout': responses[label]}
        session.hdc = hdc
        return session

    def responses(self):
        return {'stop-own-probe': 'force stop process successfully.\n', 'own-pid-after': '',
                'uninstall-own-probe': '[Info]App uninstall path: msg:uninstall bundle successfully.\n'}

    def test_cleanup_requires_target_confirmation_and_only_own_bundle(self):
        session = self.session(self.responses())
        session.stop()
        self.assertTrue(session.stopped)
        self.assertEqual([args[-1] for _, args in session.calls], [BUNDLE] * 3)
        self.assertTrue(json.loads((session.args.output / 'device-after.json').read_text())['uninstalled'])

    def test_zero_exit_without_semantic_success_is_not_cleanup(self):
        for label in ('stop-own-probe', 'uninstall-own-probe'):
            with self.subTest(label=label):
                values = self.responses()
                values[label] = 'error: device rejected request'
                session = self.session(values)
                with self.assertRaises(ExecutionError):
                    session.stop()
                self.assertFalse((session.args.output / 'device-after.json').exists())

    def test_remaining_process_prevents_cleanup_pass(self):
        values = self.responses()
        values['own-pid-after'] = '123'
        session = self.session(values)
        with self.assertRaisesRegex(ExecutionError, 'remains'):
            session.stop()
        self.assertFalse((session.args.output / 'device-after.json').exists())


if __name__ == '__main__':
    unittest.main()
