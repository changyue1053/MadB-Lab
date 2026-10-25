"""Host negative controls for the narrowly observed diagnostic scenarios."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c07_diagnostic_observations import predicates


def live_frames():
    held, done = [0] * 178, [0] * 178
    for index in (13, 14, 58, 65, 68):
        held[index] = 1
    held[62:65] = [101, 102, 103]
    for index in (16, 17, 59, 60, 66, 67, 68, 69, 70):
        done[index] = 1
    # Historical cleanup TID may have been reused; only the simultaneous held
    # checkpoint proves thread separation.
    done[62:65] = [101, 102, 101]
    return {"live-cleanup-held": held, "live-cleanup-returned": done}


def baseline_frames():
    before = [0] * 178
    for index in (14, 20, 21, 24, 25, 28, 40, 42, 44, 46, 50):
        before[index] = 1
    after = list(before)
    after[33], after[34], after[36] = 3, 3, 1
    return {"child-open-baseline": before, "child-returned-baseline": after,
            "child-baseline-values": [42, 1]}


class DiagnosticOracleTests(unittest.TestCase):
    def test_simultaneously_live_three_threads_then_actual_completion(self):
        self.assertEqual(predicates("live-cleanup-threads", live_frames()), [])

    def test_historical_distinct_ids_do_not_replace_live_witnesses(self):
        for index, value in ((64, 101), (64, 0), (13, 0), (58, 0), (59, 1), (66, 1), (69, 1)):
            frames = live_frames(); frames["live-cleanup-held"][index] = value
            with self.subTest(index=index, value=value):
                self.assertTrue(predicates("live-cleanup-threads", frames))

    def test_started_join_is_not_a_completion_ack(self):
        for index in (17, 67, 69, 70):
            frames = live_frames(); frames["live-cleanup-returned"][index] = 0
            with self.subTest(index=index):
                self.assertTrue(predicates("live-cleanup-threads", frames))

    def test_child_cleanup_returns_live_runtime_baseline(self):
        self.assertEqual(predicates("child-ownership-baseline", baseline_frames()), [])

    def test_whole_runtime_zero_cannot_substitute_for_child_baseline(self):
        frames = baseline_frames(); frames["child-returned-baseline"] = [0] * 178
        self.assertTrue(predicates("child-ownership-baseline", frames))

    def test_leaks_unpaired_model_free_missing_compute_and_duplicate_callback_fail(self):
        for index, value in ((29, 1), (35, 1), (33, 0), (34, 2), (36, 0), (41, 1), (51, 1)):
            frames = baseline_frames(); frames["child-returned-baseline"][index] = value
            with self.subTest(index=index):
                self.assertTrue(predicates("child-ownership-baseline", frames))
        frames = baseline_frames(); frames["child-baseline-values"] = [42, 2]
        self.assertTrue(predicates("child-ownership-baseline", frames))


if __name__ == "__main__":
    unittest.main()
