"""Synthetic L05 background parser/UI rejection tests; no SDK or device execution."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'harness'))
from l05_background_lifecycle_observations import EXPECTED, UI_EXPECTED, UI_PHASES, click_center, find_node, parse
from l05_background_lifecycle_execution import BackgroundSession, ExecutionError

NONCE, PID = 'l05-background-test', '123'


def line(message, *, pid=PID, tag='MadBL05Background'):
    return '10-27 12:00:00.000 ' + pid + ' 124 I A00000/' + tag + ': ' + message


def evidence():
    # Independent literal transport fixture: no SDK/consumer import and no
    # derivation from the parser's EXPECTED dictionary or frame-building loop.
    payloads = (
        ('initial-ready', [1, 1, 1, 1, 1, 1]),
        ('foreground-published-0', [0, 1, 1]),
        ('background-entered-1', [1, 1, 1]),
        ('page-drained-1', [1, 1]),
        ('background-published-1', [1, 2, 2, 101]),
        ('foreground-entered-1', [1, 2]),
        ('page-reattached-1', [1, 1, 0]),
        ('foreground-published-1', [1, 11, 3]),
        ('background-entered-2', [2, 1, 3]),
        ('page-drained-2', [2, 1]),
        ('background-published-2', [2, 12, 4, 102]),
        ('foreground-entered-2', [2, 3]),
        ('page-reattached-2', [2, 1, 0]),
        ('foreground-published-2', [2, 21, 5]),
        ('background-entered-3', [3, 1, 5]),
        ('page-drained-3', [3, 1]),
        ('background-published-3', [3, 22, 6, 103]),
        ('foreground-entered-3', [3, 4]),
        ('page-reattached-3', [3, 1, 0]),
        ('foreground-published-3', [3, 31, 7]),
        ('owner-closed', [1, 3, 4, 7, 1]),
    )
    return [line('L05_BACKGROUND_CASE ' + NONCE + ' ' + label + ' ' + json.dumps(values))
            for label, values in payloads] + [line('L05_BACKGROUND_COMPLETE ' + NONCE)]


class BackgroundObservationsTests(unittest.TestCase):
    def parsed(self, rows, *, complete=True, **options):
        return parse('\n'.join(rows), nonce=options.get('nonce', NONCE), pid=options.get('pid', PID), complete=complete)

    def rejects(self, rows, **options):
        result = self.parsed(rows, **options)
        self.assertTrue(result['errors'])
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'failed')

    def test_exact_three_background_cycles_same_page_and_shared_owner(self):
        result = self.parsed(evidence())
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['frames'], EXPECTED)
        self.assertEqual(len(result['frames']), 21)
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['complete'])
        self.assertFalse(result['certifies_l05'])

    def test_all_valid_prefixes_remain_incomplete_without_final_marker(self):
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
            with self.subTest(index=index):
                self.rejects(rows[:index] + rows[index + 1:])

    def test_completion_cannot_be_early_duplicate_or_have_suffix(self):
        rows = evidence()
        for position in range(len(rows) - 1):
            with self.subTest(position=position):
                self.rejects(rows[:position] + [rows[-1]] + rows[position:-1], complete=False)
        for suffix in (' extra', ' ', '\t', '-other-run'):
            with self.subTest(suffix=suffix):
                self.rejects(rows[:-1] + [rows[-1] + suffix])
        self.rejects(rows + [rows[-1]], complete=False)

    def test_duplicate_unknown_and_after_completion_frames_fail(self):
        rows = evidence()
        for index, row in enumerate(rows[:-1]):
            with self.subTest(index=index):
                self.rejects(rows[:index + 1] + [row] + rows[index + 1:], complete=False)
        self.rejects(rows + [rows[0]], complete=False)
        self.rejects(rows[:-1] + [line('L05_BACKGROUND_CASE ' + NONCE + ' unknown [1]'), rows[-1]])
        self.rejects(rows + [line('L05_BACKGROUND_OTHER ' + NONCE)], complete=False)

    def test_all_adjacent_frame_reorders_fail(self):
        for index in range(len(evidence()) - 2):
            rows = evidence()
            rows[index], rows[index + 1] = rows[index + 1], rows[index]
            with self.subTest(index=index):
                self.rejects(rows, complete=False)

    def test_missing_background_cannot_be_replaced_by_foreground_success(self):
        rows = evidence()
        for cycle in (1, 2, 3):
            labels = ('background-entered-' + str(cycle), 'page-drained-' + str(cycle),
                      'background-published-' + str(cycle))
            changed = [row for row in rows if not any(' ' + label + ' ' in row for label in labels)]
            with self.subTest(cycle=cycle):
                self.rejects(changed, complete=False)

    def test_restoration_before_background_publication_is_rejected(self):
        for cycle in (1, 2, 3):
            rows = evidence()
            published = next(i for i, row in enumerate(rows) if ' background-published-' + str(cycle) + ' ' in row)
            restored = next(i for i, row in enumerate(rows) if ' foreground-entered-' + str(cycle) + ' ' in row)
            rows[published], rows[restored] = rows[restored], rows[published]
            with self.subTest(cycle=cycle):
                self.rejects(rows, complete=False)

    def test_every_numeric_component_and_array_length_are_checked(self):
        for index, row in enumerate(evidence()[:-1]):
            label, encoded = row.split(' ' + NONCE + ' ', 1)[1].split(' ', 1)
            values = json.loads(encoded)
            for component in range(len(values)):
                wrong = values.copy()
                wrong[component] += 1
                rows = evidence()
                rows[index] = line('L05_BACKGROUND_CASE ' + NONCE + ' ' + label + ' ' + json.dumps(wrong))
                with self.subTest(label=label, component=component):
                    self.rejects(rows, complete=False)
            for wrong in (values[:-1], values + [0]):
                rows = evidence()
                rows[index] = line('L05_BACKGROUND_CASE ' + NONCE + ' ' + label + ' ' + json.dumps(wrong))
                with self.subTest(label=label, length=len(wrong)):
                    self.rejects(rows, complete=False)

    def test_malformed_arrays_and_non_integer_values_fail(self):
        for encoded in ('[true,1,1,1,1,1]', '[1.0,1,1,1,1,1]', 'null', '{}', '{', '[]',
                        '[NaN,1,1,1,1,1]', '[Infinity,1,1,1,1,1]', '[1,1,1,1,1,1] suffix'):
            rows = evidence()
            rows[0] = line('L05_BACKGROUND_CASE ' + NONCE + ' initial-ready ' + encoded)
            with self.subTest(encoded=encoded):
                self.rejects(rows, complete=False)
        self.rejects([line('L05_BACKGROUND_CASE ' + NONCE)], complete=False)

    def test_exact_pid_nonce_tag_and_message_are_required(self):
        for pid in ('', '0', '123 124', '0123', '١٢٣', None):
            with self.subTest(pid=pid):
                self.rejects(evidence(), pid=pid)
        for nonce in ('', 'two words', 'newline\nnonce', None):
            with self.subTest(nonce=nonce):
                self.rejects(evidence(), nonce=nonce)
        rows = evidence()
        for changed in (rows[0].replace(' 123 124 ', ' 999 124 '),
                        rows[0].replace(' 123 124 ', ' 123 0 '),
                        rows[0].replace('/MadBL05Background:', '/OtherTag:'),
                        rows[0].replace(': L05_', ': prefix L05_'),
                        rows[0].split(': ', 1)[1]):
            with self.subTest(changed=changed):
                self.rejects([changed, *rows[1:]], complete=False)

    def test_other_run_is_ignored_and_cannot_supply_missing_evidence(self):
        alien = [row.replace(NONCE, NONCE + '-other') for row in evidence()]
        self.rejects(alien)
        self.rejects([alien[0], *evidence()[1:]])
        result = self.parsed(alien + evidence() + alien)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['lines']), len(evidence()))

    def test_explicit_target_failure_never_becomes_success(self):
        failure = line('L05_BACKGROUND_FAILED ' + NONCE + ' close rejected')
        for rows in ([failure], [failure, *evidence()], [*evidence(), failure]):
            self.rejects(rows, complete=False)

    def test_only_fixed_hitrace_envelopes_preserve_full_protocol(self):
        for prefix in ('[0] ', '[fffffffffffffff] ', '[0, 0, 0] ',
                       '[fffffffffffffff, 3ffffff, 3ffffff] ',
                       '[a92ab16a2bc74d9, ed518e, 4f8686] '):
            with self.subTest(prefix=prefix):
                rows = [row.replace(': L05_', ': ' + prefix + 'L05_', 1) for row in evidence()]
                self.assertTrue(self.parsed(rows)['complete'])

    def test_hitrace_is_not_arbitrary_prefix_or_relaxed_payload(self):
        prefixes = ('arbitrary ', ' [1] ', '[1] [2] ', '[1] extra ',
                    '[1, 2] ', '[1, 2, 3, 4] ', '[1,2,3] ', '[1,  2, 3] ',
                    '[1, 2, 3]\t', '[1, 2, 3]  ', '[1, 2, 3 ',
                    '[1000000000000000] ', '[1, 4000000, 0] ', '[1, 0, 4000000] ',
                    '[1, 10000000, 0] ', '[0x1] ', '[A] ', '[1, A, 0] ',
                    '[00] ', '[1, 00, 0] ', '[-1] ', '[+1] ', '[, 1, 2] ')
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                rows = evidence()
                rows[0] = rows[0].replace(': L05_', ': ' + prefix + 'L05_', 1)
                self.rejects(rows, complete=False)
        traced = [row.replace(': L05_', ': [1, 2, 3] L05_', 1) for row in evidence()]
        for first in (traced[0].replace(' 123 124 ', ' 999 124 '),
                      traced[0].replace('/MadBL05Background:', '/OtherTag:'),
                      traced[0].replace(NONCE, NONCE + '-other'),
                      traced[0].replace('[1, 1, 1, 1, 1, 1]', '[1, 1, 1, 1, 1, 2]'),
                      traced[0] + ' suffix'):
            with self.subTest(first=first):
                self.rejects([first, *traced[1:]])
        self.rejects([traced[-1], *traced[:-1]], complete=False)

    def test_formal001_trace_prefix_still_cannot_complete_missing_cycles(self):
        rows = evidence()[:7]
        rows[5] = rows[5].replace(': L05_', ': [a92ab16a2bc74d9, ed518e, 4f8686] L05_', 1)
        rows[6] = rows[6].replace(': L05_', ': [a92ab16a2bc74d9, eeec4, ed518e] L05_', 1)
        observed = self.parsed(rows, complete=False)
        self.assertEqual(observed['errors'], [])
        self.assertEqual(observed['status'], 'incomplete')
        self.assertEqual(len(observed['frames']), 7)
        self.rejects(rows, complete=True)


class BackgroundUiTests(unittest.TestCase):
    def test_phase_requires_one_snapshot_not_alternating_partial_matches(self):
        wanted = {'l05-bg-phase': 'READY_0', 'l05-bg-page-id': '1',
                  'l05-bg-value': 'EMPTY', 'l05-bg-ordinary': '0'}
        layouts = []
        for changed in ({**wanted, 'l05-bg-value': 'OLD'}, {**wanted, 'l05-bg-phase': 'PUBLISHED_0'}):
            layouts.append({'children': [{'attributes': {'id': key, 'text': value}}
                                         for key, value in changed.items()]})
        session = object.__new__(BackgroundSession)
        session.observation = Mock(return_value={})
        session.layout = Mock(side_effect=layouts)
        session.ui_steps = []
        with patch('l05_background_lifecycle_execution.time.monotonic', side_effect=[0, 0, 1, 21]), \
                patch('l05_background_lifecycle_execution.time.sleep'), self.assertRaises(ExecutionError):
            session.assert_phase('READY_0')
        self.assertEqual(session.layout.call_count, 2)
        self.assertEqual(session.ui_steps, [])

    def test_complete_phase_binds_one_actual_layout_record(self):
        values = {'l05-bg-phase': 'READY_0', 'l05-bg-page-id': '1',
                  'l05-bg-value': 'EMPTY', 'l05-bg-ordinary': '0'}
        layout = {'children': [{'attributes': {'id': key, 'text': value}} for key, value in values.items()]}
        session = object.__new__(BackgroundSession)
        session.observation = Mock(return_value={})
        session.layout = Mock(return_value=layout)
        session.ui_steps = [{'action': 'layout', 'file': 'layout-0.json', 'sha256': 'fixture-sha'}]
        self.assertIs(session.assert_phase('READY_0'), layout)
        self.assertEqual(session.layout.call_count, 1)
        self.assertEqual(session.ui_steps[-1]['observed'], values)
        self.assertEqual(session.ui_steps[-1]['layout_file'], 'layout-0.json')
        self.assertEqual(session.ui_steps[-1]['layout_sha256'], 'fixture-sha')

    def test_all_nine_visible_phases_and_exact_same_page_values(self):
        expected = (
            ('READY_0', 'EMPTY', '0'), ('PUBLISHED_0', 'FOREGROUND-0', '1'),
            ('READY_1', 'EMPTY', '2'), ('PUBLISHED_1', 'FOREGROUND-1', '3'),
            ('READY_2', 'EMPTY', '4'), ('PUBLISHED_2', 'FOREGROUND-2', '5'),
            ('READY_3', 'EMPTY', '6'), ('PUBLISHED_3', 'FOREGROUND-3', '7'),
            ('FINISHED', 'FOREGROUND-3', '7'),
        )
        self.assertEqual(UI_PHASES, tuple(phase for phase, _, _ in expected))
        for phase, value, ordinary in expected:
            with self.subTest(phase=phase):
                self.assertEqual(UI_EXPECTED[phase], {
                    'l05-bg-phase': phase, 'l05-bg-page-id': '1',
                    'l05-bg-value': value, 'l05-bg-ordinary': ordinary,
                })

    def test_ui_nodes_must_be_unique_and_click_bounds_actual(self):
        node = {'attributes': {'id': 'l05-bg-phase', 'text': 'READY_0', 'bounds': '[10,20][50,80]'}}
        self.assertEqual(find_node(node, 'l05-bg-phase')['text'], 'READY_0')
        self.assertEqual(click_center(find_node(node, 'l05-bg-phase')), (30, 50))
        for value in ({}, {'children': [node, node]}):
            with self.assertRaises(ValueError):
                find_node(value, 'l05-bg-phase')
        for bounds in ('', None, '[1,2][1,3]', '[2,3][1,4]', '[-1,2][3,4]'):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                click_center({'bounds': bounds})


if __name__ == '__main__':
    unittest.main()
