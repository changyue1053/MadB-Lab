"""L02 independent observation and refusal checks, not native runtime evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("verify_l02", Path(__file__).with_name("verify_l02.py"))
l02 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l02)


class L02Checks(unittest.TestCase):
    library = Path("/private/tmp/l02-unit-only-not-a-real-library")
    identity = {"interface_digest": "sha256:" + "1" * 64, "profile_digest": "sha256:" + "2" * 64}

    def output(self, body):
        rows = [{"loaded_module": str(self.library), "pid": 123}, *body,
                {"actual_identity": "1" * 64 + "2" * 64}, {"result": "passed"}]
        return "\n".join(json.dumps(row) for row in rows)

    def ordinary(self):
        return {"ordinary": True, "engine": 1, "subscription": 2, "callbacks": 1, "sum": 511, "close": "confirmed"}

    def stats(self, events=11, calls=10, failures=1, callbacks=1, drops=0, enabled=1):
        return {"events": events, "completed_calls": calls, "failed_calls": failures,
                "completed_callbacks": callbacks, "dropped_events": drops, "capture_enabled": enabled}

    def events(self):
        symbols = [1, 2, 3, 3, 8, 7, 4, 5, 5, 6, 6]
        resources = [0, 1, 1, 0, 2, 1, 1, 1, 2, 2, 1]
        return [{"record_id": n + 1, "symbol_id": symbol, "phase": 2 if n == 4 else 1,
                 "resource_id": resources[n], "related_resource_id": 1 if n == 4 else 2 if n == 5 else 0,
                 "duration_ns": 100, "status": 2 if n == 3 else 0, "status_present": 0 if n == 4 else 1}
                for n, symbol in enumerate(symbols)]

    def inspect(self, body, mode="events"):
        return l02.inspect_output(self.output(body), mode, self.library, self.identity)

    def test_exact_responsibilities_and_mutations(self):
        body = [self.ordinary(), *self.events(), self.stats()]
        self.inspect(body)
        for index, key, value in ((5, "phase", 1), (5, "status_present", 1), (6, "related_resource_id", 0),
                                  (4, "status", 0), (2, "record_id", 1), (3, "resource_id", 99),
                                  (12, "completed_calls", 11), (0, "close", "requested")):
            changed = copy.deepcopy(body); changed[index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(ValueError): self.inspect(changed)
        with self.assertRaises(ValueError): self.inspect(body[:-1])
        with self.assertRaises(ValueError): self.inspect(body + [self.stats()])

    def test_default_off_does_not_mean_protection_off(self):
        body = [self.ordinary(), self.stats(events=0, enabled=0)]
        self.inspect(body, "off")
        body[-1]["completed_calls"] = 0
        with self.assertRaises(ValueError): self.inspect(body, "off")
        with self.assertRaises(ValueError): self.inspect([{"result": "passed"}], "ordinary")

    def test_fifo_capacity_not_just_event_count(self):
        events = [{"record_id": n, "symbol_id": 3, "phase": 1, "resource_id": 1,
                   "related_resource_id": 0, "duration_ns": 1, "status": 0, "status_present": 1} for n in range(1, 65)]
        body = events + [self.stats(events=64, calls=88, failures=0, drops=23)]
        self.inspect(body, "full")
        changed = copy.deepcopy(body); changed[0]["record_id"] = 65
        with self.assertRaises(ValueError): self.inspect(changed, "full")
        changed = copy.deepcopy(body); changed[-1]["dropped_events"] = 22
        with self.assertRaises(ValueError): self.inspect(changed, "full")
        with self.assertRaises(ValueError): self.inspect(body[1:], "full")

    def test_stubs_cannot_claim_native_or_hide_create(self):
        for mode in range(6):
            row = {"scope": "stub-only", "mode": mode, "kind": 2 if mode == 5 else mode,
                   "bootstrap_calls": 1, "create_calls": int(mode in (0, 4)), "result": "passed"}
            l02.inspect_output(json.dumps(row), "stub", None, None, stub=mode)
            changed = dict(row, create_calls=2)
            with self.assertRaises(ValueError): l02.inspect_output(json.dumps(changed), "stub", None, None, stub=mode)

    def test_exact_exports_and_contract(self):
        for group, count in zip(l02.GROUPS, (7, 14, 9, 16)):
            symbols = l02.expected_exports(group); self.assertEqual(len(symbols), count)
            output = "\n".join("000 T _" + name for name in symbols)
            contract = {"symbols": [{"shape": {"link_name": name}} for name in symbols - l02.TEST]}
            l02.inspect_exports(output, group, contract)
            for bad in (output + "\n000 T _madb_fixture_unknown", "\n".join(output.splitlines()[1:])):
                with self.assertRaises(l02.CandidateError): l02.inspect_exports(bad, group, contract)
            with self.assertRaises(l02.CandidateError): l02.inspect_exports(output, group, {"symbols": []})

    def test_fixed_pins_and_native_identity(self):
        pins = [name + "=sha256:" + str(i) * 64 for i, name in enumerate(l02.GROUPS)]
        self.assertEqual(len(l02.parse_pins(pins)), 4)
        for invalid in (pins[:-1], pins + [pins[0]], [p.replace("sha256:", "") for p in pins]):
            with self.assertRaises(ValueError): l02.parse_pins(invalid)
        output = self.output([self.ordinary()])
        for invalid in (output.replace('"pid": 123', '"pid": true'), output.replace("1" * 64, "3" * 64),
                        output.replace(str(self.library), "/private/tmp/wrong-library")):
            with self.assertRaises(ValueError): l02.inspect_output(invalid, "ordinary", self.library, self.identity)

    def test_clean_actual_lab_revision_required(self):
        with tempfile.TemporaryDirectory(prefix="madb-l02-clean-gate-") as directory:
            root = Path(directory)
            def git(*args): return subprocess.check_output(["git", "-C", root, *args], stderr=subprocess.DEVNULL, text=True).strip()
            git("init"); (root / "source").write_text("fixed")
            git("add", "source"); git("-c", "user.name=Lab Fixture", "-c", "user.email=fixture@invalid", "commit", "-m", "fixture")
            revision = git("rev-parse", "HEAD"); self.assertEqual(set(l02.lab_identity(root, revision)), {"source"})
            with self.assertRaises(ValueError): l02.lab_identity(root, "0" * 40)
            (root / "untracked").write_text("dirty")
            with self.assertRaises(ValueError): l02.lab_identity(root, revision)

    def test_provisional_producer_and_wrong_candidate_are_rejected(self):
        digest, producer, target = "sha256:" + "1" * 64, "2" * 40, "aarch64-apple-darwin"
        candidate = {"manifest": {"candidate_digest": digest, "required_cases": ["c05.existing"],
                                  "files": [{"path": "include/madb_rust.h"}, {"path": "include/madb_rust_client.h"}],
                                  "selector": {"profile_id": "c05-c-to-rust-" + target, "target": target,
                                               "route": "RUST-C-ABI", "direction": "consumer-to-provider"}},
                     "provenance": {"producer_revision": producer}}
        l02.check_selection("c-to-rust", candidate, digest, producer, target)
        candidate["provenance"]["provisional"] = True
        with self.assertRaises(l02.CandidateError): l02.check_selection("c-to-rust", candidate, digest, producer, target)
        candidate["provenance"]["provisional"] = False
        with self.assertRaises(l02.CandidateError): l02.check_selection("c-to-rust", candidate, "sha256:" + "3" * 64, producer, target)
        candidate["manifest"]["required_cases"].append("l02.unknown")
        with self.assertRaises(l02.CandidateError): l02.check_selection("c-to-rust", candidate, digest, producer, target)

    def test_consumer_sdk_bytes_and_producer_only_receipts_are_distinct(self):
        with tempfile.TemporaryDirectory(prefix="madb-l02-sdk-gate-") as directory:
            root = Path(directory); sdk = root / "sdk"; sdk.mkdir(); resource = root / "resource"; resource.mkdir()
            (sdk / "header").write_bytes(b"sdk"); (resource / "header").write_bytes(b"resource")
            receipt = {"sdk_inputs": [{"name": "sdk/header", **l02.reference(sdk / "header")},
                                      {"name": "clang-resource/header", **l02.reference(resource / "header")},
                                      {"name": "native/producer.rlib", "sha256": "sha256:" + "1" * 64, "size": 10}]}
            result = l02.sdk_binding(receipt, sdk, resource)
            self.assertEqual(len(result["consumer_sdk_bytes"]), 2)
            self.assertEqual(set(result["producer_only_native_receipts"]), {"native/producer.rlib"})
            (sdk / "header").write_bytes(b"modified")
            with self.assertRaises(l02.CandidateError): l02.sdk_binding(receipt, sdk, resource)

    def test_timing_requires_actual_samples(self):
        samples = [{"sample": n, "iterations": 800, "batches": 25, "duration_ns": 1234} for n in range(5)]
        self.inspect(samples, "timing-off")
        with self.assertRaises(ValueError): self.inspect(samples[:-1], "timing-off")
        samples[0]["duration_ns"] = 0
        with self.assertRaises(ValueError): self.inspect(samples, "timing-off")

    def test_rejected_control_preserves_exact_bootstrap_and_stats(self):
        event = {"record_id": 1, "symbol_id": 1, "phase": 1, "resource_id": 0,
                 "related_resource_id": 0, "duration_ns": 10, "status": 0, "status_present": 1}
        body = [event, self.stats(events=1, calls=1, failures=0, callbacks=0)]
        self.inspect(body, "rejections")
        for key, value in (("symbol_id", 3), ("phase", 2), ("resource_id", 99), ("related_resource_id", 7), ("status", 5), ("status_present", 0)):
            changed = copy.deepcopy(body); changed[0][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError): self.inspect(changed, "rejections")
        for key, value in (("events", 0), ("failed_calls", 99), ("completed_callbacks", 99), ("capture_enabled", 0)):
            changed = copy.deepcopy(body); changed[1][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError): self.inspect(changed, "rejections")

    def test_concurrent_final_capture_and_every_pulled_event(self):
        event = {"record_id": 1, "symbol_id": 3, "phase": 1, "resource_id": 7,
                 "related_resource_id": 0, "duration_ns": 10, "status": 0, "status_present": 1}
        work = {"concurrent_work": 4000, "engine": 7, "controller_events": 1, "busy_observed": 0}
        stats = self.stats(events=0, calls=4005, failures=0, callbacks=0, enabled=0)
        self.inspect([event, work, stats], "concurrent")
        # Empty and nonempty observations both remain legal; no scheduler-specific
        # requirement that contention, drops or a particular event count occurs.
        self.inspect([dict(work, controller_events=0), stats], "concurrent")
        for capture in (1, 2):
            with self.assertRaises(ValueError): self.inspect([event, work, dict(stats, capture_enabled=capture)], "concurrent")
        for key, value in (("record_id", 0), ("symbol_id", 1), ("phase", 2), ("resource_id", 99), ("related_resource_id", 7), ("status", 5), ("status_present", 0)):
            changed = dict(event); changed[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError): self.inspect([changed, work, stats], "concurrent")
        with self.assertRaises(ValueError): self.inspect([work, stats], "concurrent")

    def test_case_coverage_cannot_inherit_another_headers_mismatch(self):
        rows = [{"group": group, "case": mode} for group, cases in l02.L02_CASES.items()
                for mode in sorted(set(mode for modes in cases.values() for mode in modes) - {"actual-mismatch"})]
        for provider in ("c-to-rust-test", "c-to-rust-diagnostics-test"):
            rows.append({"header_group": "c-to-rust-diagnostics", "library_group": provider, "case": "actual-mismatch"})
        self.assertEqual(len(l02.case_results(rows)), 5)
        changed = copy.deepcopy(rows); changed[-1]["header_group"] = "c-to-rust"
        with self.assertRaises(l02.CandidateError): l02.case_results(changed)
        changed = copy.deepcopy(rows); changed[-1]["library_group"] = "c-to-rust-test"
        with self.assertRaises(l02.CandidateError): l02.case_results(changed)


if __name__ == "__main__": unittest.main()
