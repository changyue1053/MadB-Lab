"""L02 independent observation and refusal checks, not native runtime evidence."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("verify_l02", Path(__file__).with_name("verify_l02.py"))
l02 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(l02)
import l02_reports as records


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

    def test_incomplete_or_ill_typed_rows_are_errors_before_postconditions(self):
        resource = {"resource_balance": True, "context_released_after_drain": True}
        cases = [
            ("ordinary", [self.ordinary()], {}),
            ("events", [self.ordinary(), *self.events(), self.stats()], {}),
            ("operation-close", [{"held": "operation", "await": "TIMEOUT", "release": "BUSY"}, resource], {}),
            ("exhaustion", [{"checked_kind": 4, "native_failure": "RESOURCE_EXHAUSTED"}, resource], {}),
            ("fault-isolation", [self.ordinary(), {"test_fault": 3, "ordinary_semantics_unchanged": True}, resource], {}),
            ("exporter", [self.ordinary(), {"exporter": "consumer-blocked-dropped", "ordinary_completed_before_exporter_release": True}], {}),
            ("self-wait", [{"self_wait": "WOULD_DEADLOCK", "observe": "CLOSING", "close": "confirmed"}], {}),
            ("mismatch", [{"checked_kind": 3, "created_delta": 0, "native_status": 0}], {"mismatch": 3}),
            ("timing-off", [{"sample": n, "iterations": 800, "batches": 25, "duration_ns": 100} for n in range(5)], {}),
            ("concurrent", [{"concurrent_work": 4000, "engine": 1, "controller_events": 0, "busy_observed": 0},
                            self.stats(events=0, calls=4005, failures=0, callbacks=0, enabled=0)], {}),
        ]
        for mode, body, kwargs in cases:
            rows = json.loads("[" + self.output(body).replace("\n", ",") + "]")
            l02.inspect_output("\n".join(json.dumps(row) for row in rows), mode, self.library, self.identity, **kwargs)
            shapes = set()
            for index, row in enumerate(rows):
                shape = tuple(sorted(row))
                if shape in shapes: continue
                shapes.add(shape)
                for key in row:
                    for missing in (True, False):
                        changed = copy.deepcopy(rows)
                        if missing: del changed[index][key]
                        else: changed[index][key] = []
                        with self.subTest(mode=mode, key=key, missing=missing), self.assertRaises(ValueError) as caught:
                            l02.inspect_output("\n".join(json.dumps(row) for row in changed), mode, self.library, self.identity, **kwargs)
                        self.assertNotIsInstance(caught.exception, l02.ObservationFailure)
        stub = {"scope": "stub-only", "mode": 0, "kind": 0, "bootstrap_calls": 1, "create_calls": 1, "result": "passed"}
        for key in stub:
            for missing in (True, False):
                changed = dict(stub)
                if missing: del changed[key]
                else: changed[key] = []
                with self.subTest(stub_key=key, missing=missing), self.assertRaises(ValueError) as caught:
                    l02.inspect_output(json.dumps(changed), "stub", None, None, stub=0)
                self.assertNotIsInstance(caught.exception, l02.ObservationFailure)

    def test_complete_wrong_values_remain_failures_and_missing_events_are_errors(self):
        for body, mode in (([dict(self.ordinary(), sum=512)], "ordinary"),
                           ([{"self_wait": "WOULD_DEADLOCK", "observe": "OK", "close": "confirmed"}], "self-wait"),
                           ([{"held": "operation", "await": "TIMEOUT", "release": "BUSY"},
                             {"resource_balance": False, "context_released_after_drain": True}], "operation-close"),
                           ([self.ordinary(), *self.events(), self.stats(failures=99)], "events")):
            with self.subTest(mode=mode), self.assertRaises(l02.ObservationFailure): self.inspect(body, mode)
        for output in (self.output([self.ordinary()]).replace('"pid": 123', '"pid": 0'),
                       self.output([self.ordinary()]).replace('"actual_identity": "' + '1' * 64, '"actual_identity": "' + '3' * 64)):
            with self.assertRaises(l02.ObservationFailure): l02.inspect_output(output, "ordinary", self.library, self.identity)
        with self.assertRaises(ValueError) as caught:
            self.inspect([self.ordinary(), *self.events()[1:], self.stats()])
        self.assertNotIsInstance(caught.exception, l02.ObservationFailure)


class L02LinuxChecks(unittest.TestCase):
    """Finite-path/receipt fixtures only; no Linux SDK execution is inferred."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="madb-l02-linux-binding-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.system = self.root / "system"; self.system.mkdir()
        self.resources = self.root / "resource"; (self.resources / "include").mkdir(parents=True)
        self.header = self.system / "stdint.h"; self.header.write_bytes(b"system-header")
        self.resource = self.resources / "include/stddef.h"; self.resource.write_bytes(b"resource-header")
        self.header_ref = l02.reference(self.header)
        self.receipt = {"sdk_inputs": [
            {"name": "native/stdint.h-" + self.header_ref["sha256"][7:], **self.header_ref},
            {"name": "clang-resource/include/stddef.h", **l02.reference(self.resource)},
            {"name": "native/libstd-fixture.rlib-" + "1" * 64, "sha256": "sha256:" + "1" * 64, "size": 10}]}
        self.dependencies = {str(path): l02.reference(path) for path in (self.header, self.resource)}

    def bind(self, receipt=None, dependencies=None):
        return l02.linux_sdk_binding(self.receipt if receipt is None else receipt, self.resources, self.system,
                                    self.dependencies if dependencies is None else dependencies)

    def test_exact_platforms_compiler_flags_and_no_apple_environment_on_linux(self):
        self.assertEqual(l02.native_target("Linux", "x86_64", "glibc"), "x86_64-unknown-linux-gnu")
        self.assertEqual(l02.native_target("Darwin", "arm64", ""), "aarch64-apple-darwin")
        for host in (("Linux", "aarch64", "glibc"), ("Linux", "x86_64", "musl"), ("Windows", "AMD64", ""), ("Darwin", "x86_64", "")):
            with self.subTest(host=host), self.assertRaises(ValueError): l02.native_target(*host)
        flags, receipt = l02.compiler_configuration("x86_64-unknown-linux-gnu", None, self.resources)
        self.assertEqual(flags, ["-target", "x86_64-unknown-linux-gnu", "-resource-dir", str(self.resources)])
        self.assertNotIn("deployment_target", receipt)
        self.assertEqual(receipt["warnings"], ["-Wall", "-Wextra", "-Werror"])
        mac_flags, mac_receipt = l02.compiler_configuration("aarch64-apple-darwin", self.system, self.resources)
        self.assertEqual(mac_flags, ["-isysroot", str(self.system), "-resource-dir", str(self.resources), "-target", "arm64-apple-macosx14.0"])
        self.assertEqual(mac_receipt["deployment_target"], "14.0")
        with patch.dict(os.environ, {"SDKROOT": "/unit-apple-sdk", "DEVELOPER_DIR": "/unit-apple-developer"}):
            for system in ("Linux", "Darwin"):
                output = self.root / system; output.mkdir()
                with patch.object(l02.platform, "system", return_value=system): environment = l02.Commands(output).environment
                self.assertEqual(environment.get("HOME"), os.environ.get("HOME"))
                for name in ("SDKROOT", "DEVELOPER_DIR", "MACOSX_DEPLOYMENT_TARGET"):
                    self.assertEqual(name in environment, system == "Darwin")
        for group in l02.GROUPS:
            exports = l02.expected_exports(group)
            contract = {"symbols": [{"shape": {"link_name": name}} for name in exports - l02.TEST]}
            self.assertEqual(l02.inspect_exports("\n".join("000 T " + name for name in exports), group, contract), sorted(exports))

    def test_native_system_headers_are_bound_and_only_archives_are_producer_only(self):
        result = self.bind()
        self.assertEqual(len(result["consumer_sdk_bytes"]), 2)
        self.assertEqual(result["consumer_sdk_bytes"][self.receipt["sdk_inputs"][0]["name"]]["path"], str(self.header))
        self.assertEqual(set(result["producer_only_native_receipts"]), {self.receipt["sdk_inputs"][2]["name"]})
        changed = copy.deepcopy(self.receipt); changed["sdk_inputs"][0]["name"] = "native/stdint.h-" + "2" * 64
        with self.assertRaises(ValueError): self.bind(changed)
        changed = copy.deepcopy(self.receipt); changed["sdk_inputs"][2]["name"] = "native/unknown.bin-" + "1" * 64
        with self.assertRaises(ValueError): self.bind(changed)
        changed = copy.deepcopy(self.receipt); changed["sdk_inputs"].append(changed["sdk_inputs"][0])
        with self.assertRaises(ValueError): self.bind(changed)

    def test_missing_ambiguous_private_changed_and_unreceipted_headers_refuse(self):
        with self.assertRaises(ValueError): self.bind(dependencies={str(self.resource): self.dependencies[str(self.resource)]})
        alternate = self.system / "other"; alternate.mkdir(); duplicate = alternate / self.header.name; duplicate.write_bytes(self.header.read_bytes())
        with self.assertRaises(ValueError): self.bind(dependencies={**self.dependencies, str(duplicate): l02.reference(duplicate)})
        private = self.root / "producer-private.h"; private.write_bytes(b"private")
        with self.assertRaises(ValueError): self.bind(dependencies={**self.dependencies, str(private): l02.reference(private)})
        extra = self.system / "extra.h"; extra.write_bytes(b"extra")
        with self.assertRaises(ValueError): self.bind(dependencies={**self.dependencies, str(extra): l02.reference(extra)})
        link = self.system / "escape.h"; link.symlink_to(private)
        with self.assertRaises(ValueError): self.bind(dependencies={**self.dependencies, str(link): l02.reference(link)})
        self.header.write_bytes(b"changed")
        with self.assertRaises(ValueError): self.bind()
        with self.assertRaises(ValueError): self.bind(dependencies={**self.dependencies, str(self.header): l02.reference(self.header)})
        with self.assertRaises(ValueError): l02.linux_sdk_binding(self.receipt, self.resources, Path("/"), self.dependencies)

    def test_public_and_extra_consumer_dependency_sets_are_distinct(self):
        source = self.root / "source.c"; source.write_text("/* fixture */")
        extra = self.system / "pthread.h"; extra.write_bytes(b"extra-consumer-header")
        depfile = self.root / "consumer.d"
        depfile.write_text("madb-l02: " + " ".join(map(str, (source, self.header, self.resource, extra))) + "\n")
        inputs = l02.dependency_inputs(depfile, "madb-l02", [source], [self.system, self.resources])
        self.assertIn(str(extra), inputs)
        self.assertEqual(len(self.bind()["consumer_sdk_bytes"]), 2)
        with self.assertRaises(ValueError): self.bind(dependencies={path: ref for path, ref in inputs.items() if path != str(source)})
        depfile.write_text("wrong-target: " + str(source))
        with self.assertRaises(ValueError): l02.dependency_inputs(depfile, "madb-l02", [source], [self.system])
        depfile.write_text("madb-l02: " + str(self.header))
        with self.assertRaises(ValueError): l02.dependency_inputs(depfile, "madb-l02", [source], [self.system])
        private = self.root / "private.h"; private.write_bytes(b"private")
        depfile.write_text("madb-l02: " + str(source) + " " + str(private))
        with self.assertRaises(ValueError): l02.dependency_inputs(depfile, "madb-l02", [source], [self.system])

    def test_public_probe_uses_actual_depfile_and_both_public_headers(self):
        include = self.root / "include"; include.mkdir()
        for name in ("madb_rust.h", "madb_rust_client.h"): (include / name).write_text("/* public fixture */")
        output = self.root / "output"; output.mkdir()
        outer = self
        class ProbeCommands:
            system_roots = [outer.system, outer.resources]
            c_flags = ["-target", "x86_64-unknown-linux-gnu", "-resource-dir", str(outer.resources)]
            def __init__(self): self.output = output; self.calls = []
            def run(self, argv, timeout):
                self.calls.append([str(x) for x in argv])
                depfile = Path(argv[argv.index("-MF") + 1]); source = Path(argv[-1])
                depfile.write_text("madb-l02-public: " + " ".join(map(str, (source, include / "madb_rust.h", include / "madb_rust_client.h", outer.header, outer.resource))) + "\n")
                return "", "unit-only"
        commands = ProbeCommands()
        probe = l02.public_header_probe(commands, Path("/unit/compiler"), include, output)
        self.assertEqual(probe["system_dependencies"], self.dependencies)
        self.assertEqual(len(self.bind(dependencies=probe["system_dependencies"])["consumer_sdk_bytes"]), 2)
        self.assertIn("-M", commands.calls[0]); self.assertNotIn("-isysroot", commands.calls[0])
        self.assertEqual((output / probe["source"]["path"]).read_text(), '#include "madb_rust.h"\n#include "madb_rust_client.h"\n')


