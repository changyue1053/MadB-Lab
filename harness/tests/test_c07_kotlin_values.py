"""Synthetic oracle counterexamples only; target evidence is separate."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c07_kotlin_value_observations import SCENARIOS, predicates


def positive(case):
    frames = {label: [70501] + [0] * 109 if kind == 'native' else []
              for label, kind in SCENARIOS[case].items()}
    for label, kind in SCENARIOS[case].items():
        if kind == 'native':
            frames[label][9] = frames[label][10] = 6
    if case == 'kotlin-getters':
        frames['getter-report'] = [16, 1, 1, 2, 1, 0, 2]
    elif case == 'kotlin-copies':
        frames['copy-values'] = [42, 2, 2, 90, 1, 2, 999, 333]
        for i in (12, 13, 14, 15):
            frames['copy-closed'][i] = 1
        frames['copy-closed'][18] = 4
    elif case == 'kotlin-listeners':
        for label in ('listener-entered', 'listener-stopped-entered'):
            frames[label][25], frames[label][31], frames[label][32] = 2, 1, 1
        frames['listener-stopped'][25] = 1
        frames['listener-values'] = [1, 2, 1, 2]
        frames['listener-failure-values'] = [1, 4, 3, 4]
        frames['listener-all-closed'][19] = 1
    else:
        frames['request-only-counts'] = [16, 1]
        frames['request-only-closed'][19] = 1
    return frames


class KotlinValueTests(unittest.TestCase):
    def test_independent_positive_controls(self):
        for case in SCENARIOS:
            with self.subTest(case=case):
                self.assertEqual(predicates(case, positive(case)), [])

    def test_getters_need_positive_setter_original_error_and_single_reads(self):
        frames = positive('kotlin-getters')
        for index in range(7):
            changed = deepcopy(frames)
            changed['getter-report'][index] += 1
            self.assertTrue(predicates('kotlin-getters', changed))

    def test_reentrant_close_cannot_admit_native_allocation_or_work(self):
        for index in (9, 14, 35, 31, 33):
            frames = positive('kotlin-getters')
            frames['getter-after-close'][index] += 1
            self.assertTrue(predicates('kotlin-getters', frames))

    def test_native_copy_output_cannot_alias_or_lose_event(self):
        for index in range(8):
            frames = positive('kotlin-copies')
            frames['copy-values'][index] += 1
            self.assertTrue(predicates('kotlin-copies', frames))

    def test_stopped_entered_callback_must_retain_its_actual_ticket(self):
        for label in ('listener-entered', 'listener-stopped-entered'):
            frames = positive('kotlin-listeners')
            frames[label][31] = 0
            self.assertTrue(predicates('kotlin-listeners', frames))

    def test_sibling_survives_stop_and_callback_exception(self):
        for label in ('listener-values', 'listener-failure-values'):
            frames = positive('kotlin-listeners')
            frames[label][-1] = 77
            self.assertTrue(predicates('kotlin-listeners', frames))

    def test_final_child_leak_and_zero_activity_do_not_pass(self):
        for case, label in (('kotlin-copies', 'copy-closed'), ('kotlin-listeners', 'listener-all-closed'),
                            ('kotlin-request-only', 'request-only-closed')):
            for index in (11, 24, 25, 26, 27, 28, 29, 30, 31, 32, 35):
                frames = positive(case)
                frames[label][index] = 1
                self.assertTrue(predicates(case, frames))
            frames = positive(case)
            frames[label][9] = frames[label][10] = 0
            self.assertTrue(predicates(case, frames))

    def test_request_only_must_reuse_more_than_one_capacity_and_preserve_failure(self):
        for values in ([8, 1], [16, 0], [16, 2]):
            frames = positive('kotlin-request-only')
            frames['request-only-counts'] = values
            self.assertTrue(predicates('kotlin-request-only', frames))

    def test_malformed_observation_fails_closed(self):
        for bad in (None, [], [True] * 110, [70501] + [2**53] * 109):
            frames = positive('kotlin-copies')
            frames['copy-closed'] = bad
            self.assertTrue(predicates('kotlin-copies', frames))
        self.assertTrue(predicates('unknown', {}))
        self.assertTrue(predicates('kotlin-listeners', {}))


if __name__ == '__main__':
    unittest.main()
