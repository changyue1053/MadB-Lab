from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
"""Synthetic controls test the oracle, never certify an SDK execution."""

from copy import deepcopy
import unittest
from c07_capacity_stream_observations import SCENARIO, SCENARIOS, predicates


def native(alloc=0, freed=0, calls=0, slots=0):
    result = [0] * 178
    result[0] = result[54] = result[55] = result[156] = 1
    result[4], result[33], result[34], result[35], result[36] = (
        slots,
        alloc,
        freed,
        alloc - freed,
        calls,
    )
    return result


def valid():
    f = {
        "before": native(),
        "unclaimed": native(16, 8, 8, 8),
        "denied": native(16, 8, 8, 8),
        "one-released": native(16, 9, 8, 7),
        "reused": native(18, 10, 9, 8),
        "drained": native(18, 18, 9),
        "ninth-rejected": [1],
        "values": list(range(11, 19)) + [100],
        "facade-before": [1] + [0] * 14,
        "facade-unclaimed": [1, 0, 0, 0, 8] + [0] * 10,
        "recovery-operation": [1, 1] + [0] * 8,
    }
    for i in range(8):
        f["operation-" + str(i)] = [1, 1] + [0] * 8
    for i in range(1, 8):
        f["consumed-" + str(i)] = native(18, 10 + i, 9, 8 - i)
    return {"terminal-capacity-" + name: value for name, value in f.items()}


class CapacityTests(unittest.TestCase):
    def reject(self, name, index, value):
        f = valid()
        f["terminal-capacity-" + name][index] = value
        self.assertTrue(predicates(SCENARIO, f), (name, index))

    def test_complete_terminal_unclaimed_capacity_passes(self):
        f = valid()
        self.assertEqual(set(f), set(SCENARIOS[SCENARIO]))
        self.assertEqual(predicates(SCENARIO, f), [])

    def test_allocation_count_not_hardcoded_to_one_provider_implementation(self):
        f = valid()
        # Extra successful transient allocations are permitted when truly paired.
        for key, value in f.items():
            if SCENARIOS[SCENARIO][key] == "native":
                value[33] += 3
                value[34] += 3
        self.assertEqual(predicates(SCENARIO, f), [])

    def test_running_eight_is_not_terminal_eight(self):
        for index, value in ((13, 1), (36, 7)):
            self.reject("unclaimed", index, value)
        self.reject("operation-4", 1, 0)

    def test_wrong_winner_or_closed_operation_rejects(self):
        for index, value in ((1, 2), (1, 3), (2, 1), (3, 1)):
            self.reject("operation-3", index, value)

    def test_early_model_release_and_early_result_settlement_reject(self):
        self.reject("unclaimed", 35, 7)
        self.reject("facade-unclaimed", 11, 1)
        self.reject("facade-unclaimed", 4, 7)

    def test_bytes_or_waiter_pressure_cannot_explain_rejection(self):
        for index in (10, 11, 12, 19):
            self.reject("unclaimed", index, 1)

    def test_ninth_must_reject_without_allocation_or_work(self):
        self.reject("ninth-rejected", 0, 0)
        for index in (4, 33, 34, 35, 36):
            f = valid()
            f["terminal-capacity-denied"][index] += 1
            self.assertTrue(predicates(SCENARIO, f), index)

    def test_claim_and_close_return_exactly_one_slot(self):
        for index, value in ((4, 8), (35, 8), (34, 10)):
            self.reject("one-released", index, value)

    def test_lifetime_cap_cannot_pass_without_real_recovery(self):
        self.reject("reused", 36, 8)
        self.reject("reused", 4, 7)
        self.reject("recovery-operation", 1, 0)

    def test_each_old_and_recovery_payload_frees_once(self):
        self.reject("consumed-4", 34, 15)
        self.reject("drained", 34, 17)
        self.reject("drained", 4, 1)

    def test_actual_values_and_completeness_required(self):
        self.reject("values", 4, 14)
        f = valid()
        del f["terminal-capacity-operation-5"]
        self.assertTrue(predicates(SCENARIO, f))

    def test_malformed_frames_fail_without_crash(self):
        for bad in (None, [1], [True] * 178, [2**53] * 178):
            f = valid()
            f["terminal-capacity-unclaimed"] = deepcopy(bad)
            self.assertTrue(predicates(SCENARIO, f))
        self.assertTrue(predicates("unknown", valid()))


def stream():
    def frame(alloc, subscriptions):
        f = native(alloc, alloc)
        f[5] = subscriptions
        return f

    return {
        "isolation-before": frame(0, 2),
        "isolation-native-1": frame(2, 2),
        "isolation-native-2": frame(5, 3),
        "isolation-drained": frame(5, 0),
        "isolation-late-registered": frame(2, 3),
        "isolation-late-empty": [],
        "isolation-late-next": [12],
        "isolation-state-1": [11],
        "isolation-state-2": [11, 12],
        "isolation-event-1": [21],
        "isolation-event-2": [21, 22],
    }


class StreamTests(unittest.TestCase):
    def test_two_active_streams_pass_without_global_callback_order(self):
        f = stream()
        self.assertEqual(set(f), set(SCENARIOS["stream-isolation"]))
        self.assertEqual(predicates("stream-isolation", f), [])

    def test_cross_delivery_in_either_direction_rejects(self):
        for name, wrong in (
            ("isolation-state-1", [21]),
            ("isolation-event-1", [11]),
            ("isolation-state-2", [11, 22]),
            ("isolation-event-2", [21, 12]),
        ):
            f = stream()
            f[name] = wrong
            self.assertTrue(predicates("stream-isolation", f), name)

    def test_missing_duplicate_or_out_of_order_delivery_rejects(self):
        for wrong in ([21], [21, 21], [22, 21], [21, 22, 22]):
            f = stream()
            f["isolation-event-2"] = wrong
            self.assertTrue(predicates("stream-isolation", f), wrong)

    def test_no_listener_or_retained_payload_does_not_pass(self):
        for index, value in ((5, 1), (6, 1), (7, 1), (35, 1)):
            f = stream()
            f["isolation-native-1"][index] = value
            self.assertTrue(predicates("stream-isolation", f), index)

    def test_late_subscriber_cannot_replay_prior_current_value(self):
        for label, wrong in (
            ("isolation-late-empty", [11]),
            ("isolation-late-next", [11, 12]),
            ("isolation-late-next", [11]),
        ):
            f = stream()
            f[label] = wrong
            self.assertTrue(predicates("stream-isolation", f), label)
        f = stream()
        f["isolation-late-registered"][33] += 1
        f["isolation-late-registered"][34] += 1
        self.assertTrue(predicates("stream-isolation", f))

    def test_actual_clone_release_and_final_stop_are_required(self):
        for label, index, value in (
            ("isolation-native-1", 33, 0),
            ("isolation-native-2", 34, 3),
            ("isolation-drained", 5, 1),
        ):
            f = stream()
            f[label][index] = value
            self.assertTrue(predicates("stream-isolation", f), (label, index))


if __name__ == "__main__":
    unittest.main(verbosity=2)
