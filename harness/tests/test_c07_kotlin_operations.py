from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""Synthetic oracle controls, never SDK or target results."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c07_kotlin_operation_observations import ATTEMPTS, SCENARIOS, predicates


def native(allocations=0, releases=0, calls=0, completed=0, models=0, slots=0, size=0):
    result = [0] * 110
    result[0] = 70501
    result[9:16] = allocations, releases, models, 1, 0, calls, completed
    result[24], result[27], result[39] = slots, size, 1
    return result


def control():
    result = ["0"] * 31
    result[0], result[6] = "1", "-1"
    return ",".join(result)


def capacity():
    frames = {
        "kn-op-capacity-before": native(),
        "kn-op-capacity-terminal": native(8, 0, 8, 8, 8, 8, 64),
        "kn-op-capacity-denied": native(8, 0, 8, 8, 8, 8, 64),
        "kn-op-capacity-recovered": native(9, 9, 9, 9),
        "kn-op-capacity-values": list(range(1, 9)),
        "kn-op-capacity-recovery-value": [42],
        "kn-op-capacity-settlement-before": [0] * 9,
        "kn-op-capacity-settlement-unclaimed": [0] * 9,
        "kn-op-capacity-control-before": control(),
        "kn-op-capacity-control-after": control(),
    }
    for i in range(8):
        frames["kn-op-capacity-consumed-" + str(i)] = native(
            8, i + 1, 8, 8, 7 - i, 7 - i, 8 * (7 - i)
        )
    return frames


def stress(winner=0, actual_work=True, active_samples=False):
    frames = {
        "kn-op-race-control-before": control(),
        "kn-op-race-control-after": control(),
    }
    settlement = [0] * 9
    for i in range(ATTEMPTS):
        prefix = "kn-op-race-" + str(i) + "-"
        calls = i if actual_work else 0
        done = calls + (1 if actual_work else 0)
        frames[prefix + "before"] = native(i, i, calls, calls)
        frames[prefix + "before-cancel"] = native(
            i + 1, i, done, calls if active_samples else done, 1, 1, 4
        )
        frames[prefix + "closed"] = native(i + 1, i + 1, done, done)
        frames[prefix + "late"] = native(i + 1, i + 1, done, done)
        frames[prefix + "settlement-before"] = deepcopy(settlement)
        settlement[0] += 1
        settlement[1] += 1
        settlement[2 if winner == 0 else 3] += 1
        settlement[5] = 1
        settlement[6] = 1
        frames[prefix + "settlement-hook"] = deepcopy(settlement)
        settlement[5] = 0
        frames[prefix + "settlement-result"] = deepcopy(settlement)
        settlement[2] += 1  # Separate successful close observation.
        frames[prefix + "settlement-closed"] = deepcopy(settlement)
        frames[prefix + "settlement-late"] = deepcopy(settlement)
        frames[prefix + "outcome"] = [winner, 1, 1, 1]
    frames["kn-op-race-summary"] = [
        ATTEMPTS,
        ATTEMPTS if active_samples else 0,
        ATTEMPTS if winner == 0 else 0,
        ATTEMPTS if winner == 5 else 0,
        ATTEMPTS if actual_work else 0,
    ]
    return frames


