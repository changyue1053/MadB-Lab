"""Build/run one existing public companion's C09 pre-physical-ACK supplement."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import platform
import sys

from candidate import CandidateError, file_digest
from c07_candidate import verify_candidate
from c07_contract import SOURCE
from c07_controlled_execution import ControlledSession, companion_contracts
from c07_execution import BUNDLE, ExecutionError, Session, ref, write_json
from c07_kotlin_execution import kotlin_contracts
from c07_kotlin_thread_observations import FIELDS as THREAD_FIELDS
from c09_close_windows_observations import parse_observation
from runners.first_route import lab_source_identity

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENT = ROOT / "consumers/arkts/c09_close_windows"


class CloseWindowSession(ControlledSession):
    def __init__(self, args, candidate, scenario, contracts):
        super().__init__(args, candidate, scenario, contracts)
        self.start_dispatched = False

    def require_vacant_probe(self, label):
        observed = super().hdc(label, "shell", "pidof", BUNDLE, expected=None)
        if observed["stdout"].strip():
            raise ExecutionError("existing C07 probe process is not owned by this supplement; refusing install/start/stop")
        return observed

    def hdc(self, label, *args, **kwargs):
        if label == "stop-old-probe":
            # This legacy label becomes a vacancy check; never stop another run.
            return self.require_vacant_probe("exclusive-probe-before-start")
        if label == "start":
            self.start_dispatched = True
        return super().hdc(label, *args, **kwargs)

    def execute(self):
        observed = self.require_vacant_probe("exclusive-probe-before-install")
        write_json(self.args.output / "exclusive-probe.json", {
            "bundle": BUNDLE, "target": self.args.target, "preexisting_pid": observed["stdout"].strip(),
            "ownership": "explicit serial target reservation plus vacancy check before install and start",
            "recovery": "stop only after this run dispatched start; recovery stop is not native cleanup evidence"})
        return super().execute()

    def prepare(self):
        Session.prepare(self)
        target = self.root / "entry/src/main/ets"
        module = json.dumps(self.candidate["module"])
        template = "KotlinCloseWindows.ets.in" if self.args.route == "kotlin" else "NativeCloseWindows.ets.in"
        (target / "CloseWindows.ets").write_text((SUPPLEMENT / template).read_text().replace("@MADB_PUBLIC_MODULE@", module))
        if self.args.route != "kotlin":
            (target / "SupportChecks.ets").write_text((SOURCE / "controlled/SupportChecks.ets.in").read_text().replace("@MADB_PUBLIC_MODULE@", module))
            with (target / "ProbeConfig.ets").open("a") as stream:
                stream.write("export const EXPECTED_OBSERVATION_PREFIX: string = " + json.dumps(
                    "madb-observe/1/" + self.args.route + "/" + self.candidate["identity"]["expected_identity"]) + ";\n")
        callback = ""
        if self.args.route == "kotlin":
            callback = ", (label: string, value: string): void => {\n" + (
                "      hilog.info(0x0000, 'MadBC07Probe', 'C09_CLOSE_FRAME %{public}s %{public}s %{public}s', PROBE_NONCE, label, JSON.stringify(value));\n    }")
        (target / "pages/Index.ets").write_text((SUPPLEMENT / "Page.ets.in").read_text()
            .replace("@MADB_PUBLIC_MODULE@", module).replace("@TEXT_CALLBACK@", callback))

    def parse_observation(self, raw, pid):
        return parse_observation(raw, nonce=self.nonce, pid=pid, route=self.args.route)


def guarded_output(output, protected):
    """Reject aliases/ancestors/descendants before making any output directory."""
    output = output.resolve()
    for path in protected:
        path = path.resolve()
        if output.is_relative_to(path) or path.is_relative_to(output):
            raise ValueError("output overlaps protected source/candidate/tool/signing input: " + str(path))
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be empty; never replace prior evidence")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--route", choices=("c", "cpp", "rust", "kotlin"), required=True)
    parser.add_argument("--command-line-tools", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-only", action="store_true", help="compile only; no hdc/device operation")
    parser.add_argument("--target")
    parser.add_argument("--target-kind", choices=("emulator", "physical"))
    parser.add_argument("--allow-dirty", action="store_true")
    signing = parser.add_mutually_exclusive_group(required=True)
    signing.add_argument("--community-debug-signing", action="store_true")
    signing.add_argument("--signing-config", type=Path)
    args = parser.parse_args(argv)
    if not args.build_only and (not args.target or args.target.startswith("-") or
            any(char.isspace() or ord(char) < 32 for char in args.target) or not args.target_kind):
        parser.error("execution requires exactly one explicit target and target-kind")
    protected = [ROOT, args.candidate, args.command_line_tools, args.java_home]
    if args.signing_config:
        protected.append(args.signing_config)
    try:
        args.output = guarded_output(args.output, protected)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"task": "C09", "scope": "normal Runtime.close before physical ACK; existing frozen public companion",
        "expected_rejection": "AlreadyInitialized" if args.route == "kotlin" else "RuntimeAlreadyOpen",
        "oracle_note": "Kotlin occupied-slot spelling independently reviewed against frozen producer 18256fcc4b26cf3cd1e2e79c39b86c2512e012d9 bootstrap.cpp.in:170 and public facade error preservation; earlier cross-route expectation failure is retained, never relabeled",
        "build": "not-run", "execution": "not-run", "before_physical_ack": "missing",
        "after_physical_ack_before_receipt": {"status": "unavailable", "reason": "existing public facade exposes no deterministic before-receipt control point"},
        "certifies_c07": False, "certifies_c09": False, "errors": []}
    session = None
    try:
        if platform.python_version() != (ROOT / ".python-version").read_text().strip():
            raise RuntimeError("use the Lab's pinned Python")
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("candidate build requires its macOS Arm64 tool host")
        revision, dirty, source_digest = lab_source_identity(ROOT, None, args.allow_dirty)
        report.update(lab_revision=revision, lab_source_digest=source_digest, provisional=dirty)
        candidate = verify_candidate(args.candidate, args.route, companion=True)
        if candidate["provenance"].get("provisional", False):
            if not args.allow_dirty:
                raise CandidateError("ArtifactMismatch", "provisional candidate requires --allow-dirty")
            report["provisional"] = True
        candidate_digest = candidate["manifest"]["candidate_digest"]
        report.update(candidate_digest=candidate_digest, candidate_path=str(candidate["root"]), route=args.route)
        contract_reader = kotlin_contracts if args.route == "kotlin" else companion_contracts
        contracts, contract_inputs = contract_reader(candidate)
        if args.route == "kotlin":
            thread = contracts["thread-frame.json"]
            if thread.get("format") != 70604 or thread.get("length") != 21 or [f["name"] for f in thread["fields"]] != THREAD_FIELDS:
                raise CandidateError("ProfileMismatch", "public thread witness layout differs from independent C09 oracle")
        report["contract_inputs"] = contract_inputs
        write_json(args.output / "admission.json", {"candidate_digest": candidate_digest,
            "manifest_sha256": file_digest((candidate["root"] / "candidate.json").read_bytes()),
            "selector": candidate["manifest"]["selector"], "identity": candidate["identity"]})
        session = CloseWindowSession(args, candidate, "c09-normal-close-before-ack", contracts)
        report["nonce"] = session.nonce
        session.verify_tools(include_device=not args.build_only)
        if not args.build_only:
            report["target"] = session.verify_target()
        session.prepare()
        session.build()
        report["build"] = "passed"
        if not args.build_only:
            observation = session.execute()
            report["observation"] = observation
            report["execution"] = observation["status"]
            report["before_physical_ack"] = observation["status"]
        session.verify_closure("after")
        after = verify_candidate(args.candidate, args.route, companion=True)
        if after["manifest"]["candidate_digest"] != candidate_digest:
            raise CandidateError("ArtifactMismatch", "candidate changed during supplement")
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        report["errors"].append(str(error))
    finally:
        if session is not None and session.start_dispatched and not args.build_only:
            try:
                session.stop()
                report["recovery_stop"] = "complete; not native cleanup evidence"
            except (OSError, RuntimeError) as error:
                report["errors"].append("recovery stop failed: " + str(error))
        report["attachments"] = [ref(p, args.output) for p in sorted(args.output.iterdir()) if p.is_file()]
        write_json(args.output / "report.json", report)
    print(json.dumps({key: report[key] for key in ("build", "execution", "before_physical_ack", "errors")}, ensure_ascii=False))
    return int(bool(report["errors"]) or report["build"] != "passed" or
               not args.build_only and report["before_physical_ack"] != "passed")


if __name__ == "__main__":
    sys.exit(main())
