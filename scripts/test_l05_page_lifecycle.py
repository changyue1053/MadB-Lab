"""Synthetic L05 lifecycle parser/UI rejection tests; no SDK or device execution."""
from pathlib import Path
import json
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'harness'))
from l05_page_lifecycle_observations import EXPECTED, UI_EXPECTED, UI_PHASES, click_center, find_node, parse

NONCE, PID = 'l05-lifecycle-test', '123'


def line(message, *, pid=PID, tag='MadBL05Lifecycle'):
    return '10-26 12:00:00.000 ' + pid + ' 124 I A00000/' + tag + ': ' + message


def evidence():
    # Explicit independent transport fixture: neither imports consumer code nor
    # derives expected values from the SDK or the parser's EXPECTED dictionary.
    payloads = (
        ('page-created-1', [1]), ('page-attached-1', [1, 0]), ('page-published-1', [1, 11, 1]),
        ('page-destroyed-1', [1]), ('page-drained-1', [1]), ('after-destroy-published-1', [1, 12, 2, 101]),
        ('page-created-2', [2]), ('page-attached-2', [2, 0]), ('page-published-2', [2, 21, 3]),
        ('page-destroyed-2', [2]), ('page-drained-2', [2]), ('after-destroy-published-2', [2, 22, 4, 102]),
        ('page-created-3', [3]), ('page-attached-3', [3, 0]), ('page-published-3', [3, 31, 5]),
        ('page-destroyed-3', [3]), ('page-drained-3', [3]), ('after-destroy-published-3', [3, 32, 6, 103]),
        ('owner-closed', [3, 3, 6, 1]),
    )
    return [line('L05_LIFECYCLE_CASE ' + NONCE + ' ' + label + ' ' + json.dumps(values))
            for label, values in payloads] + [line('L05_LIFECYCLE_COMPLETE ' + NONCE)]