class L02ReportChecks(unittest.TestCase):
    """Formatting/control-flow fixtures only; these synthetic logs certify no SDK."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="madb-l02-report-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"; self.root.mkdir()
        self.output = Path(self.temporary.name) / "output"; self.output.mkdir()
        shutil.copytree(l02.ROOT / "cases/l02", self.root / "cases/l02")
        source = self.root / "consumers/c/l02_diagnostics.c"; source.parent.mkdir(parents=True)
        shutil.copyfile(l02.SOURCE, source)
        self.candidates = {}
        for n, (group, names) in enumerate(records.CASE_NAMES.items(), 1):
            digest = "sha256:" + str(n) * 64
            selector = {"route": "RUST-C-ABI", "profile_id": "unit-" + group, "profile_digest": digest,
                        "target": "unit-not-a-target", "direction": "consumer-to-provider"}
            self.candidates[group] = {"manifest": {"selector": selector, "candidate_digest": digest,
                                                   "required_cases": ["l02." + group + "." + name for name in names]},
                                      "provenance": {"input_digest": digest, "tool_digest": digest}}
        self.environment = [{"id": "unit-only", "version": "1", "sha256": "sha256:" + "3" * 64,
                             "host": "unit", "target": "unit-not-a-target", "source": "synthetic", "arguments": []}]
        self.book = records.Reports(self.root, self.output, self.candidates, "4" * 40, self.environment)
        self.local = {"result": "passed", "compile": "passed", "logs": []}

    def row(self, group, key):
        mode, capture, stub, provider = key
        return ({"header_group": group, "case": mode, "library_group": provider} if provider else
                {"group": group, "case": mode, "stub": stub} if stub is not None else
                {"group": group, "case": mode, "capture": capture})

    def complete(self, row):
        self.book.begin(row); self.book.started()
        path = self.output / ("unit-log-" + str(len(self.local["logs"])) + ".json")
        path.write_text(json.dumps({"argv": ["synthetic-unit-fixture"], "exit_code": 0, "timeout": False,
                                    "duration_ns": 1200000, "stdout": '{"result":"passed"}\n', "stderr": ""}))
        self.local["logs"].append(records.file_reference(path, self.output))
        self.book.complete(row, path.name)

    def all_completed(self):
        for group, names in records.CASE_NAMES.items():
            for name in names:
                for key in records.required_probes(name): self.complete(self.row(group, key))

    def write(self, failure=None):
        if failure: self.local["result"] = "failed"
        (self.output / "report.json").write_text(json.dumps(self.local))
        return [json.loads((self.output / item["path"]).read_text()) for item in self.book.write(self.local, failure)]

    def test_instances_are_fixed_before_any_target_and_match_each_selector(self):
        self.assertEqual(len(self.book.cases), 5)
        index = json.loads((self.output / "case-inputs.json").read_text())
        self.assertEqual(len(index["cases"]), 5)
        self.assertEqual(self.local["logs"], [])
        for key, case in self.book.cases.items():
            self.assertEqual(case["kind"], "instance")
            self.assertEqual(case["selector"], self.candidates[key[0]]["manifest"]["selector"])
            self.assertEqual(case["requires"]["environment"], [{"id": "unit-only", "version": "1"}])
            instance = self.output / self.book.references[key]["path"]
            self.assertEqual(records.case_digest(json.loads(instance.read_text())), records.case_digest(case))

    def test_standard_success_has_exact_five_cases_and_actual_attachments(self):
        self.all_completed(); self.book.verify()
        result = self.write()
        self.assertEqual([len(report["results"]) for report in result], [3, 2])
        for report in result:
            self.assertEqual(report["schema"], "madb.report/1")
            self.assertEqual(report["started_at"], self.book.started_at)
            self.assertEqual(report["identity"]["profile_digest"], report["selector"]["profile_digest"])
            for row in report["results"]:
                self.assertEqual(row["status"], "passed"); self.assertEqual(row["cleanup"], "complete")
                self.assertEqual(row["resource_observations"], []); self.assertEqual(row["blocked_by"], [])
                self.assertEqual((row["actual"]["kind"], row["actual"]["code"], row["actual"]["stage"], row["actual"]["exit_code"]), ("success", None, None, 0))
                for ref in row["attachments"]: self.assertEqual(records.file_reference(self.output / ref["path"], self.output), ref)

    def test_exact_steps_do_not_accept_missing_captures_stubs_or_other_headers(self):
        group = "c-to-rust-diagnostics"
        with self.assertRaises(ValueError): self.book.begin({"group": group, "case": "helper-stub", "stub": 0})
        self.complete({"group": group, "case": "ordinary", "capture": None})
        with self.assertRaises(ValueError): self.book.begin({"group": group, "case": "helper-stub", "stub": 1})
        self.assertIsNone(self.book.owner({"header_group": "c-to-rust", "case": "actual-mismatch", "library_group": "c-to-rust-test"}))
        with self.assertRaises(ValueError): self.book.verify()

    def test_changed_instance_catalog_fixture_or_raw_evidence_cannot_pass(self):
        self.all_completed()
        paths = [self.output / self.book.index_reference["path"], self.output / next(iter(self.book.references.values()))["path"],
                 self.root / "cases/l02/c-to-rust-diagnostics/diagnostics.json", self.root / "consumers/c/l02_diagnostics.c",
                 self.output / self.local["logs"][0]["path"]]
        for path in paths:
            original = path.read_bytes(); path.write_bytes(original + b" ")
            with self.subTest(path=path.name), self.assertRaises(ValueError): self.book.verify()
            path.write_bytes(original)
        self.book.verify()

    def test_watchdog_assertion_and_missing_evidence_fail_differently(self):
        row = {"group": "c-to-rust-diagnostics", "case": "ordinary", "capture": None}
        for timeout, code, stderr, expected in ((True, -9, "", "error"), (False, 2, "L02 assertion:123:x\n", "failed"),
                                                (False, 2, "other failure", "error"), (False, -11, "", "error")):
            self.book.begin(row); self.book.started()
            error = records.CommandFailure(self.output / "unit-failure.json", {"timeout": timeout, "exit_code": code, "stderr": stderr, "duration_ns": 3000000})
            report = self.write(error); results = [r for p in report for r in p["results"]]
            self.assertEqual(results[0]["status"], expected)
            self.assertEqual(results[0]["cleanup"], "failed")
            self.assertEqual(results[0]["duration_ms"], 3)
            for result in results[1:]:
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["blocked_by"], [results[0]["case_id"]])
                self.assertEqual(result["cleanup"], "not-run")
        result = self.write(ValueError("missing evidence"))
        self.assertEqual(result[0]["results"][0]["status"], "error")

    def test_shared_final_recheck_failure_never_retains_passes(self):
        self.all_completed(); self.book.verify()
        reports = self.write(ValueError("final compiler image changed"))
        results = [row for report in reports for row in report["results"]]
        self.assertEqual([row["status"] for row in results], ["error", "blocked", "blocked", "blocked", "blocked"])
        self.assertTrue(all(row["cleanup"] == "failed" for row in results))

    def test_budget_exhaustion_and_missing_raw_terminal_are_not_success(self):
        row = {"group": "c-to-rust-diagnostics", "case": "ordinary", "capture": None}
        self.book.begin(row); self.book.started()
        log = self.output / "missing-terminal.json"
        log.write_text(json.dumps({"exit_code": 0, "timeout": False, "duration_ns": 1, "stdout": ""}))
        with self.assertRaises(ValueError): self.book.complete(row, log.name)
        self.complete(row)
        key = ("c-to-rust-diagnostics", "checked-constructor")
        self.book.records[key][0]["duration_ns"] = self.book.cases[key]["timeout_policy"]["timeout_ms"] * 1000000
        with self.assertRaises(RuntimeError): self.book.begin({"group": key[0], "case": "helper-stub", "stub": 0})

    def test_runner_oracle_mismatch_is_failed_and_failed_launch_is_not_target_evidence(self):
        checks = L02Checks()
        body = checks.ordinary(); body["sum"] = 512
        path = self.output / "oracle-unit-only-log.json"
        class SyntheticCommands:
            def run(self, argv, timeout):
                output = checks.output([body])
                path.write_text(json.dumps({"exit_code": 0, "timeout": False, "duration_ns": 4500000, "stdout": output}))
                return output, path.name
        with self.assertRaises(records.ObservationFailure) as caught:
            l02.run_probe(SyntheticCommands(), {"observations": []}, self.book, ["unit-only"],
                          "c-to-rust-diagnostics", "ordinary", checks.library, checks.identity)
        reports = self.write(caught.exception)
        self.assertEqual(reports[0]["results"][0]["status"], "failed")
        self.assertEqual(reports[0]["results"][0]["evidence_level"], "target-run")
        self.assertEqual(reports[0]["results"][0]["duration_ms"], 4)
        self.book.begin({"group": "c-to-rust-diagnostics", "case": "ordinary", "capture": None})
        reports = self.write(OSError("process failed before launch"))
        self.assertEqual(reports[0]["results"][0]["status"], "error")
        self.assertEqual(reports[0]["results"][0]["evidence_level"], "compiled")
        self.assertEqual(reports[0]["results"][0]["cleanup"], "not-run")


if __name__ == "__main__": unittest.main()
