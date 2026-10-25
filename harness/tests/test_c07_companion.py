"""Host-only negative controls; no platform API or device operation is executed."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import c07_companion_observations as oracle
from c07_memory_observations import FIELDS as MEMORY_FIELDS, UNITS as MEMORY_UNITS
from c07_admission_observations import BOOTSTRAP_FIELDS, DELIVERY_FIELDS


def contracts():
    # Explicit mock public layout input. There is no producer source dependency.
    return {
        "memory-layout.json":{"format":1,"length":27,"native_ordinal":31,"fields":{str(i):v for i,v in enumerate(MEMORY_FIELDS)},"units":MEMORY_UNITS,"native_signature":"testMemory(runtime:string):number[]","public_signature":"testMemory(runtime:Runtime):number[]"},
        "subscription-state-layout.json":{"format":1,"length":4,"fields":{"0":"Format","1":"Closing","2":"Closed","3":"ListenerRetained"}},
        "bootstrap-totals-layout.json": {"format":1,"length":16,"fields":{str(i):v for i,v in enumerate(BOOTSTRAP_FIELDS)}},
        "ports-layout.json": {"delivery":{"format":1,"length":8,"fields":{str(i):v for i,v in enumerate(DELIVERY_FIELDS)}}},
        "runtime-frame-layout.json": {str(i): name for i, name in enumerate(oracle.RUNTIME_FIELDS)},
        "test-frame-layout.json": {"native_prefix_length": 54, "test_length": 48, "total_length": 178,
            "legacy_total_length": 156, "hook_entry_offset": 102, "hook_entry_length": 54,
            "fields": {str(i + 54): name for i, name in enumerate(oracle.TEST_FIELDS)},
            "operation_fields": list(oracle.OPERATION_FIELDS)},
        "observer-layout.json": {"format": 1, "length": 178, "unchanged_prefix": 156,
            "local_offset": 156, "process_offset": 168,
            "local": {str(i + 156): name for i, name in enumerate(oracle.LOCAL_FIELDS)},
            "process": {str(i + 168): name for i, name in enumerate(oracle.PROCESS_FIELDS)}},
        "facade-frame-layout.json": {"format": 1, "length": 15, "fields": list(oracle.FACADE_FIELDS)},
    }


def native(**fields):
    value = [0] * 178
    value[0] = value[54] = value[156] = 1
    value[157] = 11
    value[168] = 250
    for index, item in fields.items():
        value[int(index)] = item
    return value


def physical():
    value = native()
    for index in (15, 16, 17, 27, 30, 31, 38, 39, 40, 41, 42, 43, 44, 45,
                  46, 47, 48, 49, 50, 51, 58, 59, 60, 65, 66, 67, 68, 69, 70,
                  91, 92, 93, 94, 95, 102, 165, 166, 167):
        value[index] = 1
    value[1], value[55], value[33], value[34] = 3, 2, 17, 17
    value[62:65] = [101, 102, 103]
    value[71:77] = [1, 7, 8, 6, 9, 10]
    value[157] = 158
    value[168:178] = [7825, 0, 0, 0, 1, 1, 1, 1, 1, 1]
    return value


def worker_frames():
    final = physical()
    gate = native()
    for index in (4, 13, 14, 55, 56, 57, 58, 65):
        gate[index] = 1
    gate[62:64] = [101, 102]
    request = native()
    for index, value in {4: 8, 5: 3, 6: 8, 7: 1, 8: 1, 10: 4096, 11: 32, 19: 32, 77: 1}.items():
        request[index] = value
    return {"worker-gate-held": gate, "worker-exit-request": request,
            "worker-hook-entry": final[102:156], "worker-exit-code": [0],
            "physical-closed": final, "case-complete": [1]}


def log(frames, case="worker-env-exit", complete=True):
    messages = ["PROBE_STARTED nonce", "PROBE_PAGE_READY nonce", "PROBE_FINISHED nonce",
                "CONTROLLED_BEGIN nonce " + case]
    messages += ["CONTROLLED_CASE nonce " + name + " " + json.dumps(value) for name, value in frames.items()]
    if complete:
        messages.append("CONTROLLED_COMPLETE nonce " + case)
    return "\n".join("10-25 12:00:00.000 123 456 I MadBC07Probe: " + message for message in messages)


class CompanionOracleTests(unittest.TestCase):
    def parse(self, frames=None, **changes):
        inputs = dict(raw=log(worker_frames() if frames is None else frames), nonce="nonce", pid="123",
                      case="worker-env-exit", route="c", contracts=contracts())
        inputs.update(changes)
        return oracle.parse_controlled(**inputs)

    def test_worker_physical_ack_and_zero_null_counts_are_separate_claims(self):
        result = self.parse()
        self.assertEqual(result["status"], "passed", result["problems"])
        self.assertFalse(result["certifies_c07"])
        self.assertEqual(result["napi"]["null_wake"], "unobserved")
        self.assertEqual(result["napi"]["null_finalizer"], "unobserved")

    def test_same_supported_layout_does_not_require_rust_module_registration(self):
        self.assertEqual(self.parse(route="rust")["status"], "passed")
        self.assertEqual(self.parse(route="cpp")["status"], "passed")

    def test_kotlin_and_unimplemented_cases_are_never_inferred(self):
        self.assertEqual(self.parse(route="kotlin")["status"], "unsupported")
        self.assertEqual(self.parse(case="identity")["status"], "unsupported")
        self.assertEqual(self.parse(case="delivery-hold")["status"], "unsupported")

    def test_explicit_public_layout_is_required_and_must_match_indexes(self):
        for changed in ({}, deepcopy(contracts())):
            if changed:
                changed["observer-layout.json"]["local"]["158"] = "NotIllegalAttempts"
            with self.subTest(changed=bool(changed)):
                self.assertEqual(self.parse(contracts=changed)["status"], "failed")

    def test_legacy_truncated_boolean_float_negative_and_overflow_frames_fail(self):
        values = [physical()[:156], physical()[:-1], physical() + [0]]
        for value in (True, 1.0, -1, 2**53):
            changed = physical(); changed[157] = value; values.append(changed)
        for value in values:
            frames = worker_frames(); frames["physical-closed"] = value
            with self.subTest(value=value[157:158]):
                self.assertEqual(self.parse(frames)["status"], "failed")

    def test_each_illegal_counter_rejects_even_with_complete_markers(self):
        for index in (158, 159, 160, 161, 169, 170):
            frames = worker_frames(); frames["physical-closed"][index] = 1
            with self.subTest(index=index):
                self.assertEqual(self.parse(frames)["status"], "failed")

    def test_absent_api_attempt_or_cleanup_action_is_not_proof(self):
        for index in (157, 165, 166, 167, 91, 92, 93):
            frames = worker_frames(); frames["physical-closed"][index] = 0
            with self.subTest(index=index):
                self.assertEqual(self.parse(frames)["status"], "failed")

    def test_null_wake_must_have_actual_entry_and_paired_native_disposal(self):
        frames = worker_frames(); frames["physical-closed"][162] = 1
        self.assertEqual(self.parse(frames)["status"], "failed")
        frames["physical-closed"][163] = 1
        self.assertEqual(self.parse(frames)["napi"]["null_wake"], "observed-and-paired")

    def test_hook_fullness_is_not_inferred_from_exit_request(self):
        result = self.parse()  # Hook has zero occupancy, exit request has 32 real waiters.
        self.assertEqual(result["status"], "passed")
        frames = worker_frames(); frames["worker-exit-request"][11] = 31
        self.assertEqual(self.parse(frames)["status"], "failed")
        frames = worker_frames(); frames["worker-hook-entry"][11] = 32
        self.assertEqual(self.parse(frames)["status"], "failed")

    def test_physical_owner_and_tls_join_proof_cannot_be_replaced_by_marker(self):
        for index, value in ((20, 1), (34, 16), (55, 1), (17, 0), (73, 10), (62, 0)):
            frames = worker_frames(); frames["physical-closed"][index] = value
            with self.subTest(index=index):
                self.assertEqual(self.parse(frames)["status"], "failed")

    def test_process_observations_can_change_while_local_receipt_is_stable(self):
        frames = worker_frames()
        frames["observer-local"] = frames["physical-closed"][156:168]
        frames["observer-process"] = frames["physical-closed"][168:178]
        frames["observer-process-repeat"] = [8185, 0, 0, 0, 2, 1, 2, 1, 2, 1]
        self.assertEqual(self.parse(frames)["status"], "passed")
        frames["observer-local"][1] += 1
        self.assertEqual(self.parse(frames)["status"], "failed")

    def test_missing_duplicate_unknown_truncated_and_wrong_pid_transport_fail(self):
        frames = worker_frames(); del frames["worker-exit-request"]
        self.assertEqual(self.parse(frames)["status"], "failed")
        frames = worker_frames(); frames["unreviewed-label"] = [1]
        self.assertEqual(self.parse(frames)["status"], "failed")
        raw = log(worker_frames())
        extra = "\n10-25 12:00:00.000 123 456 I MadBC07Probe: CONTROLLED_CASE nonce case-complete [1]"
        for changed in (raw + extra, raw.replace('case-complete [1]', 'case-complete ['),
                        raw.replace(' 123 ', ' 124 ', 1), raw.replace('CONTROLLED_COMPLETE nonce worker-env-exit', 'CONTROLLED_COMPLETE nonce full-waiters')):
            with self.subTest(changed=changed[-80:]):
                self.assertEqual(self.parse(raw=changed)["status"], "failed")

    def test_incomplete_and_prior_nonce_do_not_pass_or_contaminate(self):
        self.assertEqual(self.parse(raw=log({}, complete=False))["status"], "incomplete")
        self.assertEqual(self.parse(raw=log(worker_frames()).replace('nonce', 'nonce-old'))["status"], "incomplete")
        self.assertEqual(self.parse(raw=log(worker_frames()) + '\n' + log(worker_frames()).replace('nonce', 'nonce-old'))["status"], "passed")

    def test_failure_or_absent_live_pid_never_passes(self):
        self.assertEqual(self.parse(pid="")["status"], "failed")
        raw = log(worker_frames()) + '\n10-25 12:00:00.000 123 456 I MadBC07Probe: PROBE_FAILED nonce assertion BridgeFailure'
        self.assertEqual(self.parse(raw=raw)["status"], "failed")

    def test_normal_close_requires_facade_owner_retirement(self):
        final = physical(); final[27] = 0
        opened = native(); full = native(); full[5] = 8
        js = [1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0]
        frames = {"open": opened, "subscriptions-full8": full, "physical-closed": final,
                  "facade-closed": js, "case-complete": [1]}
        self.assertEqual(self.parse(raw=log(frames, 'subscriptions-capacity'), case='subscriptions-capacity')["status"], "passed")
        js[6] = 1
        self.assertEqual(self.parse(raw=log(frames, 'subscriptions-capacity'), case='subscriptions-capacity')["status"], "failed")


if __name__ == "__main__":
    unittest.main()
