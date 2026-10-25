"""Counterexamples for the Lab-owned normal-env admission oracle."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c07_kotlin_admission_observations import EPOCHS, LABELS, PAIRS, predicates


def closed_frames():
    # Independent synthetic positive control, never candidate/target evidence.
    frames = {label: ([70501] + [0] * 109 if kind == 'native' else
                      [0] * 13 if kind == 'admission' else []) for label, kind in LABELS.items()}
    frames['workerfirst-admission'][2] = 1
    frames['workerfirst'] = [1, 0]
    frames['epoch-key-changed'] = [1]
    frames['epoch2-local-id1'] = [7, 7]
    frames['old-key-rejections'] = [1, 1, 1, 1]
    frames['epoch2-result'] = [42]
    frames['admission-complete'] = [1]
    for name in ('epoch2-live-waiter', 'epoch2-after-old-calls'):
        for i in (9, 11, 12, 14, 24, 26, 36, 41):
            frames[name][i] = 1
        frames[name][27] = 5
    for index, epoch in enumerate(EPOCHS, 1):
        frame = frames[epoch + '-closed']
        frame[1], frame[2], frame[7], frame[72] = 4, 1, 1, 3
        for a, b in PAIRS:
            frame[a] = frame[b] = 1
        frames[epoch + '-admission'][7] = index
        if epoch != 'epoch2':
            frames[epoch + '-values'] = [42, 7, 8]
    for stage in range(5):
        prefix = f'partial-{stage}-'
        before = frames[prefix + 'before']
        before[0], before[1], before[8] = 10 + stage, stage, stage
        immediate = frames[prefix + 'immediate'] = before.copy()
        immediate[0] += 1
        immediate[1] += 1
        ack = frames[prefix + 'ack'] = immediate.copy()
        ack[8] += 1
        ack[9] = stage
    return frames


class KotlinAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.frames = closed_frames()

    def test_independent_positive_control(self):
        self.assertEqual(predicates(self.frames), [])

    def test_worker_reject_cannot_initialize_provider(self):
        self.frames['workerfirst-admission'][4] = 1
        self.assertTrue(any('Worker rejection initialized' in p for p in predicates(self.frames)))

    def test_old_calls_cannot_consume_new_waiter_or_change_model(self):
        for index, value in ((26, 0), (9, 2), (13, 1), (27, 0), (36, 2)):
            with self.subTest(index=index):
                frames = deepcopy(self.frames)
                frames['epoch2-after-old-calls'][index] = value
                self.assertTrue(predicates(frames))

    def test_partial_failure_needs_real_rollback_ack_and_drain(self):
        for stage in range(5):
            with self.subTest(stage=stage):
                frames = deepcopy(self.frames)
                frames[f'partial-{stage}-ack'][8] -= 1
                self.assertTrue(any('rollback ACK' in p for p in predicates(frames)))
        self.frames['partial-4-drained'][47] = 1
        self.assertTrue(any('owners or errors remain' in p for p in predicates(self.frames)))

    def test_logical_closed_cannot_replace_physical_join(self):
        self.frames['epoch2-closed'][13] = 0
        self.assertTrue(any('physical allocation/cleanup' in p for p in predicates(self.frames)))

    def test_zero_balances_cannot_replace_real_work_and_resource_activity(self):
        for epoch in EPOCHS:
            with self.subTest(epoch=epoch):
                frames = deepcopy(self.frames)
                for a, b in PAIRS:
                    frames[epoch + '-closed'][a] = frames[epoch + '-closed'][b] = 0
                self.assertTrue(any('absent real' in p for p in predicates(frames)))

    def test_wrong_current_local_id_cannot_make_old_key_rejection_pass(self):
        self.frames['epoch2-local-id1'] = [7, 0]
        self.assertTrue(any('positively observed' in p for p in predicates(self.frames)))

    def test_reopen_requires_a_new_epoch(self):
        self.frames['epoch2-admission'][7] = self.frames['epoch1-admission'][7]
        self.assertTrue(any('slot/epoch' in p for p in predicates(self.frames)))

    def test_each_failed_stage_requires_actual_retry_behavior(self):
        for stage in range(1, 5):
            with self.subTest(stage=stage):
                frames = deepcopy(self.frames)
                frames[f'retry{stage}-values'] = [42, 7]
                self.assertTrue(any('retry did not execute' in p for p in predicates(frames)))

    def test_missing_or_malformed_is_failure_not_exception(self):
        for value in (None, [], [True] * 110, [float('nan')] * 110, [2**53] * 110):
            with self.subTest(value=repr(value)[:20]):
                frames = deepcopy(self.frames)
                frames['epoch1-closed'] = value
                self.assertTrue(any('malformed' in p for p in predicates(frames)))
        del self.frames['admission-complete']
        self.assertTrue(predicates(self.frames))


if __name__ == '__main__':
    unittest.main()
