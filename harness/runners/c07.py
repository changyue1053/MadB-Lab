"""Run independent ArkTS consumers against an exact public HAR candidate."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from candidate import CandidateError, file_digest, read_json, semantic_digest
from c07_candidate import verify_candidate
from c07_contract import ROUTES, SOURCE, case_requirements
from c07_execution import ExecutionError, Session, ref, write_json
from c07_generation import run_generation
from check_cases import errors as case_errors
from check_repository import dependency_errors, snapshot_errors
from runners.first_route import instantiated_case, lab_source_identity


EXECUTABLE_TARGET_GROUPS = {"ordinary", "values", "output-copy", "distribution"}


def registered_fixture(requirement):
    prefix, name = requirement["id"].split(".")[1:]
    return (ROOT / "cases/c07" / prefix / (name + ".json")).is_file()


def case_for(requirement, candidate):
    prefix, name = requirement["id"].split(".")[1:]
    path = ROOT / "cases/c07" / prefix / (name + ".json")
    if path.is_file():
        return instantiated_case("c07/" + prefix, name, candidate)
    # Required but not registered: preserve it in the report as blocked, with an
    # exact independent requirement fixture. This never declares executable coverage.
    source = SOURCE / "requirements.json"
    case = {"schema": "madb.case/1", "id": requirement["id"], "kind": "instance",
        "selector": candidate["manifest"]["selector"], "problem_ids": requirement["problem_ids"], "source_ids": [],
        "requires": {"features": [], "environment": []}, "fixture": dict(ref(source, ROOT), schema="madb.lab-source/1"),
        "setup": [{"id": "missing-fixture", "action": "environment", "entrypoint": "unimplemented-public-fixture", "arguments": []}],
        "steps": [{"id": "required", "action": "call", "entrypoint": name, "arguments": []}],
        "assertions": [{"observation": name, "operator": "equals", "expected": [{"kind": "string", "value": requirement["independent_expectation"]}]}],
        "expected_result": {"kind": "success"},
        "cleanup": [{"id": "none", "action": "cleanup", "entrypoint": "not-executed", "arguments": []}],
        "timeout_policy": {"timeout_ms": 50000, "on_timeout": "error", "recovery": "isolate"}}
    return case, semantic_digest("madb.case/1", case)


def record(case, digest, status, reason, *, duration, attachments, cleanup, evidence_level="target-run"):
    return {"case_id": case["id"], "case_digest": digest, "status": status, "expected": case["expected_result"],
        "actual": {"kind": "success" if status == "passed" else "unavailable", "code": None, "stage": None,
                   "exit_code": 0 if status == "passed" else None, "reason": reason},
        "evidence_level": evidence_level if status == "passed" else "static", "duration_ms": duration,
        "resource_observations": [], "diagnostics": [] if status == "passed" else [{"code": "LAB.C07", "message": reason, "location": None}],
        "cleanup": cleanup, "attachments": attachments, "blocked_by": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--route", choices=tuple(ROUTES), required=True)
    parser.add_argument("--companion", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--command-line-tools", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--target", help="one explicit hdc target, never enumerated")
    parser.add_argument("--target-kind", choices=("emulator", "physical"))
    signing = parser.add_mutually_exclusive_group()
    signing.add_argument("--community-debug-signing", action="store_true")
    signing.add_argument("--signing-config", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--generation-only", action="store_true", help="run public generation without any device operation")
    parser.add_argument("--generator-cli", type=Path)
    parser.add_argument("--generation-fixtures", type=Path)
    parser.add_argument("--cli-inventory", type=Path)
    parser.add_argument("--cli-inventory-sha256")
    parser.add_argument("--lab-revision")
    parser.add_argument("--producer-revision")
    args = parser.parse_args(argv)
    args.output = args.output.resolve()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be empty; reports cannot overwrite earlier runs")
    args.output.mkdir(parents=True, exist_ok=True)
    generation_inputs = (args.generator_cli, args.generation_fixtures, args.cli_inventory, args.cli_inventory_sha256)
    if any(generation_inputs) and not all(generation_inputs):
        parser.error("generation requires --generator-cli, --generation-fixtures, --cli-inventory and --cli-inventory-sha256")
    if args.generation_only and (not all(generation_inputs) or args.companion or args.route != "c"):
        parser.error("--generation-only currently requires all public generation inputs and ordinary --route c")
    if not args.generation_only:
        if not args.target or any(char.isspace() or ord(char) < 32 for char in args.target) or args.target.startswith("-"):
            parser.error("--target must name one explicit target")
        if not args.target_kind or not (args.community_debug_signing or args.signing_config):
            parser.error("target execution requires explicit --target-kind and signing choice")
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        if platform.python_version() != (ROOT / ".python-version").read_text().strip():
            raise RuntimeError("use the Lab's pinned Python version")
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("this build profile requires its declared macOS Arm64 tool host")
        findings = case_errors(ROOT) + dependency_errors(ROOT) + snapshot_errors(ROOT)
        if findings:
            raise ValueError("; ".join(findings))
        revision, provisional, source_digest = lab_source_identity(ROOT, args.lab_revision, args.allow_dirty)
        candidate = verify_candidate(args.candidate, args.route, companion=args.companion)
        admitted_manifest_hash = file_digest((candidate["root"] / "candidate.json").read_bytes())
        if args.producer_revision and candidate["provenance"]["producer_revision"] != args.producer_revision:
            raise CandidateError("ArtifactMismatch", "candidate differs from pinned producer revision")
        if candidate["provenance"].get("provisional", False):
            if not args.allow_dirty:
                raise CandidateError("ArtifactMismatch", "provisional candidate cannot produce formal acceptance")
            provisional = True
        write_json(args.output / "admission.json", {"candidate_digest": candidate["manifest"]["candidate_digest"],
            "candidate_file": {"sha256": file_digest((candidate["root"] / "candidate.json").read_bytes()), "source": str(candidate["root"])},
            "profile": candidate["manifest"]["selector"], "identity": candidate["identity"],
            "required_scope": candidate["scope"], "embedded_identity_binding": candidate["identity_binding"], "lab_source_digest": source_digest})
        execution_error, observed, target, session = None, None, {}, None
        generation, generation_error = None, None
        begin = time.monotonic()
        if not args.companion:
            try:
                session = Session(args, candidate)
                session.verify_tools(include_device=not args.generation_only)
                if all(generation_inputs):
                    try:
                        generation = run_generation(session, deadline=begin + 600)
                    except (OSError, RuntimeError, ValueError, KeyError, StopIteration) as error:
                        generation_error = str(error)
                if not args.generation_only:
                    target = session.verify_target()
                    session.prepare()
                    session.build()
                    observed = session.execute()
                session.verify_closure("after")
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                execution_error = str(error)
            finally:
                if session is not None and hasattr(session, "hap"):
                    try:
                        session.stop()
                    except (OSError, RuntimeError) as error:
                        execution_error = (execution_error + "; " if execution_error else "") + "test recovery stop failed: " + str(error)
        duration = int((time.monotonic() - begin) * 1000)
        if generation is not None and duration >= 600000:
            generation_error = "overall generation watchdog expired including final tool closure check"
        final_candidate = verify_candidate(args.candidate, args.route, companion=args.companion)
        if (final_candidate["manifest"]["candidate_digest"] != candidate["manifest"]["candidate_digest"] or
                file_digest((candidate["root"] / "candidate.json").read_bytes()) != admitted_manifest_hash):
            raise CandidateError("ArtifactMismatch", "candidate was replaced during execution")
        if lab_source_identity(ROOT, revision, args.allow_dirty)[2] != source_digest:
            raise CandidateError("ArtifactMismatch", "Lab source changed during execution")
        command_refs = [ref(path, args.output) for path in sorted((args.output / "commands").glob("*.json"))]
        write_json(args.output / "command-manifest.json", {"commands": command_refs})
        archive_refs = [ref(path, args.output) for path in sorted(args.output.iterdir()) if path.is_file()]
        results = []
        for requirement in case_requirements(candidate["profile"]["id"]):
            case, digest = case_for(requirement, candidate)
            case_path = args.output / "cases" / (case["id"] + ".json")
            write_json(case_path, case)
            name = requirement["matrix_id"]
            if args.companion:
                status, reason = "blocked", "candidate-only controlled runner wiring and complete per-case oracle are not yet implemented; development observations are not transferred"
            elif not registered_fixture(requirement):
                status, reason = "blocked", "required executable case fixture is not registered"
            elif name == "generation":
                if execution_error or generation_error:
                    status, reason = "error", execution_error or generation_error
                elif generation:
                    status, reason = generation["status"], generation["reason"]
                else:
                    status, reason = "blocked", "required explicit public generator CLI/author fixtures were not supplied; HAR success is insufficient"
            elif args.generation_only:
                status, reason = "blocked", "generation-only invocation did not build/install/run this target case"
            elif name not in EXECUTABLE_TARGET_GROUPS:
                status, reason = "blocked", "required target group has no executable consumer oracle"
            elif execution_error:
                status, reason = "error", execution_error
            elif observed is None:
                status, reason = "error", "no actual target observation"
            else:
                status, reason = "passed", "exact candidate HAR was independently installed, Release-obfuscated, and actual ordinary consumer assertions matched on " + args.target_kind
            cleanup = "complete" if name == "generation" and generation else "not-run" if status == "blocked" else "complete" if observed and session.stopped else "failed"
            results.append(record(case, digest, status, reason, duration=duration,
                attachments=archive_refs + [ref(case_path, args.output)], cleanup=cleanup,
                evidence_level="host-run" if name == "generation" else "target-run"))
        catalog = b"".join(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() for path in sorted((ROOT / "cases").rglob("*.json")))
        manifest, provenance = candidate["manifest"], candidate["provenance"]
        environment = []
        if (args.output / "tools.json").is_file():
            observed_tools = read_json(args.output / "tools.json")
            for index, item in enumerate(observed_tools["inputs"]):
                environment.append({"id": "c07-consumed-tool-" + str(index), "version": "candidate-bound-bytes",
                    "sha256": item["sha256"], "host": "aarch64-apple-darwin", "target": "aarch64-linux-ohos",
                    "source": item["path"], "arguments": []})
        report = {"schema": "madb.report/1", "run_id": ("provisional." if provisional else "") + "c07." + candidate["profile"]["id"],
            "identity": {"input_digest": provenance["input_digest"], "tool_digest": provenance["tool_digest"],
                         "profile_digest": manifest["selector"]["profile_digest"], "candidate_digest": manifest["candidate_digest"],
                         "lab_revision": revision, "case_catalog_digest": file_digest(catalog)},
            "selector": manifest["selector"], "started_at": started, "environment": environment, "results": results}
        if provisional:
            report["extensions"] = {"madb.lab-source-state": "provisional", "madb.lab-source-digest": source_digest}
        write_json(args.output / "report.json", report)
        print("C07: " + ", ".join(item["case_id"] + "=" + item["status"] for item in results))
        return 0 if all(item["status"] == "passed" for item in results) else 1
    except (CandidateError, RuntimeError, ValueError, OSError, KeyError) as error:
        write_json(args.output / "preflight-error.json", {"status": "error", "reason": str(error)})
        print("C07 failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