class OperationOracleTests(unittest.TestCase):
    def test_eight_completed_unclaimed_handles_pass(self):
        self.assertEqual(predicates("kotlin-terminal-capacity", capacity()), [])
        self.assertEqual(set(capacity()), set(SCENARIOS["kotlin-terminal-capacity"]))

    def test_running_eight_cannot_impersonate_terminal_eight(self):
        f = capacity()
        f["kn-op-capacity-terminal"][15] = 0
        self.assertTrue(predicates("kotlin-terminal-capacity", f))

    def test_terminal_claimed_or_freed_early_is_rejected(self):
        for index, value in ((11, 7), (24, 7), (26, 1), (27, 56), (10, 1)):
            f = capacity()
            f["kn-op-capacity-terminal"][index] = value
            self.assertTrue(predicates("kotlin-terminal-capacity", f), index)
        f = capacity()
        f["kn-op-capacity-settlement-unclaimed"][2] = 1
        self.assertTrue(predicates("kotlin-terminal-capacity", f))

    def test_ninth_rejection_has_no_allocation_or_work_effect(self):
        for index in (9, 10, 14, 15, 24):
            f = capacity()
            f["kn-op-capacity-denied"][index] += 1
            self.assertTrue(predicates("kotlin-terminal-capacity", f), index)

    def test_each_consumed_model_has_one_pair_and_own_value(self):
        for label, index in (
            ("kn-op-capacity-consumed-3", 10),
            ("kn-op-capacity-consumed-7", 24),
        ):
            f = capacity()
            f[label][index] += 1
            self.assertTrue(predicates("kotlin-terminal-capacity", f))
        f = capacity()
        f["kn-op-capacity-values"][4] = 4
        self.assertTrue(predicates("kotlin-terminal-capacity", f))

    def test_capacity_recovery_must_do_real_work(self):
        f = capacity()
        f["kn-op-capacity-recovered"] = native(8, 8, 8, 8)
        self.assertTrue(predicates("kotlin-terminal-capacity", f))

    def test_uncontrolled_stress_accepts_either_winner_without_sampled_overlap(self):
        for winner in (0, 5):
            f = stress(winner)
            self.assertEqual(predicates("kotlin-cancel-race", f), [], winner)
            self.assertEqual(set(f), set(SCENARIOS["kotlin-cancel-race"]))

    def test_inflight_is_recorded_fact_not_required_nor_invented(self):
        f = stress(active_samples=True)
        self.assertEqual(predicates("kotlin-cancel-race", f), [])
        f["kn-op-race-summary"][1] = 0
        self.assertTrue(predicates("kotlin-cancel-race", f))

    def test_zero_actual_native_work_never_proves_cancellation_stress(self):
        self.assertTrue(predicates("kotlin-cancel-race", stress(5, actual_work=False)))

    def test_illegal_winner_duplicate_handler_or_second_claim_is_rejected(self):
        for vector in ([8, 1, 1, 1], [0, 2, 1, 1], [5, 1, 2, 1], [0, 1, 1, 0]):
            f = stress()
            f["kn-op-race-0-outcome"] = vector
            self.assertTrue(predicates("kotlin-cancel-race", f), vector)

    def test_result_settler_cannot_accept_twice_or_both_paths(self):
        for index in (2, 3):
            f = stress()
            f["kn-op-race-0-settlement-result"][index] += 1
            self.assertTrue(predicates("kotlin-cancel-race", f), index)
        f = stress()
        f["kn-op-race-0-settlement-hook"][5] = 0
        self.assertTrue(predicates("kotlin-cancel-race", f))

    def test_late_settlement_free_and_counter_reset_are_rejected(self):
        for label, index in (
            ("kn-op-race-0-late", 10),
            ("kn-op-race-0-settlement-late", 2),
            ("kn-op-race-1-before", 9),
        ):
            f = stress()
            f[label][index] += 1
            self.assertTrue(predicates("kotlin-cancel-race", f), label)

    def test_test_gate_or_fault_must_not_serialize_stress(self):
        for index in (1, 2, 3, 23, 24):
            f = stress()
            c = f["kn-op-race-control-after"].split(",")
            c[index] = "1"
            f["kn-op-race-control-after"] = ",".join(c)
            self.assertTrue(predicates("kotlin-cancel-race", f), index)
        f = stress()
        f["kn-op-race-0-before-cancel"][43] = 1
        self.assertTrue(predicates("kotlin-cancel-race", f))

    def test_summary_and_missing_malformed_frames_never_pass(self):
        f = stress()
        f["kn-op-race-summary"][2] -= 1
        self.assertTrue(predicates("kotlin-cancel-race", f))
        for case in SCENARIOS:
            self.assertTrue(predicates(case, {}))
        f = capacity()
        f["kn-op-capacity-before"][9] = True
        self.assertTrue(predicates("kotlin-terminal-capacity", f))
        f = stress()
        f["kn-op-race-0-settlement-result"] = [0] * 7
        self.assertTrue(predicates("kotlin-cancel-race", f))


if __name__ == "__main__":
    unittest.main()