class LifecycleObservationsTests(unittest.TestCase):
    def parsed(self, rows, *, complete=True, **options):
        return parse('\n'.join(rows), nonce=options.get('nonce', NONCE), pid=options.get('pid', PID), complete=complete)

    def rejects(self, rows, **options):
        result = self.parsed(rows, **options)
        self.assertTrue(result['errors'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'failed')

    def test_exact_three_fresh_pages_and_final_owner(self):
        result = self.parsed(evidence())
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['frames'], EXPECTED)
        self.assertEqual(len(result['frames']), 19)
        self.assertTrue(result['complete'])
        self.assertFalse(result['certifies_l05'])

    def test_every_valid_prefix_stays_incomplete_without_completion(self):
        rows = evidence()
        for count in range(len(rows)):
            with self.subTest(count=count):
                result = self.parsed(rows[:count], complete=False)
                self.assertEqual(result['errors'], [])
                self.assertEqual(result['status'], 'incomplete')
                self.assertFalse(result['complete'])

    def test_each_missing_frame_or_completion_fails_final_verification(self):
        rows = evidence()
        for index in range(len(rows)):
            with self.subTest(index=index): self.rejects(rows[:index] + rows[index + 1:])

    def test_completion_cannot_be_early_or_duplicate_or_have_suffix(self):
        rows = evidence()
        for position in range(len(rows) - 1):
            with self.subTest(position=position):
                self.rejects(rows[:position] + [rows[-1]] + rows[position:-1], complete=False)
        for suffix in (' extra', ' ', '\t', '-other-run'):
            with self.subTest(suffix=suffix): self.rejects(rows[:-1] + [rows[-1] + suffix])
        self.rejects(rows + [rows[-1]], complete=False)

    def test_duplicate_unknown_and_after_completion_observations_fail(self):
        rows = evidence()
        for index, row in enumerate(rows[:-1]):
            with self.subTest(index=index):
                self.rejects(rows[:index + 1] + [row] + rows[index + 1:], complete=False)
        self.rejects(rows + [rows[0]], complete=False)
        self.rejects(rows[:-1] + [line('L05_LIFECYCLE_CASE ' + NONCE + ' unknown [1]'), rows[-1]])
        self.rejects(rows + [line('L05_LIFECYCLE_OTHER ' + NONCE)], complete=False)

    def test_all_adjacent_frame_reorders_fail(self):
        for index in range(len(evidence()) - 2):
            rows = evidence(); rows[index], rows[index + 1] = rows[index + 1], rows[index]
            with self.subTest(index=index): self.rejects(rows, complete=False)

    def test_every_numeric_observation_component_is_checked(self):
        for index, row in enumerate(evidence()[:-1]):
            label, encoded = row.split(' ' + NONCE + ' ', 1)[1].split(' ', 1)
            values = json.loads(encoded)
            for component in range(len(values)):
                wrong = values.copy(); wrong[component] += 1
                rows = evidence(); rows[index] = line('L05_LIFECYCLE_CASE ' + NONCE + ' ' + label + ' ' + json.dumps(wrong))
                with self.subTest(label=label, component=component): self.rejects(rows, complete=False)

    def test_malformed_arrays_and_non_integer_values_fail(self):
        for encoded in ('[true]', '[1.0]', 'null', '{}', '{', '[]', '[1, 0]', '[NaN]', '[Infinity]', '[1] suffix'):
            rows = evidence(); rows[0] = line('L05_LIFECYCLE_CASE ' + NONCE + ' page-created-1 ' + encoded)
            with self.subTest(encoded=encoded): self.rejects(rows, complete=False)
        self.rejects([line('L05_LIFECYCLE_CASE ' + NONCE)], complete=False)

    def test_exact_pid_nonce_tag_and_message_are_required(self):
        for pid in ('', '0', '123 124', '0123', '١٢٣', None):
            with self.subTest(pid=pid): self.rejects(evidence(), pid=pid)
        for nonce in ('', 'two words', 'newline\nnonce', None):
            with self.subTest(nonce=nonce): self.rejects(evidence(), nonce=nonce)
        rows = evidence()
        for changed in (rows[0].replace(' 123 124 ', ' 999 124 '),
                        rows[0].replace('/MadBL05Lifecycle:', '/OtherTag:'),
                        rows[0].replace(': L05_', ': prefix L05_'),
                        rows[0].split(': ', 1)[1]):
            self.rejects([changed, *rows[1:]], complete=False)

    def test_other_run_cannot_supply_evidence_but_is_ignored(self):
        alien = [row.replace(NONCE, NONCE + '-other') for row in evidence()]
        self.rejects(alien)
        self.rejects([alien[0], *evidence()[1:]])
        result = self.parsed(alien + evidence() + alien)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['lines']), len(evidence()))

    def test_explicit_target_failure_never_becomes_success(self):
        failure = line('L05_LIFECYCLE_FAILED ' + NONCE + ' close rejected')
        for rows in ([failure], [failure, *evidence()], [*evidence(), failure]):
            self.rejects(rows, complete=False)


class LifecycleUiTests(unittest.TestCase):
    def test_separate_ordered_hierarchy_expectations(self):
        phases = tuple(name + '_' + str(page) for page in (1, 2, 3)
                       for name in ('PAGE_READY', 'PAGE_PUBLISHED', 'AWAY_READY', 'AWAY_PUBLISHED')) + ('FINISHED',)
        self.assertEqual(UI_PHASES, phases)
        for page in (1, 2, 3):
            for phase, text in (('PAGE_READY', 'EMPTY'), ('PAGE_PUBLISHED', 'PAGE-' + str(page))):
                expected = UI_EXPECTED[phase + '_' + str(page)]
                self.assertEqual(expected['l05-life-value'], text)
                self.assertEqual(expected['l05-life-page-id'], str(page))
            self.assertEqual(UI_EXPECTED['AWAY_READY_' + str(page)]['l05-life-ordinary'], str(2 * page - 1))
            self.assertEqual(UI_EXPECTED['AWAY_PUBLISHED_' + str(page)]['l05-life-ordinary'], str(2 * page))
        self.assertEqual(UI_EXPECTED['FINISHED']['l05-life-ordinary'], '6')

    def test_ui_nodes_must_be_unique_and_click_bounds_real(self):
        node = {'attributes': {'id': 'l05-life-phase', 'text': 'PAGE_READY_1', 'bounds': '[10,20][50,80]'}}
        self.assertEqual(find_node(node, 'l05-life-phase')['text'], 'PAGE_READY_1')
        self.assertEqual(click_center(find_node(node, 'l05-life-phase')), (30, 50))
        for value in ({}, {'children': [node, node]}):
            with self.assertRaises(ValueError): find_node(value, 'l05-life-phase')
        for bounds in ('', None, '[1,2][1,3]', '[2,3][1,4]', '[-1,2][3,4]'):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError): click_center({'bounds': bounds})


