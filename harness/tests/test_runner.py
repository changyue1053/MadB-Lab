from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("first_route", ROOT / "harness/runners/first_route.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerFailureChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="madb-lab-runner-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_program(self, program, timeout=3):
        return runner.run([sys.executable, "-c", program], cwd=self.root,
                          env=dict(os.environ), log=self.root / "log.json", timeout=timeout)

    def test_nonzero_program_is_not_a_success(self):
        with self.assertRaises(runner.ExecutionError): self.run_program("raise SystemExit(7)")

    def test_crashed_program_is_not_an_expected_negative(self):
        with self.assertRaises(runner.ExecutionError): self.run_program("import os; os.abort()")

    def test_watchdog_is_error_not_sdk_cleanup(self):
        with self.assertRaises(runner.ExecutionError) as caught:
            self.run_program("import time; time.sleep(10)", timeout=0.05)
        self.assertTrue(caught.exception.timeout)

    def test_empty_output_cannot_be_claimed_passed(self):
        with self.assertRaises(ValueError):
            runner.result_record({"id": "case", "expected_result": {"kind": "success"}},
                                 "sha256:" + "0" * 64, output="", report_root=self.root)

    def test_isolation_clears_user_injection_settings(self):
        environment = runner.isolated_environment(self.root)
        self.assertEqual(environment["HOME"], str(self.root / "home"))
        self.assertEqual(environment["CARGO_HOME"], str(self.root / "cargo-home"))
        for name in ("RUSTFLAGS", "DYLD_LIBRARY_PATH", "LD_PRELOAD", "CPATH", "LIBRARY_PATH"):
            self.assertNotIn(name, environment)

    def test_expected_rejection_cannot_fabricate_actual_rejection(self):
        case = {"id": "case", "expected_result": {"kind": "rejection", "code": "Invented", "stage": "link"}}
        with self.assertRaises(ValueError):
            runner.result_record(case, "sha256:" + "0" * 64, output='{"result":"passed"}', report_root=self.root)

    def test_blocked_link_case_has_no_compilation_evidence(self):
        case = {"id": "case", "expected_result": {"kind": "rejection", "code": "MissingBootstrap", "stage": "link"}}
        result = runner.result_record(case, "sha256:" + "0" * 64, status="blocked", error="compiler unavailable", report_root=self.root)
        self.assertEqual(result["evidence_level"], "static")
        self.assertEqual(result["cleanup"], "not-run")

    def test_resource_leak_is_not_a_success(self):
        case = {"id": "case", "expected_result": {"kind": "success"}}
        with self.assertRaises(ValueError):
            runner.result_record(case, "sha256:" + "0" * 64, output='{"resources":{"active_operations":1,"source_leases":0,"registry_entries":0}}\n{"result":"passed"}', report_root=self.root)

    def test_linker_timeout_cannot_pass_missing_bootstrap_negative(self):
        error = runner.ExecutionError("timeout", "compile", self.root / "log.json", True)
        log = {"timeout": True, "exit_code": -9, "stderr": "Undefined symbols: madb_fixture_bootstrap"}
        self.assertFalse(runner.missing_bootstrap_rejection(error, log))

    def test_linker_crash_cannot_pass_missing_bootstrap_negative(self):
        error = runner.ExecutionError("signal", "compile", self.root / "log.json")
        log = {"timeout": False, "exit_code": -6, "stderr": "Undefined symbols: madb_fixture_bootstrap"}
        self.assertFalse(runner.missing_bootstrap_rejection(error, log))

    def test_precise_missing_bootstrap_link_error_is_accepted(self):
        error = runner.ExecutionError("link failed", "compile", self.root / "log.json")
        log = {"timeout": False, "exit_code": 1, "stderr": "Undefined symbols: madb_fixture_bootstrap"}
        self.assertTrue(runner.missing_bootstrap_rejection(error, log))

    def test_arbitrary_lab_revision_is_rejected(self):
        with patch.object(runner.subprocess, "check_output", return_value="a" * 40):
            with self.assertRaises(ValueError):
                runner.lab_source_identity(self.root, "b" * 40, True)

    def test_dirty_lab_cannot_emit_formal_revision_evidence(self):
        with patch.object(runner.subprocess, "check_output", side_effect=["a" * 40, b" M harness/runner.py"]):
            with self.assertRaises(ValueError):
                runner.lab_source_identity(self.root, None, False)

    def test_explicit_development_run_records_actual_source_digest(self):
        (self.root / "source.py").write_bytes(b"actual source")
        with patch.object(runner.subprocess, "check_output", side_effect=["a" * 40, b"?? source.py", b"source.py\0"]):
            revision, provisional, digest = runner.lab_source_identity(self.root, None, True)
        self.assertEqual(revision, "a" * 40)
        self.assertTrue(provisional)
        self.assertTrue(digest.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
