from pathlib import Path
import json
import sys
import tempfile
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from c06_contract import COMMON_CASES, ROUTES, required_cases
from candidate import CandidateError, shape_digest, type_references, verify_contract_digests, verify_error_channels
from c06_observations import observations, resource_observations
from c06_execution import ExecutionError, isolated_environment, precise_rejection, require_host
from c06_toolchain import verify_installation, verify_apple, tree_identity
from candidate import file_digest
from runners.c06 import result_record


class C06ObservationChecks(unittest.TestCase):
    def emit(self, *records):
        return "\n".join(json.dumps(record) for record in records)

    def test_exact_independent_observation_is_accepted(self):
        expected = {"sequence": "-9223372036854775808", "nullable": None}
        output = self.emit({"check": "sequence", "actual": "-9223372036854775808"},
                           {"check": "nullable", "actual": None}, {"result": "passed"})
        self.assertEqual(observations(output, expected=expected), expected)

    def test_completion_without_observation_is_rejected(self):
        with self.assertRaises(ValueError):
            observations('{"result":"passed"}', expected={"cancelled": True})

    def test_actual_cannot_be_taken_from_candidate_expected(self):
        with self.assertRaises(ValueError):
            observations(self.emit({"check": "cancelled", "actual": False}, {"result": "passed"}),
                         expected={"cancelled": True})

    def test_duplicate_or_late_terminal_is_rejected(self):
        for output in (self.emit({"result": "passed"}, {"result": "passed"}),
                       self.emit({"result": "passed"}, {"check": "x", "actual": 1}),
                       self.emit({"check": "x", "actual": 1}, {"check": "x", "actual": 1}, {"result": "passed"})):
            with self.subTest(output=output), self.assertRaises(ValueError):
                observations(output, expected={"x": 1})

    def test_boolean_is_not_an_integer_counter(self):
        with self.assertRaises(ValueError):
            observations(self.emit({"check": "completed", "actual": True}, {"result": "passed"}), expected={"completed": 1})

    def test_unknown_observation_cannot_replace_a_required_check(self):
        with self.assertRaises(ValueError):
            observations(self.emit({"check": "unrelated", "actual": 1}, {"result": "passed"}), expected={"required": 1})

    def test_missing_completion_or_invalid_json_is_rejected(self):
        for output in ('{"check":"x","actual":1}', 'not-json', ''):
            with self.subTest(output=output), self.assertRaises(ValueError):
                observations(output, expected={"x": 1})

    def test_resource_counters_need_balanced_exact_integer_counts(self):
        good = {"resource.callbacks": {"before": 0, "after": 0, "created": 2, "released": 2}}
        self.assertEqual(resource_observations(good)[0]["name"], "callbacks")
        for changed in (dict(before=0, after=1, created=2, released=1),
                        dict(before=0, after=0, created=True, released=1)):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                resource_observations({"resource.callbacks": changed})

    def test_four_routes_have_separate_required_case_identity(self):
        self.assertEqual(len(ROUTES), 4)
        identities = [required_cases(group) for group in ROUTES]
        self.assertEqual(sum(map(len, identities)), len(set.union(*identities)))
        self.assertEqual(len(COMMON_CASES), 12)
        self.assertEqual(sum(map(len, identities)), 54)


class C06ExecutionChecks(unittest.TestCase):
    def test_host_build_is_not_device_or_other_target_proof(self):
        with patch("c06_execution.platform.system", return_value="Linux"), patch("c06_execution.platform.machine", return_value="x86_64"):
            with self.assertRaises(RuntimeError): require_host()

    def test_platform_cache_and_loader_injections_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = isolated_environment(Path(directory))
            self.assertEqual(environment["HOME"], str(Path(directory) / "home"))
            for name in ("GRADLE_USER_HOME", "KONAN_DATA_DIR", "CARGO_HOME", "CLANG_MODULE_CACHE_PATH"):
                self.assertTrue(Path(environment[name]).is_relative_to(directory))
            for name in ("DYLD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH", "KOTLIN_OPTS"):
                self.assertNotIn(name, environment)

    def test_expected_rejection_needs_exact_stage_and_marker(self):
        error = ExecutionError("negative", "link", Path("log"))
        good = {"exit_code": 1, "timeout": False, "stderr": "Undefined symbols: madbIdentity", "stdout": ""}
        self.assertTrue(precise_rejection(error, good, stage="link", markers=("Undefined symbols", "madbIdentity")))
        for changed in ({**good, "exit_code": -6}, {**good, "timeout": True}, {**good, "stderr": "unrelated compile error"}):
            self.assertFalse(precise_rejection(error, changed, stage="link", markers=("Undefined symbols", "madbIdentity")))
        self.assertFalse(precise_rejection(error, good, stage="run", markers=("madbIdentity",)))

    def test_nested_boolean_cannot_impersonate_resource_count(self):
        output = '{"check":"resource","actual":{"created":true}}\n{"result":"passed"}'
        with self.assertRaises(ValueError): observations(output, expected={"resource": {"created": 1}})

    def test_duplicate_json_fields_are_rejected(self):
        output = '{"check":"x","actual":0,"actual":1}\n{"result":"passed"}'
        with self.assertRaises(ValueError): observations(output, expected={"x": 1})