class InputAndStageTests(unittest.TestCase):
    def verifier(self):
        import importlib.util
        path = Path(__file__).with_name('verify_l05_page_lifecycle.py')
        spec = importlib.util.spec_from_file_location('l05_lifecycle_verifier_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_actual_preflight_rules_are_bound(self):
        module = self.verifier()
        actual = module.code_snapshot()
        for name in ('.python-version', 'consumers/arkts/c07/requirements.json',
                     'docs/reference/REVISION', 'docs/reference/SHA256SUMS'):
            self.assertIn(name, actual)
        expected = module.preflight_inputs(module.ROOT)
        self.assertTrue(all(str(p.relative_to(module.ROOT)) in actual for p in expected))
        self.assertTrue(any(p.suffix == '.md' for p in expected))

    def test_preflight_closure_tracks_rule_change_and_ignores_build_cargo(self):
        import tempfile
        module = self.verifier()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            included = ['.python-version', 'consumers/arkts/c07/requirements.json',
                        'docs/reference/REVISION', 'docs/reference/SHA256SUMS',
                        'docs/reference/validation/example.md', 'consumer/Cargo.toml']
            excluded = ['target/Cargo.toml', '.venv/Cargo.toml', 'reports/a/Cargo.toml']
            for name in included + excluded:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            self.assertEqual(module.preflight_inputs(root), {root / name for name in included})
            def snapshot():
                return {str(p.relative_to(root)): module.file_digest(p.read_bytes()) for p in module.preflight_inputs(root)}
            before = snapshot()
            (root / 'consumers/arkts/c07/requirements.json').write_text('changed independent rule')
            after = snapshot()
            self.assertNotEqual(before, after)
            self.assertEqual([k for k in before if before[k] != after[k]], ['consumers/arkts/c07/requirements.json'])

    def test_build_attempt_failure_is_failed_not_not_run(self):
        from types import SimpleNamespace
        module = self.verifier()
        report = {'compile': 'not_run', 'target_execution': 'not_run'}
        def fail():
            self.assertEqual(report['compile'], 'started')
            raise RuntimeError('actual compiler failure')
        with self.assertRaisesRegex(RuntimeError, 'compiler failure'):
            module.run_build(SimpleNamespace(build=fail), report)
        self.assertEqual(report, {'compile': 'failed', 'target_execution': 'not_run'})
        module.run_build(SimpleNamespace(build=lambda: None), report)
        self.assertEqual(report['compile'], 'passed')

    def test_device_failures_only_mark_phases_actually_entered(self):
        from types import SimpleNamespace
        module = self.verifier()
        for entered in ((), ('native',), ('native', 'ui')):
            with self.subTest(entered=entered):
                report = {'compile': 'passed'}
                session = SimpleNamespace()
                for phase in entered:
                    setattr(session, phase + '_started', True)
                def fail():
                    self.assertEqual(report['target_execution'], 'started')
                    raise RuntimeError('target failure')
                session.execute = fail
                with self.assertRaisesRegex(RuntimeError, 'target failure'):
                    module.run_target(session, report)
                self.assertEqual(report['target_execution'], 'failed')
                for phase in ('native', 'ui'):
                    self.assertEqual(report[phase], 'failed' if phase in entered else 'not_run')
                self.assertEqual(report['runtime_close'], 'not_confirmed')
                self.assertEqual(report['compile'], 'passed')

    def test_target_success_keeps_explicit_close_confirmation(self):
        from types import SimpleNamespace
        module = self.verifier()
        report = {}
        session = SimpleNamespace(execute=lambda: {'complete': True}, native_passed=True,
                                  ui_passed=True, runtime_close_confirmed=True)
        self.assertEqual(module.run_target(session, report), {'complete': True})
        self.assertEqual(report, {'target_execution': 'passed', 'native': 'passed', 'ui': 'passed', 'runtime_close': 'confirmed'})


if __name__ == '__main__':
    unittest.main()
