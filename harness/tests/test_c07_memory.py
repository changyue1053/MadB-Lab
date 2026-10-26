"""Oracle controls only: these synthetic vectors are not SDK execution evidence."""

from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from copy import deepcopy
import unittest
from c07_memory_observations import (
    FIELDS,
    SCENARIOS,
    UNITS,
    predicates,
    validate_contracts,
)


def memory(
    retained,
    peak,
    staging,
    staging_peak,
    models,
    max_models,
    acquired_models,
    released_models,
    scopes,
):
    out = [0] * 27
    out[0] = 1
    out[1:5] = retained, peak, staging, staging_peak
    out[5:12] = (
        models * 32,
        max_models * 32,
        models * 1024,
        max_models * 1024,
        max_models * 1056,
        acquired_models * 1056,
        released_models * 1056,
    )
    out[12:16] = 0, 1025, scopes * 1025, scopes * 1025
    out[16:20] = 0, 32, 0, 2050
    out[20:27] = scopes, scopes, scopes, scopes, 32, 32, 2050
    return out


def native(**fields):
    out = [0] * 178
    for name, value in fields.items():
        out[int(name)] = value
    return out


def successful(case):
    if case == "memory-state-staging":
        return {
            "memory-state-pending": memory(1024, 1024, 0, 0, 1, 1, 1, 0, 1),
            "memory-state-staged": memory(2048, 2048, 1024, 1024, 2, 2, 2, 0, 2),
            "memory-state-replaced": memory(1024, 2048, 0, 1024, 1, 2, 2, 1, 2),
            "memory-state-entered": memory(1024, 2048, 0, 1024, 1, 2, 2, 1, 2),
            "memory-state-drained": memory(0, 2048, 0, 1024, 0, 2, 2, 2, 2),
            "memory-final": memory(0, 2048, 0, 1024, 0, 2, 2, 2, 2),
            "memory-state-gate": [1, 0, 1, 0, 0, 1, 0, 0],
            "memory-state-values": [2],
            "memory-state-staged-native": native(**{"7": 2, "9": 0, "10": 2048, "77": 1}),
            "memory-state-replaced-native": native(
                **{"7": 1, "9": 0, "10": 1024, "77": 0}
            ),
            "memory-state-entered-native": native(**{"7": 1, "9": 1, "10": 1024}),
        }
    return {
        "memory-full-before-copy": memory(4096, 4096, 0, 0, 4, 4, 4, 0, 4),
        "memory-full-after-copy": memory(4096, 4096, 0, 0, 4, 5, 5, 1, 5),
        "memory-full-rejected": memory(4096, 4096, 0, 0, 4, 5, 5, 1, 6),
        "memory-final": memory(0, 4096, 0, 0, 0, 5, 5, 5, 6),
        **{
            name: native(**{"3": 0, "4": 4, "10": 4096, "13": 4})
            for name in (
                "memory-full-native",
                "memory-full-after-copy-native",
                "memory-full-rejected-native",
            )
        },
        "memory-copy-result": [1, 1024, 512],
    }


def failures(case, frames):
    errors = []

    def need(ok, reason):
        if not ok:
            errors.append(reason)

    def equal(name, expected):
        for index, value in expected.items():
            need(frames[name][index] == value, name + ":" + str(index))

    def delta(before, after, expected):
        for index, value in expected.items():
            need(
                frames[after][index] - frames[before][index] == value,
                after + ":delta" + str(index),
            )

    predicates(case, frames, need, equal, delta)
    return errors