class C06CleanupReportingChecks(unittest.TestCase):
    def record(self, error=None, rejection=None):
        expected = {"kind": "success"} if rejection is None else {"kind": "rejection", **rejection}
        return result_record({"id": "c06.fixture", "expected_result": expected}, "sha256:" + "0" * 64,
                             output="", log=None, report_root=Path("."), error=error, rejection=rejection)

    def test_runtime_failure_never_claims_sdk_cleanup_completed(self):
        for failure in (ExecutionError("signal", "run", Path("missing")), ValueError("missing drain observations")):
            with self.subTest(failure=failure):
                self.assertEqual(self.record(failure)["cleanup"], "failed")

    def test_compile_failure_has_no_executed_sdk_cleanup(self):
        self.assertEqual(self.record(ExecutionError("compiler unavailable", "compile", Path("missing")))["cleanup"], "not-run")

    def test_precise_pre_admission_rejection_has_no_live_sdk_to_drain(self):
        result = self.record(rejection={"code": "AbiMismatch", "stage": "link"})
        self.assertEqual(result["cleanup"], "complete")
        self.assertEqual(result["resource_observations"], [])


class C06ErrorChannelChecks(unittest.TestCase):
    def contract(self):
        return {"types": [{"id": "unit", "definition": {"kind": "unit"}},
                          {"id": "tag", "definition": {"kind": "integer", "signed": False, "width": 32}},
                          {"id": "error", "definition": {"kind": "variant", "tag_type": "tag",
                           "cases": [{"name": "Rejected", "payload": None}]}}], "observations": []}

    def symbol(self):
        return {"shape": {"kind": "sync", "calling_convention": "backend", "parameters": [], "result": "unit", "throws": "error"}}

    def test_error_shape_is_reachable_and_changes_signature_identity(self):
        contract = self.contract(); symbol = self.symbol()
        before = shape_digest(contract, symbol)
        contract["types"][2]["definition"]["cases"][0]["name"] = "Different"
        self.assertNotEqual(shape_digest(contract, symbol), before)

    def test_missing_error_type_cannot_be_ignored(self):
        symbol = self.symbol(); symbol["shape"]["throws"] = "absent"
        with self.assertRaises(CandidateError): shape_digest(self.contract(), symbol)

    def test_callback_error_channel_is_reachable(self):
        callback = {"kind": "callback", "parameters": [], "result": "unit", "throws": "error"}
        self.assertEqual(type_references(callback), ["unit", "error"])

    def test_erased_swift_error_is_a_backend_owned_resource(self):
        contract = self.contract(); contract["symbols"] = [self.symbol()]
        contract["types"][2]["definition"] = {"kind": "resource", "representation": "backend-handle", "owner": "swift.error"}
        verify_error_channels(contract)
        erased_digest = shape_digest(contract, contract["symbols"][0])
        contract["types"][2]["definition"]["owner"] = "different.runtime"
        self.assertNotEqual(erased_digest, shape_digest(contract, contract["symbols"][0]))

    def test_erased_error_cannot_claim_a_pointer_registry_or_enumerable_payload(self):
        contract = self.contract(); contract["symbols"] = [self.symbol()]
        for definition in (
            {"kind": "resource", "representation": "registry-u64", "owner": "swift.error"},
            {"kind": "resource", "representation": "opaque-pointer", "owner": "swift.error"},
            {"kind": "resource", "representation": "backend-handle", "owner": "swift.error", "cases": [{"name": "Fake"}]},
        ):
            contract["types"][2]["definition"] = definition
            with self.subTest(definition=definition), self.assertRaises(CandidateError): verify_error_channels(contract)

    def test_error_channel_rejects_non_variant_type(self):
        contract = self.contract(); symbol = self.symbol(); symbol["shape"]["throws"] = "unit"
        contract["symbols"] = [symbol]
        with self.assertRaises(CandidateError) as caught: verify_contract_digests(contract)
        self.assertEqual(caught.exception.code, "AbiMismatch")


