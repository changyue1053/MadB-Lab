"""Independently install, compile and run the four declared C06 public SDK routes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from candidate import CandidateError, file_digest, read_json
from c06_candidate import verify_candidate
from c06_contract import ROUTES, TARGET, case_names
from c06_execution import ExecutionError, attachment, install_candidate, isolated_environment, lab_source_identity, require_host, run
from c06_observations import observations
from c06_build import _library, compile_consumer
from c06_toolchain import verify_installation, verify_apple
from check_cases import errors as case_errors
from check_repository import dependency_errors, snapshot_errors
from runners.first_route import instantiated_case


def expectation(group, name, candidate):
    path = (ROOT / "consumers/swift/c06-skie/expected.json" if group == "swift-kotlin"
            else ROOT / "consumers/kotlin-common/c06/expected.json")
    expected = dict(read_json(path)[name])
    if group != "swift-kotlin" and name in {"identity", "distribution"}:
        expected["identity.profile"] = candidate["manifest"]["selector"]["profile_digest"]
    return expected


def result_record(case, digest, *, output, log, report_root, duration=0, error=None, rejection=None):
    if error is not None:
        status = "error" if isinstance(error, (OSError, ExecutionError, RuntimeError)) else "failed"
        actual = {"kind": "unavailable" if status == "error" else "rejection", "code": None if status == "error" else "AssertionFailed",
                  "stage": None if status == "error" else "run", "exit_code": None, "reason": str(error)}
    else:
        status = "passed"
        actual = ({"kind": "success", "code": None, "stage": None, "exit_code": 0,
                   "reason": "independent consumer observations matched all required expectations"}
                  if rejection is None else {"kind": "rejection", "code": rejection["code"], "stage": rejection["stage"],
                                            "exit_code": None, "reason": "precise declared rejection observed before business admission"})
        if (dict(kind="success") if rejection is None else dict(kind="rejection", **rejection)) != case["expected_result"]:
            raise ValueError("observed outcome does not match the independent case definition")
    return {"case_id": case["id"], "case_digest": digest, "status": status, "expected": case["expected_result"],
            "actual": actual, "evidence_level": "static" if error else "compiled" if rejection and rejection["stage"] in {"compile", "link"} else "target-run",
            "duration_ms": duration, "resource_observations": [],
            "diagnostics": [] if error is None else [{"code": "LAB.C06", "message": str(error), "location": None}],
            "cleanup": ("complete" if error is None else "not-run" if getattr(error, "stage", None) in {"compile", "link"} else "failed"), "attachments": [] if log is None or not log.exists() else [attachment(log, report_root)], "blocked_by": []}


def report_for(candidate, revision, results, environment, started):
    manifest, provenance = candidate["manifest"], candidate["provenance"]
    catalog = b"".join(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes()
                       for path in sorted((ROOT / "cases").rglob("*.json")))
    report = {"schema": "madb.report/1", "run_id": "c06." + manifest["selector"]["profile_id"],
              "identity": {"input_digest": provenance["input_digest"], "tool_digest": provenance["tool_digest"],
                           "profile_digest": manifest["selector"]["profile_digest"], "candidate_digest": manifest["candidate_digest"],
                           "lab_revision": revision, "case_catalog_digest": file_digest(catalog)},
              "selector": manifest["selector"], "started_at": started, "environment": environment, "results": results}
    if candidate.get("provisional"):
        report["run_id"] = "provisional." + report["run_id"]
        report["extensions"] = {"madb.lab-source-state": "provisional", "madb.lab-source-digest": candidate["lab_source_digest"]}
    return report


def run_group(group, candidate, all_candidates, args, environment):
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    results = []
    with tempfile.TemporaryDirectory(prefix="madb-lab-c06-") as folder:
        temporary = Path(folder)
        local_environment = isolated_environment(temporary)
        install = install_candidate(candidate, temporary)
        logs = args.output / group
        try:
            command = compile_consumer(group, install, temporary, args, local_environment, logs)
            compile_error = None
        except (ExecutionError, OSError, ValueError, RuntimeError) as error:
            command, compile_error = None, error
        for name in case_names(group):
            case, digest = instantiated_case("c06/" + group, name, candidate)
            case_path = args.output / "cases/c06" / group / (name + ".json")
            case_path.parent.mkdir(parents=True, exist_ok=True)
            case_path.write_text(json.dumps(case, indent=2) + "\n")
            log = logs / (name + ".json")
            output, duration, error, rejection = "", 0, compile_error, None
            if error is None:
                try:
                    if name in {"wrong-profile", "wrong-abi", "foreign-future-once", "callback-throw", "cancel-late-result", "missing-cinterop-origin", "generic-lambda"}:
                        from c06_negatives import execute_special
                        output, duration, rejection = execute_special(group, name, candidate, all_candidates, install,
                            temporary, command, args, local_environment, log)
                    else:
                        arguments = [name, candidate["manifest"]["selector"]["profile_digest"]]
                        if name == "distribution" and group != "swift-kotlin": arguments.append(str(_library(install)))
                        output, duration = run(command + arguments,
                                               cwd=temporary, env=local_environment, log=log, timeout=35)
                    if rejection is None or rejection["stage"] == "load":
                        observations(output, expected=expectation(group, name, candidate))
                    # Negative copies may change deliberately; the normal public
                    # installation must retain exactly the admitted bytes.
                    verify_candidate(install, group)
                except (ExecutionError, OSError, ValueError, RuntimeError, ImportError) as failure:
                    error = failure
            record = result_record(case, digest, output=output, log=getattr(error, "log", log),
                                   report_root=args.output, duration=duration, error=error, rejection=rejection)
            if compile_error is not None:
                record["cleanup"] = "not-run"
            record["attachments"].append(attachment(case_path, args.output))
            compilation = (logs / (name + "-compile") / "compile.json" if name in {"wrong-profile", "wrong-abi"}
                           else logs / "p03-compile.json" if name in {"foreign-future-once", "callback-throw", "cancel-late-result"}
                           else logs / "compile.json")
            if compilation.is_file() and compilation != getattr(error, "log", log):
                record["attachments"].append(attachment(compilation, args.output))
            results.append(record)
        verify_candidate(candidate["root"], group)
    return report_for(candidate, args.lab_revision, results, environment, started)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--managed-root", required=True, type=Path)
    parser.add_argument("--kotlin-home", type=Path)
    parser.add_argument("--konan-home", type=Path)
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--lab-revision")
    parser.add_argument("--producer-revision")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--group", choices=tuple(ROUTES), action="append", help="explicit focused development run; does not certify the C06 package")
    args = parser.parse_args(argv)
    args.output = args.output.resolve(); args.managed_root = args.managed_root.resolve()
    if args.output.exists() and any(args.output.iterdir()): parser.error("--output must be empty so different runs cannot mix evidence")
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        require_host()
        if platform.python_version() != (ROOT / ".python-version").read_text().strip(): raise RuntimeError("use the Lab's pinned Python version")
        findings = case_errors(ROOT) + dependency_errors(ROOT) + snapshot_errors(ROOT)
        if findings: raise ValueError("; ".join(findings))
        args.lab_revision, provisional, source_digest = lab_source_identity(ROOT, args.lab_revision, args.allow_dirty)
        args.kotlin_home = args.kotlin_home or args.managed_root / "kotlin-jvm"
        args.konan_home = args.konan_home or args.managed_root / "kotlin-native"
        args.java_home = args.java_home or args.managed_root / "jdk/Contents/Home"
        for supplied, relative in ((args.kotlin_home, "kotlin-jvm"), (args.konan_home, "kotlin-native"), (args.java_home, "jdk/Contents/Home")):
            if supplied.resolve() != (args.managed_root / relative).resolve(): raise ValueError("explicit compiler homes must belong to the candidate-bound managed installation")
        candidates = {group: verify_candidate(args.candidates / group, group) for group in ROUTES}
        if any(value["provenance"].get("provisional", False) for value in candidates.values()):
            if not args.allow_dirty: raise CandidateError("ArtifactMismatch", "provisional candidates cannot produce formal acceptance")
            provisional = True
        if args.producer_revision and any(value["provenance"]["producer_revision"] != args.producer_revision for value in candidates.values()):
            raise CandidateError("ArtifactMismatch", "candidate producer differs from fixed workflow revision")
        if len({value["manifest"]["selector"]["profile_digest"] for value in candidates.values()}) != 4:
            raise CandidateError("ProfileMismatch", "all four routes require distinct exact profile identities")
        for value in candidates.values():
            value.update(provisional=provisional, lab_source_digest=source_digest)
        requirements = [value["toolchain"]["managed_installation"] for value in candidates.values()]
        if len({value["receipt_sha256"] for value in requirements}) != 1:
            raise CandidateError("ArtifactMismatch", "C06 profiles do not share the declared managed compiler installation")
        requirement = dict(requirements[0]); requirement["components"] = sorted(set.union(*(set(item["components"]) for item in requirements)))
        verify_installation(args.managed_root, requirement)
        apple_proofs = [{name: value["toolchain"][name] for name in ("tools", "trees", "xcode")} for value in candidates.values()]
        if any(proof != apple_proofs[0] for proof in apple_proofs[1:]):
            raise CandidateError("ProfileMismatch", "C06 routes disagree on the shared compiler and dependency closure")
        environment = verify_apple(candidates["swift-rust"]["toolchain"])
        passed = True
        for group in args.group or ROUTES:
            report = run_group(group, candidates[group], candidates, args, environment)
            (args.output / (group + ".report.json")).write_text(json.dumps(report, indent=2) + "\n")
            success = all(result["status"] == "passed" for result in report["results"])
            print(f"{group}: {'passed' if success else 'FAILED'} ({len(report['results'])} cases)", flush=True)
            passed = passed and success
        verify_installation(args.managed_root, requirement)
        verify_apple(candidates["swift-rust"]["toolchain"])
        if lab_source_identity(ROOT, args.lab_revision, args.allow_dirty)[2] != source_digest:
            raise CandidateError("ArtifactMismatch", "Lab sources changed while acceptance was running")
        return 0 if passed else 1
    except (CandidateError, RuntimeError, ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        (args.output / "preflight-error.json").write_text(json.dumps({"status": "error", "reason": str(error)}) + "\n")
        print(f"C06 failed: {error}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
