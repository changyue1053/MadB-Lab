"""C05 report timing control flow only; no compiler or SDK is executed."""
from contextlib import ExitStack
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("c05_timing_runner", ROOT / "harness/runners/first_route.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class C05ReportTimingChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="madb-c05-timing-unit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / "candidate"; source.mkdir()
        (source / "artifact.bin").write_bytes(b"timing-only public fixture")
        self.output = self.root / "output"; self.output.mkdir()
        digest = "sha256:" + "1" * 64
        self.candidate = {
            "root": source,
            "manifest": {"selector": {"route": "RUST-C-ABI", "profile_id": "timing-unit", "profile_digest": digest,
                                      "target": "timing-unit", "direction": "consumer-to-provider"},
                         "candidate_digest": digest, "required_cases": ["c05.c-to-rust.data", "c05.c-to-rust.lifecycle"],
                         "files": [{"path": "artifact.bin"}]},
            "provenance": {"input_digest": digest, "tool_digest": digest}, "contract": {},
            "identity": {"interface_digest": digest, "profile_digest": digest},
        }
        self.args = SimpleNamespace(output=self.output, lab_revision="2" * 40, clang="never-invoked", cargo="never-invoked")
        self.environment = [{"id": "timing-unit-environment"}]
        self.now = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.after_action = datetime(2000, 1, 2, tzinfo=timezone.utc)
        self.events = []

    def read_clock(self, zone):
        self.assertIs(zone, timezone.utc)
        self.events.append("clock")
        return self.now

    def action(self, name):
        self.events.append(name)
        self.now = self.after_action

    def run_group(self, compilation_fails):
        instantiate = runner.instantiated_case

        def instantiate_after_start(*args):
            self.action("instantiate")
            return instantiate(*args)

        def compile_fixture(install, temporary, *args):
            self.action("compile")
            if compilation_fails:
                log = self.output / "failed-compile.json"
                log.write_text(json.dumps({"exit_code": 1, "timeout": False, "stderr": "unit compile failure"}))
                raise runner.ExecutionError("unit compile failure", "compile", log)
            return temporary / "never-executed-program"

        def run_fixture(command, **kwargs):
            self.action("target")
            log = kwargs["log"]; log.parent.mkdir(parents=True, exist_ok=True)
            output = '{"result":"passed"}\n'
            log.write_text(json.dumps({"stdout": output, "exit_code": 0, "timeout": False}))
            return output, 17

        with ExitStack() as stack:
            clock = stack.enter_context(patch.object(runner, "datetime"))
            clock.now.side_effect = self.read_clock
            stack.enter_context(patch.object(runner, "GROUPS", {"c-to-rust": ["data", "lifecycle"]}))
            stack.enter_context(patch.object(runner, "instantiated_case", side_effect=instantiate_after_start))
            stack.enter_context(patch.object(runner, "isolated_environment", return_value={}))
            stack.enter_context(patch.object(runner, "verify_candidate", side_effect=lambda *args: self.action("verify")))
            stack.enter_context(patch.object(runner, "verify_exports", side_effect=lambda *args: self.action("exports")))
            stack.enter_context(patch.object(runner, "compile_c", side_effect=compile_fixture))
            stack.enter_context(patch.object(runner, "run", side_effect=run_fixture))
            result = runner.run_group("c-to-rust", self.candidate, self.args, self.environment)
        self.assertEqual(result["started_at"], "2000-01-01T00:00:00Z")
        self.assertEqual(self.events[0], "clock")
        self.assertEqual(self.events.count("clock"), 1)
        self.assertIn("compile", self.events)
        self.assertEqual(result["selector"], self.candidate["manifest"]["selector"])
        self.assertEqual(result["environment"], self.environment)
        return result

    def test_normal_group_retains_start_before_definitions_compile_and_target(self):
        report = self.run_group(False)
        self.assertIn("target", self.events)
        self.assertEqual([item["status"] for item in report["results"]], ["passed", "passed"])

    def test_early_compile_failure_uses_same_group_start_and_blocking(self):
        report = self.run_group(True)
        self.assertNotIn("target", self.events)
        self.assertEqual([item["status"] for item in report["results"]], ["error", "blocked"])
        self.assertEqual(report["results"][1]["blocked_by"], [report["results"][0]["case_id"]])

    def test_integrity_time_precedes_copy_mutation_and_rejection(self):
        copytree = shutil.copytree

        def copy_after_start(*args, **kwargs):
            self.action("copy")
            return copytree(*args, **kwargs)

        def reject_mutated_copy(path):
            self.action("reject")
            self.assertTrue((path / "artifact.bin").read_bytes().endswith(b"tampered"))
            raise runner.CandidateError("ArtifactMismatch", "unit fixture changed")

        with patch.object(runner, "datetime") as clock, patch.object(runner.shutil, "copytree", side_effect=copy_after_start), \
                patch.object(runner, "verify_candidate", side_effect=reject_mutated_copy):
            clock.now.side_effect = self.read_clock
            runner.integrity_case(self.candidate, self.output, self.args.lab_revision, self.environment)
        report = json.loads((self.output / "packaging.report.json").read_text())
        self.assertEqual(self.events, ["clock", "copy", "reject"])
        self.assertEqual(report["started_at"], "2000-01-01T00:00:00Z")
        self.assertEqual(report["results"][0]["actual"]["kind"], "rejection")
        self.assertEqual(report["results"][0]["actual"]["code"], "ArtifactMismatch")
        self.assertEqual(report["results"][0]["status"], "passed")

    def test_report_serialization_cannot_obtain_a_new_start_time(self):
        captured = "2000-01-01T00:00:00Z"
        with patch.object(runner, "datetime") as clock:
            clock.now.side_effect = AssertionError("report writing must not recapture the clock")
            report = runner.report_for(self.candidate, self.args.lab_revision, [], self.environment, started_at=captured)
        self.assertEqual(report["started_at"], captured)


if __name__ == "__main__":
    unittest.main()