class C06ManagedToolChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="madb-lab-managed-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "compiler").mkdir()
        self.binary = self.root / "compiler/tool"
        self.binary.write_bytes(b"independent compiler inventory fixture")
        self.binary.chmod(0o644)
        self.receipt = {"schema": "madb.managed-installation/1", "recipe_sha256": "sha256:" + "2" * 64,
                        "components": {"compiler": {"source": {"path": "compiler"}, "files": [
                            {"path": "tool", "sha256": file_digest(self.binary.read_bytes()), "size": self.binary.stat().st_size,
                             "executable": False}]}}}
        self.requirement = {"recipe_sha256": self.receipt["recipe_sha256"], "components": ["compiler"]}
        self.save()

    def save(self):
        data = json.dumps(self.receipt).encode()
        (self.root / "receipt.json").write_bytes(data)
        self.requirement["receipt_sha256"] = file_digest(data)

    def test_complete_independent_inventory_is_accepted(self):
        self.assertEqual(verify_installation(self.root, self.requirement), self.receipt)

    def test_changed_installed_binary_cannot_reuse_good_receipt(self):
        self.binary.write_bytes(b"modified")
        with self.assertRaises(CandidateError): verify_installation(self.root, self.requirement)

    def test_added_files_cannot_hide_in_an_installed_tool(self):
        (self.root / "compiler/unrecorded").write_text("unrecorded")
        with self.assertRaises(CandidateError): verify_installation(self.root, self.requirement)

    def test_executable_mode_is_part_of_tool_identity(self):
        self.binary.chmod(0o755)
        with self.assertRaises(CandidateError): verify_installation(self.root, self.requirement)

    def test_receipt_cannot_be_reanchored_by_an_untrusted_cli_hash(self):
        (self.root / "receipt.json").write_text("{}")
        with self.assertRaises(CandidateError): verify_installation(self.root, self.requirement)

    def test_native_download_lock_does_not_admit_a_developer_cache(self):
        self.receipt["components"]["kotlin-native"] = self.receipt["components"].pop("compiler")
        self.requirement["components"] = ["kotlin-native"]
        dependencies = self.root / "konan/dependencies"; dependencies.mkdir(parents=True)
        (dependencies / ".extracted").write_text("\n")
        cache = dependencies / "cache"; cache.mkdir(); (cache / ".lock").touch()
        self.save(); verify_installation(self.root, self.requirement)
        (cache / "untrusted.klib").write_bytes(b"unrecorded")
        with self.assertRaises(CandidateError): verify_installation(self.root, self.requirement)

    def test_compiler_symlink_must_stay_inside_its_component(self):
        (self.root / "outside").write_text("outside")
        link = self.root / "compiler/link"
        link.symlink_to("../outside")
        self.receipt["components"]["compiler"]["files"].append({"path": "link", "symlink": "../outside"})
        self.save()
        with self.assertRaises(CandidateError): verify_installation(self.root, self.requirement)


class C06AppleToolChecks(unittest.TestCase):
    def test_same_version_text_cannot_hide_a_different_compiler(self):
        toolchain = {"xcode": {"version": "27.0", "build": "FixtureBuild", "sdk_version": "27.0", "sdk_build": "FixtureSDK"},
                     "tools": [{"id": "c06-swiftc", "sha256": "sha256:" + "1" * 64, "size": 1}]}
        responses = ["Xcode 27.0\nBuild version FixtureBuild", "27.0", "FixtureSDK", "/fixture/swiftc"]
        with patch("c06_toolchain.subprocess.check_output", side_effect=responses), patch("c06_toolchain._stream_digest", return_value="sha256:" + "2" * 64):
            with self.assertRaises(CandidateError) as caught: verify_apple(toolchain)
        self.assertEqual(caught.exception.code, "ProfileMismatch")

    def test_header_content_and_executable_mode_change_tree_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); header = root / "public.h"; header.write_text("unsigned value(void);")
            before = tree_identity(root)
            header.write_text("signed value(void);")
            changed = tree_identity(root)
            self.assertNotEqual(before["sha256"], changed["sha256"])
            header.chmod(0o755)
            self.assertNotEqual(changed["sha256"], tree_identity(root)["sha256"])

    def test_sdk_tree_symlink_cannot_read_outside_declared_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "sdk"; root.mkdir()
            (Path(temporary) / "foreign.h").write_text("outside")
            (root / "foreign.h").symlink_to("../foreign.h")
            with self.assertRaises(CandidateError): tree_identity(root)


if __name__ == "__main__":
    unittest.main()
