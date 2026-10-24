"""Build and run independent consumers from immutable public C05 candidates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))
from candidate import (CandidateError, canonical_json, file_digest, read_json,
                       semantic_digest, verify_candidate)
from check_cases import errors as case_errors
from check_repository import PRIVATE_CRATES, dependency_errors, snapshot_errors


GROUPS = {
    "c-to-rust": ["data", "lifecycle", "observe", "bootstrap", "abi-mismatch", "profile-mismatch", "missing-bootstrap"],
    "c-to-rust-test": ["operation-close", "source-lease", "registration-failure",
                       "panic", "diagnostics", "token-exhaustion", "capacity"],
    "rust-to-c": ["data", "bootstrap", "abi-mismatch", "profile-mismatch"],
}
TIMEOUT = 30
ENGINE_EXPORTS = {"madb_fixture_bootstrap", "madb_fixture_create", "madb_fixture_checksum",
                  "madb_fixture_observe", "madb_fixture_request_close", "madb_fixture_await_closed",
                  "madb_fixture_release_handle"}
TEST_EXPORTS = {"madb_fixture_test_arm", "madb_fixture_test_wait", "madb_fixture_test_resume",
                "madb_fixture_test_snapshot", "madb_fixture_test_emit", "madb_fixture_test_set_fault",
                "madb_fixture_test_set_next_token"}


class ExecutionError(RuntimeError):
    def __init__(self, message, stage, log, timeout=False):
        super().__init__(message)
        self.stage, self.log, self.timeout = stage, log, timeout


def run(command, *, cwd, env, log: Path, timeout=TIMEOUT, expected_exit=0, stage="run"):
    """A process group watchdog reports error; killing it never proves SDK cleanup."""
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"command": [str(x) for x in command], "exit_code": process.returncode,
                               "timeout": timed_out, "stdout": stdout.decode("utf-8", errors="replace"),
                               "stderr": stderr.decode("utf-8", errors="replace")}, indent=2) + "\n")
    if timed_out:
        raise ExecutionError("process watchdog expired; SDK cleanup is unproved", stage, log, True)
    if process.returncode != expected_exit:
        raise ExecutionError(f"{stage}: unexpected exit {process.returncode}; expected {expected_exit}", stage, log)
    return stdout.decode("utf-8"), int((time.monotonic() - started) * 1000)


def isolated_environment(temporary: Path):
    home = temporary / "home"; home.mkdir()
    # Installed compilers/SDKs are tools. Cargo registry, project target and HOME caches are not reused.
    environment = {"HOME": str(home), "CARGO_HOME": str(temporary / "cargo-home"),
                   "CARGO_TARGET_DIR": str(temporary / "target"), "CARGO_NET_OFFLINE": "true",
                   "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(Path.home() / ".rustup")),
                   "RUSTUP_TOOLCHAIN": "1.99.1", "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   "LC_ALL": "C", "LANG": "C", "TMPDIR": str(temporary),
                   "MACOSX_DEPLOYMENT_TARGET": "14.0"}
    for name in ("DEVELOPER_DIR", "SDKROOT"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def attachment(path: Path, report_root: Path):
    data = path.read_bytes()
    return {"path": path.relative_to(report_root).as_posix(), "size": len(data), "sha256": file_digest(data)}


def instantiated_case(group, name, candidate):
    case = read_json(ROOT / "cases" / group / (name + ".json"))
    case["kind"] = "instance"; case["selector"] = candidate["manifest"]["selector"]
    projection = dict(case)
    for key in ("problem_ids", "source_ids"):
        projection[key] = sorted(projection[key])
    projection["requires"] = dict(projection["requires"])
    projection["requires"]["features"] = sorted(projection["requires"]["features"])
    projection["requires"]["environment"] = sorted(projection["requires"]["environment"], key=lambda item: item["id"])
    return case, semantic_digest("madb.case/1", projection)


def result_record(case, digest, *, status="passed", duration=0, log=None, output="", error=None,
                  observed_rejection=None, report_root):
    resources = []
    if status == "passed":
        lines = [json.loads(line) for line in output.splitlines() if line]
        if not lines or lines[-1] != {"result": "passed"}:
            raise ValueError("consumer did not emit its completion record")
        for line in lines:
            if "resources" in line:
                observed = line["resources"]
                if any(observed[name] != 0 for name in ("active_operations", "source_leases", "registry_entries")):
                    raise ValueError("consumer reported retained resources after cleanup")
                for name in ("engines", "subscriptions", "callbacks"):
                    created, released = observed[name + "_created"], observed[name + "_released"]
                    if type(created) is not int or created < 0 or created != released:
                        raise ValueError("consumer reported an unbalanced resource lifetime")
                    resources.append({"name": name, "before": 0, "after": created - released,
                                      "created": created, "released": released})
        observation = {"kind": "success"} if observed_rejection is None else dict(kind="rejection", **observed_rejection)
        if observation != case["expected_result"]:
            raise ValueError("independently observed result does not match case expectation")
        actual = ({"kind": "rejection", "code": observed_rejection["code"], "stage": observed_rejection["stage"], "exit_code": None,
                   "reason": "independently observed rejection code and stage matched"}
                  if observed_rejection is not None else
                  {"kind": "success", "code": None, "stage": None, "exit_code": 0,
                   "reason": "independent consumer assertions passed"})
    else:
        actual = {"kind": "unavailable" if status in {"error", "blocked"} else "rejection",
                  "code": None if status in {"error", "blocked"} else "AssertionFailed",
                  "stage": None if status in {"error", "blocked"} else "run", "exit_code": None,
                  "reason": str(error)}
    return {"case_id": case["id"], "case_digest": digest, "status": status,
            "expected": case["expected_result"], "actual": actual,
            "evidence_level": "static" if status in {"error", "blocked"} or (observed_rejection and observed_rejection["stage"] == "identity") else "compiled" if observed_rejection is not None else "target-run",
            "duration_ms": duration, "resource_observations": resources,
            "diagnostics": [] if error is None else [{"code": "LAB.Execution", "message": str(error), "location": None}],
            "cleanup": "failed" if getattr(error, "timeout", False) else "not-run" if status == "blocked" else "complete",
            "attachments": [] if log is None or not log.exists() else [attachment(log, report_root)],
            "blocked_by": []}


def compile_c(install, temporary, group, clang, env, report_root, label="normal"):
    library = install / "lib" / ("libmadb_engine.dylib" if platform.system() == "Darwin" else "libmadb_engine.so")
    executable = temporary / "c-consumer"
    command = [clang, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pthread",
               "-I", str(install / "include"), str(ROOT / "consumers/c/main.c"),
               str(library), "-Wl,-rpath," + str(install / "lib"), "-o", str(executable)]
    if group.endswith("-test"):
        command.insert(1, "-DMADB_LAB_TEST_SUPPORT=1")
    if platform.system() != "Darwin":
        command.append("-ldl")
    try:
        run(command, cwd=temporary, env=env, log=report_root / group / ("compile-" + label + ".json"), timeout=120, stage="compile")
    except ExecutionError as error:
        error.stage = "compile"; raise
    return executable


def verify_exports(group, install, temporary, env, report_root, contract):
    is_macos = platform.system() == "Darwin"
    library = (install / "lib/libmadb_c.a" if group == "rust-to-c" else
               install / "lib" / ("libmadb_engine.dylib" if is_macos else "libmadb_engine.so"))
    nm = shutil.which("nm")
    if nm is None:
        raise RuntimeError("native symbol inspector nm is required")
    arguments = [nm, "-gU"] if is_macos else [nm, "-g", "--defined-only"]
    output, _ = run(arguments + [str(library)], cwd=temporary, env=env,
                    log=report_root / group / "public-symbols.json", stage="link")
    symbols = {line.split()[-1].removeprefix("_") for line in output.splitlines() if line.split()}
    actual = {symbol for symbol in symbols if symbol.startswith("madb_")}
    expected = ({"madb_c_fixture_bootstrap", "madb_c_fixture_checksum"} if group == "rust-to-c" else
                ENGINE_EXPORTS | TEST_EXPORTS if group.endswith("-test") else ENGINE_EXPORTS)
    contract_exports = {symbol["shape"]["link_name"] for symbol in contract["symbols"]}
    expected_contract = expected - TEST_EXPORTS
    if contract_exports != expected_contract:
        raise CandidateError("AbiMismatch", "public contract link names differ from the supported ABI")
    if actual != expected:
        raise CandidateError("ArtifactMismatch", f"{group}: public native export set differs: {sorted(actual)}")


def compile_rust(install, temporary, cargo, env, report_root, name="build"):
    project = temporary / "consumer"
    project.mkdir(exist_ok=True)
    (project / "src").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "consumers/rust/src/main.rs", project / "src/main.rs")
    (project / "Cargo.toml").write_text(
        '[package]\nname = "madb-lab-rust-consumer"\nversion = "0.1.0"\nedition = "2024"\n'
        '[dependencies]\nmadb-c-client = { path = "../install/rust/madb-c-client" }\n')
    try:
        run([cargo, "generate-lockfile", "--offline", "--manifest-path", str(project / "Cargo.toml")],
            cwd=temporary, env=env, log=report_root / "rust-to-c" / (name + "-lock.json"), timeout=120, stage="compile")
        metadata, _ = run([cargo, "metadata", "--offline", "--locked", "--format-version", "1", "--manifest-path", str(project / "Cargo.toml")],
                          cwd=temporary, env=env, log=report_root / "rust-to-c" / (name + "-dependencies.json"), timeout=120, stage="compile")
        for package in json.loads(metadata)["packages"]:
            if package["name"] in PRIVATE_CRATES or not Path(package["manifest_path"]).resolve().is_relative_to(temporary.resolve()):
                raise CandidateError("ArtifactMismatch", "Rust consumer resolved a private or external package dependency")
        run([cargo, "build", "--offline", "--locked", "--manifest-path", str(project / "Cargo.toml")],
            cwd=temporary, env=env, log=report_root / "rust-to-c" / (name + ".json"), timeout=120, stage="compile")
    except ExecutionError as error:
        error.stage = "compile"; raise
    return temporary / "target/debug/madb-lab-rust-consumer"


def replace_c_library(install, temporary, clang, env, report_root, mismatch):
    """A distinct Lab-owned wrong library; abort if connect reaches a business call."""
    identity = read_json(install / "identity.json")
    value = bytearray.fromhex(identity["interface_digest"][7:] + identity["profile_digest"][7:])
    value[0 if mismatch == "abi-mismatch" else 32] ^= 1
    source = temporary / "wrong-provider.c"
    source.write_text('#include "madb_c.h"\n#include <stdlib.h>\n#include <string.h>\n'
        'int32_t madb_c_fixture_bootstrap(uint32_t version, uint8_t *out, uint64_t capacity) {\n'
        f'  static const uint8_t value[64] = {{{",".join(str(x) for x in value)}}};\n'
        '  if (!out || capacity != 64 || version != 1) return 1; memcpy(out, value, 64); return 0;\n}\n'
        'int32_t madb_c_fixture_checksum(const uint8_t *data, uint64_t length, uint64_t *sum, MadbError *error) {\n'
        '  (void)data; (void)length; (void)sum; (void)error; abort();\n}\n')
    obj = temporary / "wrong-provider.o"
    run([clang, "-std=c11", "-I", str(install / "include"), "-c", str(source), "-o", str(obj)],
        cwd=temporary, env=env, log=report_root / "rust-to-c" / (mismatch + "-compile.json"), stage="compile")
    library = install / "lib/libmadb_c.a"; library.unlink()
    run([shutil.which("ar") or "/usr/bin/ar", "rcs", str(library), str(obj)], cwd=temporary, env=env,
        log=report_root / "rust-to-c" / (mismatch + "-archive.json"), stage="link")


def replace_rust_library(install, temporary, clang, env, report_root, mismatch):
    """Different native library with matching declarations and deliberately wrong identity."""
    identity = read_json(install / "identity.json")
    value = bytearray.fromhex(identity["interface_digest"][7:] + identity["profile_digest"][7:])
    if mismatch != "missing-bootstrap":
        value[0 if mismatch == "abi-mismatch" else 32] ^= 1
    source = temporary / "wrong-rust-provider.c"
    bootstrap = '' if mismatch == "missing-bootstrap" else (
        'int32_t madb_fixture_bootstrap(uint32_t version, uint8_t *out, uint64_t capacity) {\n'
        f' static const uint8_t value[64] = {{{",".join(str(x) for x in value)}}};\n'
        ' if (!out || capacity != 64 || version != 1) return 1; memcpy(out, value, 64); return 0;\n}\n')
    source.write_text('#include "madb_rust.h"\n#include <stdlib.h>\n#include <string.h>\n' + bootstrap +
        'MadbStatus madb_fixture_create(MadbHandle *out, MadbError *error) { (void)out; (void)error; abort(); }\n'
        'MadbStatus madb_fixture_checksum(MadbHandle h, const uint8_t *d, uint64_t n, uint64_t *o, MadbError *e) { (void)h;(void)d;(void)n;(void)o;(void)e;abort(); }\n'
        'MadbStatus madb_fixture_request_close(MadbHandle h, MadbError *e) { (void)h;(void)e;abort(); }\n'
        'MadbStatus madb_fixture_await_closed(MadbHandle h, uint32_t t, MadbError *e) { (void)h;(void)t;(void)e;abort(); }\n'
        'MadbStatus madb_fixture_release_handle(MadbHandle h, MadbError *e) { (void)h;(void)e;abort(); }\n'
        'MadbStatus madb_fixture_observe(MadbHandle h, MadbStateCallback c, void *x, MadbHandle *s, MadbError *e) { (void)h;(void)c;(void)x;(void)s;(void)e;abort(); }\n')
    is_macos = platform.system() == "Darwin"
    library = install / "lib" / ("libmadb_engine.dylib" if is_macos else "libmadb_engine.so")
    command = [clang, "-std=c11", "-I", str(install / "include"), "-dynamiclib" if is_macos else "-shared", "-fPIC",
               str(source), "-o", str(library)]
    if is_macos:
        command.extend(["-Wl,-install_name,@rpath/libmadb_engine.dylib"])
    run(command, cwd=temporary, env=env, log=report_root / "c-to-rust" / (mismatch + "-provider.json"), stage="compile")


def report_for(candidate, lab_revision, results, environment):
    manifest, provenance = candidate["manifest"], candidate["provenance"]
    catalog = b"".join(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes()
                       for path in sorted((ROOT / "cases").rglob("*.json")))
    report = {"schema": "madb.report/1", "run_id": "c05." + manifest["selector"]["profile_id"],
            "identity": {"input_digest": provenance["input_digest"], "tool_digest": provenance["tool_digest"],
                         "profile_digest": manifest["selector"]["profile_digest"],
                         "candidate_digest": manifest["candidate_digest"], "lab_revision": lab_revision,
                         "case_catalog_digest": file_digest(catalog)},
            "selector": manifest["selector"], "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "environment": environment, "results": results}
    if candidate.get("provisional"):
        report["run_id"] = "provisional." + report["run_id"]
        report["extensions"] = {"madb.lab-source-state": "provisional", "madb.lab-source-digest": candidate["lab_source_digest"]}
    return report


def missing_bootstrap_rejection(error, log):
    return (not error.timeout and log.get("timeout") is False
            and type(log.get("exit_code")) is int and log["exit_code"] > 0
            and error.stage in {"compile", "link"}
            and "madb_fixture_bootstrap" in log.get("stderr", "")
            and any(marker in log["stderr"] for marker in ("Undefined symbols", "undefined reference")))


def lab_source_identity(root, requested_revision, allow_dirty):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if requested_revision is not None and requested_revision != revision:
        raise ValueError("requested Lab revision differs from the actual checkout HEAD")
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root))
    if dirty and not allow_dirty:
        raise ValueError("formal C05 evidence requires a clean Lab commit; use --allow-dirty only for provisional development runs")
    paths = subprocess.check_output(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"], cwd=root).decode().split("\0")
    files = []
    for relative in sorted(set(paths) - {""}):
        path = root / relative
        if path.is_file():
            files.append({"path": relative, "sha256": file_digest(path.read_bytes())})
    return revision, dirty, file_digest(canonical_json(files))


def run_group(group, candidate, args, environment):
    records = []
    cases = [(name, *instantiated_case(group, name, candidate)) for name in GROUPS[group]]
    case_paths = {}
    for name, case, _ in cases:
        path = args.output / "cases" / group / (name + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(case, indent=2) + "\n")
        case_paths[name] = path
    expected_cases = {case["id"] for _, case, _ in cases}
    undeclared = set(candidate["manifest"]["required_cases"]) - expected_cases
    if undeclared:
        raise CandidateError("CoverageMissing", f"unimplemented required cases: {sorted(undeclared)}")
    with tempfile.TemporaryDirectory(prefix="madb-lab-c05-") as directory:
        temporary = Path(directory).resolve(); env = isolated_environment(temporary)
        install = temporary / "install"; shutil.copytree(candidate["root"], install)
        verify_candidate(install)
        verify_exports(group, install, temporary, env, args.output, candidate["contract"])
        try:
            executable = (compile_rust(install, temporary, args.cargo, env, args.output) if group == "rust-to-c"
                          else compile_c(install, temporary, group, args.clang, env, args.output))
        except ExecutionError as error:
            for index, (name, case, digest) in enumerate(cases):
                record = result_record(case, digest, status="error" if index == 0 else "blocked",
                                       error=error, log=error.log, report_root=args.output)
                if index:
                    record["blocked_by"] = [cases[0][1]["id"]]
                record["attachments"].append(attachment(case_paths[name], args.output))
                records.append(record)
            return report_for(candidate, args.lab_revision, records, environment)
        for name, case, digest in cases:
            log = args.output / group / (name + ".json")
            try:
                if name not in {"abi-mismatch", "profile-mismatch", "missing-bootstrap"}:
                    verify_candidate(install)
                if name in {"abi-mismatch", "profile-mismatch", "missing-bootstrap"}:
                    if group == "rust-to-c":
                        replace_c_library(install, temporary, args.clang, env, args.output, name)
                        # No stale Cargo fingerprint may keep the previously linked library.
                        shutil.rmtree(temporary / "target")
                        executable = compile_rust(install, temporary, args.cargo, env, args.output, name)
                    else:
                        replace_rust_library(install, temporary, args.clang, env, args.output, name)
                        if name == "missing-bootstrap":
                            try:
                                compile_c(install, temporary, group, args.clang, env, args.output, name)
                            except ExecutionError as link_error:
                                link_log = read_json(link_error.log)
                                if not missing_bootstrap_rejection(link_error, link_log):
                                    raise
                                log.write_text(json.dumps(link_log, indent=2) + "\n")
                                record = result_record(case, digest, output='{"result":"passed"}',
                                                       observed_rejection={"code": "MissingBootstrap", "stage": "link"},
                                                       log=log, report_root=args.output)
                                record["attachments"].append(attachment(case_paths[name], args.output))
                                records.append(record)
                                continue
                            raise ValueError("library without bootstrap unexpectedly linked")
                        executable = compile_c(install, temporary, group, args.clang, env, args.output, name)
                command = [str(executable), name]
                if group != "rust-to-c":
                    identity = candidate["identity"]
                    command.append(identity["interface_digest"][7:] + identity["profile_digest"][7:])
                    command.append(str(install / "lib" / ("libmadb_engine.dylib" if platform.system() == "Darwin" else "libmadb_engine.so")))
                output, duration = run(command, cwd=temporary, env=env, log=log)
                if name not in {"abi-mismatch", "profile-mismatch", "missing-bootstrap"}:
                    verify_candidate(install)
                record = result_record(case, digest, duration=duration, log=log, output=output, report_root=args.output)
            except (ExecutionError, ValueError, OSError) as error:
                status = "error" if isinstance(error, OSError) or getattr(error, "timeout", False) or getattr(error, "stage", "run") != "run" else "failed"
                record = result_record(case, digest, status=status, error=error, log=log, report_root=args.output)
            record["attachments"].append(attachment(case_paths[name], args.output))
            records.append(record)
        # Original published bytes must remain immutable despite deliberately altered installed copies.
        verify_candidate(candidate["root"])
    return report_for(candidate, args.lab_revision, records, environment)


def integrity_case(candidate, output, lab_revision, environment):
    """Corrupt an actual candidate copy; reject it before executing any downloaded code."""
    with tempfile.TemporaryDirectory(prefix="madb-lab-integrity-") as directory:
        install = Path(directory) / "candidate"; shutil.copytree(candidate["root"], install)
        path = install / candidate["manifest"]["files"][0]["path"]
        path.write_bytes(path.read_bytes() + b"tampered")
        try:
            verify_candidate(install)
        except CandidateError as error:
            if error.code != "ArtifactMismatch":
                raise
            observed = {"code": error.code, "stage": "identity"}
        else:
            raise AssertionError("corrupted candidate was accepted")
    log = output / "integrity.json"
    log.write_text(json.dumps({"case_id": "c05.packaging.integrity", "observed": observed,
                              "candidate_digest": candidate["manifest"]["candidate_digest"]}, indent=2) + "\n")
    case, digest = instantiated_case("packaging", "integrity", candidate)
    case_path = output / "cases/packaging/integrity.json"
    case_path.parent.mkdir(parents=True, exist_ok=True)
    case_path.write_text(json.dumps(case, indent=2) + "\n")
    record = result_record(case, digest, output='{"result":"passed"}', observed_rejection=observed,
                           log=log, report_root=output)
    record["attachments"].append(attachment(case_path, output))
    report = report_for(candidate, lab_revision, [record], environment)
    report["run_id"] += ".packaging"
    (output / "packaging.report.json").write_text(json.dumps(report, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lab-revision")
    parser.add_argument("--allow-dirty", action="store_true", help="provisional development run; never current fixed-revision acceptance")
    parser.add_argument("--producer-revision", help="expected full public producer commit, supplied by CI")
    parser.add_argument("--clang", default=shutil.which("clang"))
    parser.add_argument("--cargo", default=shutil.which("cargo"))
    args = parser.parse_args(argv)
    args.output = args.output.resolve()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be a new or empty directory so evidence from different runs cannot mix")
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        if platform.python_version() != (ROOT / ".python-version").read_text().strip():
            raise RuntimeError("use the Lab's pinned Python version")
        definitions = case_errors(ROOT) + dependency_errors(ROOT) + snapshot_errors(ROOT)
        if definitions:
            raise ValueError("; ".join(definitions))
        if not args.clang or not args.cargo:
            raise RuntimeError("Clang and Cargo are required; no consumer checks were run")
        tool_environment = dict(os.environ, RUSTUP_TOOLCHAIN="1.99.1")
        if Path(args.cargo).resolve().name == "rustup":
            args.cargo = subprocess.check_output([str(Path(args.cargo).resolve()), "which", "--toolchain", "1.99.1", "cargo"],
                                                text=True, env=tool_environment).strip()
        cargo_version = subprocess.check_output([args.cargo, "--version"], text=True, env=tool_environment)
        if not cargo_version.startswith("cargo 1.99.1 "):
            raise RuntimeError("C05 consumer requires the pinned Rust 1.99.1 toolchain")
        args.lab_revision, provisional, source_digest = lab_source_identity(ROOT, args.lab_revision, args.allow_dirty)
        if len(args.lab_revision) != 40 or any(c not in "0123456789abcdef" for c in args.lab_revision):
            raise ValueError("Lab revision must be a full Git commit")
        candidates = {group: verify_candidate(args.candidates / group) for group in GROUPS}
        if any(candidate["provenance"].get("provisional", False) for candidate in candidates.values()):
            if not args.allow_dirty:
                raise CandidateError("ArtifactMismatch", "provisional producer candidates cannot supply formal acceptance evidence")
            provisional = True
        for candidate in candidates.values():
            candidate["provisional"] = provisional
            candidate["lab_source_digest"] = source_digest
        if len({candidate["manifest"]["selector"]["profile_id"] for candidate in candidates.values()}) != len(candidates) or len({candidate["manifest"]["selector"]["profile_digest"] for candidate in candidates.values()}) != len(candidates):
            raise CandidateError("ProfileMismatch", "direct directions and test-support require distinct profiles")
        if args.producer_revision is not None and any(candidate["provenance"]["producer_revision"] != args.producer_revision for candidate in candidates.values()):
            raise CandidateError("ArtifactMismatch", "candidate producer revision differs from pinned workflow source")
        expected_target = "aarch64-apple-darwin" if platform.system() == "Darwin" and platform.machine() == "arm64" else "x86_64-unknown-linux-gnu" if platform.system() == "Linux" and platform.machine() == "x86_64" else None
        if any(value["manifest"]["selector"]["target"] != expected_target for value in candidates.values()):
            raise RuntimeError("candidate target does not match this real consumer host")
        environment = []
        for name, executable in (("clang", args.clang), ("cargo", args.cargo)):
            version = subprocess.check_output([executable, "--version"], text=True, env=tool_environment).splitlines()[0]
            environment.append({"id": name, "version": version[:128], "sha256": file_digest(Path(executable).read_bytes()),
                                "host": expected_target, "target": expected_target, "source": executable, "arguments": []})
        passed = True
        for group, candidate in candidates.items():
            report = run_group(group, candidate, args, environment)
            path = args.output / (group + ".report.json")
            path.write_text(json.dumps(report, indent=2) + "\n")
            group_passed = all(result["status"] == "passed" for result in report["results"])
            print(f"{'provisional ' if provisional else ''}{group}: {'passed' if group_passed else 'FAILED'} ({len(report['results'])} cases)", flush=True)
            passed = passed and group_passed
        integrity_case(candidates["c-to-rust"], args.output, args.lab_revision, environment)
        return 0 if passed else 1
    except (CandidateError, RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        (args.output / "preflight-error.json").write_text(json.dumps({"status": "error", "reason": str(error)}) + "\n")
        print(f"C05 failed: {error}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
