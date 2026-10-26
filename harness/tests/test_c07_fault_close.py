"""Finite fault-close parser regressions; synthetic positives are not target proof."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import c07_companion_observations as oracle
from c07_companion_cases import GROUPS, assess_group
from test_c07_companion import contracts, log, native, physical
from test_c07_companion_cases import DIGEST, RUN, observations

CASES = ("fault-before-guard", "fault-after-accepted",
         "failed-close-before-guard", "failed-close-after-accepted")


def fault_frames(case):
    before = case.endswith("before-guard")
    worker = case in oracle.WORKER_CASES
    final = physical()
    if not worker:
        for index in (27, 91, 92, 165, 166, 167):
            final[index] = 0
        final[32] = 1
    held = native(**{"4": 1, "13": 1, "14": 1, "55": 1, "56": 2,
                     "57": 1, "58": 1, "62": 101, "63": 102, "65": 1})
    residual = deepcopy(held)
    for index in (11, 19, 85, 87):
        residual[index] = int(before)
    js = [1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, int(not before), 0, 0, 0]
    pending = deepcopy(residual)
    pending[1], pending[30] = 1, 1
    pending_js = list(js)
    for index in (5, 6, 8):
        pending_js[index] = 1
    frames = {} if worker else {"open": native()}
    frames.update({
        "work-held": held, "operation-held": [1, 1, 0, 1, 2, 1, 0, 0, 0, 1],
        "fault-residual": residual, "fault-facade": js,
        "fault-settlement-counts": [int(not before), int(before)],
        "fault-close-pending-native": pending, "fault-close-pending-facade": pending_js,
        "fault-close-pending": [1, 0, 0, 1],
    })
    if worker:
        parent = deepcopy(pending)
        parent[55] = 0
        frames.update({"parent-fault-residual": parent,
            "fault-close-at-exit": [1, 0, 0, 0], "worker-exit-request": deepcopy(pending),
            "worker-hook-entry": final[102:156], "worker-exit-code": [0]})
    else:
        frames.update({"fault-close-settled-native": deepcopy(final),
            "fault-close-outcome": [0, 1, 1, 1],
            "fault-late-settlements": [int(not before), int(before), 0, 1]})
    frames["physical-closed"] = final
    if not worker:
        frames["facade-closed"] = [1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, int(not before), 0, 0, 0]
    frames["case-complete"] = [1]
    return frames


def parse(case, frames=None, raw=None, route="c"):
    if raw is None:
        raw = log(fault_frames(case) if frames is None else frames, case)
    return oracle.parse_controlled(raw=raw, nonce="nonce", pid="123", case=case,
                                   route=route, contracts=contracts())


class FaultCloseTests(unittest.TestCase):
    def test_two_distinct_cleanup_paths_and_both_transfer_boundaries(self):
        for case in CASES:
            for route in ("c", "cpp", "rust"):
                with self.subTest(case=case, route=route):
                    result = parse(case, route=route)
                    self.assertEqual(result["status"], "passed", result["problems"])
                    self.assertFalse(result["certifies_c07"])

    def test_captured_original_deadlock_remains_failed(self):
        raw = (HERE / "fixtures/c07-fault-ready-timeout.log").read_text()
        result = oracle.parse_controlled(raw=raw,
            nonce="c07-d1e8a37f15d94185a128fd30653f3438", pid="26729",
            case="fault-before-guard", route="c", contracts=contracts())
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("LAB_TIMEOUT:fault-ready" in value for value in result["failures"]))
        self.assertNotIn("physical-closed", result["frames"])

    def test_early_rejection_success_missing_memoization_or_pending_owner_fails(self):
        changes = [("fault-close-pending", 1, 1), ("fault-close-pending", 2, 1),
            ("fault-close-pending", 3, 0), ("fault-close-pending-native", 1, 3),
            ("fault-close-pending-native", 13, 0), ("fault-close-pending-native", 17, 1),
            ("fault-close-pending-native", 30, 0), ("fault-close-pending-native", 59, 1),
            ("fault-close-pending-facade", 5, 0), ("fault-close-pending-facade", 6, 0),
            ("fault-close-pending-facade", 9, 1), ("fault-close-pending-facade", 10, 0)]
        for case in CASES:
            for label, index, value in changes:
                frames = fault_frames(case); frames[label][index] = value
                with self.subTest(case=case, label=label, index=index):
                    self.assertEqual(parse(case, frames)["status"], "failed")

    def test_normal_rejection_requires_actual_receipt_not_eventual_cleanup(self):
        changes = [("fault-close-outcome", 0, 1), ("fault-close-outcome", 1, 0),
            ("fault-close-outcome", 2, 0), ("fault-close-outcome", 3, 0),
            ("fault-close-settled-native", 1, 1), ("fault-close-settled-native", 17, 0),
            ("fault-close-settled-native", 20, 1), ("fault-close-settled-native", 32, 0),
            ("fault-close-settled-native", 41, 0), ("fault-close-settled-native", 73, 10),
            ("fault-close-settled-native", 27, 1), ("fault-late-settlements", 3, 2),
            ("facade-closed", 10, 0), ("facade-closed", 6, 1)]
        for case in CASES[2:]:
            for label, index, value in changes:
                frames = fault_frames(case); frames[label][index] = value
                with self.subTest(case=case, label=label, index=index):
                    self.assertEqual(parse(case, frames)["status"], "failed")

    def test_worker_exit_still_requires_live_residual_real_hook_and_pending_close(self):
        changes = [("fault-close-at-exit", 1, 1), ("fault-close-at-exit", 2, 1),
            ("parent-fault-residual", 30, 0), ("physical-closed", 27, 0),
            ("physical-closed", 91, 0), ("physical-closed", 93, 0),
            ("physical-closed", 13, 1), ("physical-closed", 41, 0),
            ("physical-closed", 69, 0), ("physical-closed", 73, 10),
            ("worker-exit-code", 0, 1)]
        for case in CASES[:2]:
            for label, index, value in changes:
                frames = fault_frames(case); frames[label][index] = value
                with self.subTest(case=case, label=label, index=index):
                    self.assertEqual(parse(case, frames)["status"], "failed")

    def test_missing_duplicate_truncated_and_reordered_transport_cannot_pass(self):
        for case in CASES:
            good = fault_frames(case)
            for label in oracle.SCENARIOS[case]:
                frames = deepcopy(good); del frames[label]
                with self.subTest(case=case, absent=label):
                    self.assertEqual(parse(case, frames)["status"], "failed")
            raw = log(good, case)
            duplicate = '\n10-25 12:00:00.000 123 456 I MadBC07Probe: CONTROLLED_CASE nonce fault-close-pending [1,0,0,1]'
            self.assertEqual(parse(case, raw=raw + duplicate)["status"], "failed")
            self.assertEqual(parse(case, raw=raw.replace('fault-close-pending [1, 0, 0, 1]', 'fault-close-pending ['))["status"], "failed")
            frames = deepcopy(good); pending = frames.pop("fault-close-pending")
            frames["fault-close-pending"] = pending
            self.assertEqual(parse(case, frames)["status"], "failed")
            failed = raw + '\n10-25 12:00:00.000 123 456 E MadBC07Probe: PROBE_FAILED nonce LAB_ASSERT:typed-error'
            self.assertEqual(parse(case, raw=failed)["status"], "failed")

    def test_result_outcome_and_native_consumption_boundary_are_not_relaxed(self):
        for case in CASES:
            for label, index in (("fault-settlement-counts", 0), ("fault-residual", 11),
                                 ("fault-residual", 87), ("fault-facade", 11)):
                frames = fault_frames(case); frames[label][index] = 1 - frames[label][index]
                self.assertEqual(parse(case, frames)["status"], "failed")

    def test_normal_failed_close_is_required_separately_from_env_exit(self):
        for group in ("runtime-close-full", "result-transfer-failures"):
            self.assertTrue(set(CASES[2:]).issubset(GROUPS[group]["scenarios"]))
            for absent in CASES[2:]:
                records = observations(); del records[absent]
                result = assess_group(group, route="c", candidate_digest=DIGEST,
                                      run_id=RUN, observations=records)
                self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
