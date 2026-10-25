from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""Synthetic counterexamples; actual candidate compilation/target remain separate."""
from copy import deepcopy
import unittest
from c07_listener_lifetime_observations import STATES, predicates


def positive():
    frames = deepcopy(STATES)
    frames['listener-lifetime-counts'] = [0, 0, 1]
    for name, expected in {'listener-source-native': {8: 1, 77: 1, 6: 1},
            'listener-pending-native': {6: 1}, 'listener-entry-native': {5: 1, 9: 1},
            'listener-lifetime-drained': {}}.items():
        frames[name] = [1] + [0] * 177
        for i, value in expected.items():
            frames[name][i] = value
    return frames


class ListenerLifetimeTests(unittest.TestCase):
    def test_independent_positive_control(self):
        self.assertEqual(predicates(positive()), [])

    def test_release_requires_actual_listener_field_not_empty_map(self):
        for label in STATES:
            if 'released' in label:
                frames = positive(); frames[label][3] = 1
                self.assertTrue(predicates(frames))

    def test_source_pending_entered_keep_reference_until_close_ack(self):
        for label, expected in STATES.items():
            if expected[3] == 1:
                frames = positive(); frames[label][3] = 0
                self.assertTrue(predicates(frames))

    def test_cannot_substitute_closed_flag_for_physical_callback_return(self):
        frames = positive(); frames['listener-entry-stopped'][2] = 1
        self.assertTrue(predicates(frames))

    def test_zero_work_or_callback_after_stop_fails(self):
        for counts in ([0, 0, 0], [1, 0, 1], [0, 1, 1], [0, 0, 2]):
            frames = positive(); frames['listener-lifetime-counts'] = counts
            self.assertTrue(predicates(frames))

    def test_distinct_real_native_phases_and_final_drain_required(self):
        for label, index in [('listener-source-native', 8), ('listener-pending-native', 6),
                             ('listener-entry-native', 9), ('listener-lifetime-drained', 5)]:
            frames = positive(); frames[label][index] ^= 1
            self.assertTrue(predicates(frames))

    def test_malformed_or_missing_frames_fail(self):
        for value in (None, [], [True] * 178, [1] + [2**53] * 177):
            frames = positive(); frames['listener-entry-native'] = value
            self.assertTrue(predicates(frames))


if __name__ == '__main__':
    unittest.main()