class MemoryOracleTests(unittest.TestCase):
    def test_two_independent_legal_histories(self):
        for case in SCENARIOS:
            self.assertEqual(failures(case, successful(case)), [], case)

    def test_staging_must_be_charged_and_peak_observed(self):
        for index, value in (
            (1, 1024),
            (2, 1024),
            (3, 0),
            (4, 0),
            (5, 32),
            (7, 1024),
            (9, 1056),
        ):
            frames = successful("memory-state-staging")
            frames["memory-state-staged"][index] = value
            self.assertTrue(failures("memory-state-staging", frames), (index, value))

    def test_latest_only_and_entered_lease_are_required(self):
        for mode in ("old", "extra", "not_entered", "no_held"):
            frames = successful("memory-state-staging")
            if mode == "old":
                frames["memory-state-values"] = [1]
            if mode == "extra":
                frames["memory-state-values"] = [1, 2]
            if mode == "not_entered":
                frames["memory-state-entered-native"][9] = 0
            if mode == "no_held":
                frames["memory-state-gate"][2] = 0
            self.assertTrue(failures("memory-state-staging", frames), mode)

    def test_four_retained_objects_still_require_fifth_scratch_allocation(self):
        for index, value in (
            (1, 3072),
            (6, 128),
            (8, 4096),
            (9, 4224),
            (10, 4224),
            (11, 0),
        ):
            frames = successful("memory-full-scratch")
            frames["memory-full-after-copy"][index] = value
            self.assertTrue(failures("memory-full-scratch", frames), (index, value))

    def test_item_capacity_cannot_impersonate_byte_capacity(self):
        frames = successful("memory-full-scratch")
        frames["memory-full-native"][4] = 8
        self.assertTrue(failures("memory-full-scratch", frames))

    def test_rejected_operation_must_not_allocate_provider_model(self):
        frames = successful("memory-full-scratch")
        frames["memory-full-rejected"][10] += 1056
        frames["memory-full-rejected"][11] += 1056
        frames["memory-final"][10] += 1056
        frames["memory-final"][11] += 1056
        self.assertTrue(failures("memory-full-scratch", frames))

    def test_each_storage_domain_must_have_actual_observed_peak(self):
        for index in (13, 17, 19, 24, 25, 26):
            frames = successful("memory-full-scratch")
            frames["memory-full-after-copy"][index] = 0
            self.assertTrue(failures("memory-full-scratch", frames), index)

    def test_missing_scratch_conversion_events_fail_even_when_final_balanced(self):
        frames = successful("memory-full-scratch")
        for index in (14, 15, 20, 21, 22, 23):
            frames["memory-full-after-copy"][index] = frames["memory-full-before-copy"][
                index
            ]
        self.assertTrue(failures("memory-full-scratch", frames))

    def test_peak_is_simultaneous_not_an_arbitrary_sum(self):
        frames = successful("memory-state-staging")
        frames["memory-state-staged"][9] += 1
        self.assertTrue(failures("memory-state-staging", frames))

    def test_final_ownership_and_release_must_really_balance(self):
        for index in (1, 3, 5, 7, 12, 16, 18):
            frames = successful("memory-full-scratch")
            frames["memory-final"][index] = 1
            self.assertTrue(failures("memory-full-scratch", frames), index)
        for index in (11, 15, 21, 23):
            frames = successful("memory-full-scratch")
            frames["memory-final"][index] -= 1
            self.assertTrue(failures("memory-full-scratch", frames), index)

    def test_integer_range_and_peak_monotonicity(self):
        for value in (-1, True, 1.5, 2**53):
            frames = successful("memory-full-scratch")
            frames["memory-full-after-copy"][14] = value
            self.assertTrue(failures("memory-full-scratch", frames), value)
        frames = successful("memory-state-staging")
        frames["memory-final"][2] = 0
        self.assertTrue(failures("memory-state-staging", frames))

    def test_staging_source_ticket_is_counted_beside_old_pending(self):
        for tickets in (0, 1, 3):
            frames = successful("memory-state-staging")
            frames["memory-state-staged-native"][7] = tickets
            self.assertIn(
                "memory-state-staged-native:7",
                failures("memory-state-staging", frames),
                tickets,
            )

    def test_work_includes_three_queued_and_one_running_at_every_checkpoint(self):
        for label in (
            "memory-full-native",
            "memory-full-after-copy-native",
            "memory-full-rejected-native",
        ):
            for work in (0, 1, 3, 5):
                frames = successful("memory-full-scratch")
                frames[label][13] = work
                self.assertIn(
                    label + ":13", failures("memory-full-scratch", frames), (label, work)
                )

    def test_contract_field_order_is_not_guessed(self):
        value = {
            "units": deepcopy(UNITS),
            "format": 1,
            "length": 27,
            "native_ordinal": 31,
            "fields": {str(i): n for i, n in enumerate(FIELDS)},
            "native_signature": "testMemory(runtime:string):number[]",
            "public_signature": "testMemory(runtime:Runtime):number[]",
        }
        validate_contracts({"memory-layout.json": value})
        wrong = deepcopy(value)
        wrong["units"]["bytes"] = "RSS"
        with self.assertRaises(ValueError):
            validate_contracts({"memory-layout.json": wrong})
        value["fields"]["1"], value["fields"]["2"] = (
            value["fields"]["2"],
            value["fields"]["1"],
        )
        with self.assertRaises(ValueError):
            validate_contracts({"memory-layout.json": value})


if __name__ == "__main__":
    unittest.main()
