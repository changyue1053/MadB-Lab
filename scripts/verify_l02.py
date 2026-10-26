"""Independent, explicit L02 C consumer of four clean public candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
from candidate import CandidateError, canonical_json, file_digest, logical_path, parse_json, read_json, verify_candidate
from l02_reports import CommandFailure, ObservationFailure, Reports, CASE_NAMES

GROUPS = ("c-to-rust", "c-to-rust-test", "c-to-rust-diagnostics", "c-to-rust-diagnostics-test")
ENGINE = {"madb_fixture_" + name for name in ("bootstrap", "create", "checksum", "observe", "request_close", "await_closed", "release_handle")}
TEST = {"madb_fixture_test_" + name for name in ("arm", "wait", "resume", "snapshot", "emit", "set_fault", "set_next_token")}
DIAGNOSTICS = {"madb_fixture_diagnostics_configure", "madb_fixture_diagnostics_drain"}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
SOURCE = ROOT / "consumers/c/l02_diagnostics.c"
L02_CASES = {
    "c-to-rust-diagnostics": {
        "checked-constructor": ["ordinary", "helper-stub", "actual-mismatch"],
        "diagnostics": ["events", "toggle", "rejections", "concurrent", "exporter", "instance", "timing-off", "timing-on", "timing-full"],
        "disabled-protection": ["off", "self-wait"],
    },
    "c-to-rust-diagnostics-test": {
        "diagnostics-isolation": ["operation-close", "source-lease", "self-wait", "fault-isolation"],
        "diagnostics-capacity": ["full", "exhaustion"],
    },
}


def reference(path):
    data = path.read_bytes()
    return {"sha256": file_digest(data), "size": len(data)}


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("input symlink is not accepted")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = reference(path)
    return result


def lab_identity(root, expected):
    if not REVISION.fullmatch(expected):
        raise ValueError("expected Lab revision must be a full commit")
    revision = subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", root, "status", "--porcelain", "--untracked-files=all"])
    if revision != expected or dirty:
        raise ValueError("L02 requires the exact clean Lab revision; no provisional acceptance")
    paths = subprocess.check_output(["git", "-C", root, "ls-files", "-z"]).decode().split("\0")
    return {name: reference(root / name) for name in sorted(set(paths) - {""})}


def parse_pins(values):
    result = {}
    for entry in values:
        name, separator, digest = entry.partition("=")
        if not separator or name not in GROUPS or name in result or not DIGEST.fullmatch(digest):
            raise ValueError("candidate-digest needs one exact group=sha256:... per profile")
        result[name] = digest
    if set(result) != set(GROUPS):
        raise ValueError("all four independently pinned candidates are required")
    return result


def check_selection(group, candidate, digest, producer, target):
    manifest, provenance = candidate["manifest"], candidate["provenance"]
    selector = manifest["selector"]
    if provenance.get("provisional", False) or provenance["producer_revision"] != producer:
        raise CandidateError("ArtifactMismatch", "candidate is provisional or has the wrong producer revision")
    if manifest["candidate_digest"] != digest:
        raise CandidateError("ArtifactMismatch", "candidate differs from independent expected digest")
    if (selector["profile_id"] != "c05-" + group + "-" + target or selector["target"] != target
            or selector["route"] != "RUST-C-ABI" or selector["direction"] != "consumer-to-provider"):
        raise CandidateError("ProfileMismatch", "candidate is not this fixed L02 profile and host")
    listed = {item["path"] for item in manifest["files"]}
    if not {"include/madb_rust_client.h", "include/madb_rust.h"} <= listed:
        raise CandidateError("ArtifactMismatch", "candidate lacks generated public checked header")
    if ("include/test-support.h" in listed) != group.endswith("-test"):
        raise CandidateError("ArtifactMismatch", "test-support header disagrees with profile")
    expected_l02 = {"l02." + group + "." + name for name in L02_CASES.get(group, {})}
    declared_l02 = {name for name in manifest["required_cases"] if name.startswith("l02.")}
    if declared_l02 != expected_l02:
        raise CandidateError("CoverageMissing", "candidate L02 required cases differ from the fixed supported set")


def expected_exports(group):
    return ENGINE | (TEST if group.endswith("-test") else set()) | (DIAGNOSTICS if "diagnostics" in group else set())


def case_results(observations):
    """Each L02 result refers to observations of that candidate's own headers."""
    results = []
    for group, cases in L02_CASES.items():
        for name, modes in cases.items():
            indexes = [index for index, row in enumerate(observations)
                       if row.get("group", row.get("header_group")) == group and row["case"] in modes]
            if {observations[index]["case"] for index in indexes} != set(modes):
                raise CandidateError("CoverageMissing", "L02 case lacks its own candidate observations: " + name)
            if "actual-mismatch" in modes:
                providers = [observations[index]["library_group"] for index in indexes if observations[index]["case"] == "actual-mismatch"]
                if sorted(providers) != ["c-to-rust-diagnostics-test", "c-to-rust-test"]:
                    raise CandidateError("CoverageMissing", "checked constructor lacks both actual wrong-library pairings")
            results.append({"id": "l02." + group + "." + name, "result": "passed", "scenarios": modes, "observation_indexes": indexes})
    return results


def inspect_exports(output, group, contract):
    symbols = {line.split()[-1].removeprefix("_") for line in output.splitlines() if line.split()}
    actual = {name for name in symbols if name.startswith("madb_")}
    expected = expected_exports(group)
    if actual != expected:
        raise CandidateError("ArtifactMismatch", "exact native export set differs")
    if {symbol["shape"]["link_name"] for symbol in contract["symbols"]} != expected - TEST:
        raise CandidateError("AbiMismatch", "contract and selected native declarations differ")
    return sorted(actual)


def sdk_binding(receipt, sdk, resources):
    """Bind C-consumer SDK bytes; preserve producer-only Rust link receipts."""
    result = {}; native = {}; seen = set()
    for entry in receipt["sdk_inputs"]:
        name = str(logical_path(entry["name"]))
        prefix, relative = name.split("/", 1)
        if name in seen:
            raise ValueError("unknown/duplicate public SDK input identity")
        seen.add(name)
        if prefix == "native":
            # Already bound in the public candidate. These Rust producer archive
            # inputs are not read by a C consumer, and no developer cache is used.
            if not DIGEST.fullmatch(entry["sha256"]) or type(entry["size"]) is not int or entry["size"] < 0:
                raise ValueError("invalid producer native input receipt")
            native[name] = {key: entry[key] for key in ("sha256", "size")}
            continue
        root = {"sdk": sdk, "clang-resource": resources}.get(prefix)
        if root is None:
            raise ValueError("unknown public SDK input identity")
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root.resolve()):
            raise ValueError("SDK receipt path escapes its installation")
        actual = reference(path)
        if actual != {key: entry[key] for key in ("sha256", "size")}:
            raise CandidateError("ArtifactMismatch", "installed SDK bytes differ: " + name)
        result[name] = {"path": str(path), **actual}
    if not result:
        raise ValueError("public SDK receipt is empty")
    return {"consumer_sdk_bytes": result, "producer_only_native_receipts": native}


def native_target(system, machine, libc):
    if (system, machine) == ("Darwin", "arm64"):
        return "aarch64-apple-darwin"
    if (system, machine, libc) == ("Linux", "x86_64", "glibc"):
        return "x86_64-unknown-linux-gnu"
    raise ValueError("unsupported actual native consumer host")


def compiler_configuration(target, sdk, resources):
    common = {"language_standard": "c11", "warnings": ["-Wall", "-Wextra", "-Werror"]}
    if target == "aarch64-apple-darwin":
        return (["-isysroot", str(sdk), "-resource-dir", str(resources), "-target", "arm64-apple-macosx14.0"],
                {**common, "target": "arm64-apple-macosx14.0", "deployment_target": "14.0"})
    if target == "x86_64-unknown-linux-gnu":
        return (["-target", target, "-resource-dir", str(resources)], {**common, "target": target})
    raise ValueError("unsupported fixed compiler target")


def dependency_inputs(depfile, target, sources, roots):
    observed_target, separator, values = depfile.read_text().replace("\\\n", " ").partition(":")
    if observed_target != target or not separator:
        raise ValueError("unexpected compiler dependency output")
    required = {path.resolve(strict=True) for path in sources}
    allowed = [path.resolve(strict=True) for path in roots]
    inputs = {}
    for name in shlex.split(values.replace("$$", "$")):
        path = Path(name).resolve(strict=True)
        if path not in required and not any(path.is_relative_to(root) for root in allowed):
            raise ValueError("compiler read outside its public/system inputs: " + str(path))
        inputs[str(path)] = reference(path)
    if not required <= {Path(path) for path in inputs}:
        raise ValueError("compiler dependency output omits required source/header")
    return inputs


def public_header_probe(commands, clang, include, directory):
    """Observe only public headers' closure, separately from consumer POSIX headers."""
    source = directory / "public-headers.c"
    source.write_text('#include "madb_rust.h"\n#include "madb_rust_client.h"\n')
    source_ref = reference(source)
    depfile = directory / "public-headers.d"
    commands.run([clang, *commands.c_flags, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", include,
                  "-M", "-MT", "madb-l02-public", "-MF", depfile, source], timeout=120)
    inputs = dependency_inputs(depfile, "madb-l02-public", [source, include / "madb_rust.h", include / "madb_rust_client.h"],
                               [include, *commands.system_roots])
    if inputs[str(source.resolve())] != source_ref:
        raise ValueError("public header probe source changed during preprocessing")
    dependencies = {path: ref for path, ref in inputs.items()
                    if Path(path) != source.resolve() and not Path(path).is_relative_to(include.resolve())}
    return {"source": {"path": source.relative_to(commands.output).as_posix(), **source_ref},
            "depfile": {"path": depfile.relative_to(commands.output).as_posix(), **reference(depfile)},
            "inputs": inputs, "system_dependencies": dependencies}


def linux_sdk_binding(receipt, resources, system_headers, dependencies):
    """Resolve the public receipt's basename/hash names against actual -M inputs.

    Only .rlib entries are producer-only here. Native .h entries must each have
    exactly one matching actual system-header path; no backend/private mapping
    or directory scan is used to invent those paths.
    """
    resources, system_headers = resources.resolve(strict=True), system_headers.resolve(strict=True)
    if any(root == Path(root.anchor) for root in (resources, system_headers)):
        raise ValueError("unbounded Linux system/resource root")
    actual = {}
    for name, expected in dependencies.items():
        path = Path(name).resolve(strict=True)
        if not (path.is_relative_to(resources) or path.is_relative_to(system_headers)):
            raise ValueError("public header dependency escapes fixed Linux roots")
        ref = reference(path)
        if ref != expected:
            raise CandidateError("ArtifactMismatch", "public header dependency bytes changed: " + str(path))
        actual[str(path)] = ref
    result, native, seen, consumed = {}, {}, set(), set()
    for entry in receipt["sdk_inputs"]:
        name = str(logical_path(entry["name"]))
        if (set(entry) != {"name", "sha256", "size"} or name in seen or not DIGEST.fullmatch(entry["sha256"])
                or type(entry["size"]) is not int or entry["size"] < 0):
            raise ValueError("invalid/duplicate Linux SDK receipt")
        seen.add(name)
        expected = {key: entry[key] for key in ("sha256", "size")}
        prefix, separator, relative = name.partition("/")
        if not separator:
            raise ValueError("unqualified Linux SDK receipt")
        if prefix == "clang-resource":
            path = (resources / relative).resolve(strict=True)
            if not path.is_relative_to(resources) or actual.get(str(path)) != expected:
                raise CandidateError("ArtifactMismatch", "resource header absent from actual public closure or differs: " + name)
        elif prefix == "native":
            basename, separator, suffix = relative.rpartition("-")
            if not separator or "/" in relative or suffix != entry["sha256"][7:]:
                raise ValueError("native SDK receipt name does not match its byte digest")
            if basename.startswith("lib") and basename.endswith(".rlib"):
                native[name] = expected
                continue
            if not basename.endswith(".h"):
                raise ValueError("unknown producer-only native receipt; only Rust archives are exempt")
            matches = [Path(path) for path, ref in actual.items() if Path(path).is_relative_to(system_headers)
                       and not Path(path).is_relative_to(resources) and Path(path).name == basename and ref == expected]
            if len(matches) != 1:
                raise CandidateError("ArtifactMismatch", "missing or ambiguous actual system-header receipt: " + name)
            path = matches[0]
        else:
            raise ValueError("unknown Linux SDK input category")
        if str(path) in consumed:
            raise ValueError("multiple SDK receipt names alias one actual header")
        consumed.add(str(path)); result[name] = {"path": str(path), **expected}
    if not result or consumed != set(actual):
        raise CandidateError("ArtifactMismatch", "actual public-header closure differs from the exact SDK header receipt")
    return {"consumer_sdk_bytes": result, "producer_only_native_receipts": native}


def only(rows, key):
    found = [row for row in rows if key in row]
    if len(found) != 1:
        raise ValueError("missing or duplicate observation: " + key)
    return found[0]


def check_output_structure(rows):
    """Missing/ill-typed evidence is an error, before any value postcondition.

    Match whole fixed C output shapes, not just their marker: a record missing
    record_id must not silently disappear from the event collection. Exact
    types also distinguish JSON booleans from integer counters.
    """
    shapes = (
        {"loaded_module": str, "pid": int},
        {"actual_identity": str},
        {"result": str},
        {"ordinary": bool, "engine": int, "subscription": int, "callbacks": int, "sum": int, "close": str},
        {"scope": str, "mode": int, "kind": int, "bootstrap_calls": int, "create_calls": int, "result": str},
        {"events": int, "completed_calls": int, "failed_calls": int, "completed_callbacks": int, "dropped_events": int, "capture_enabled": int},
        {"record_id": int, "symbol_id": int, "phase": int, "resource_id": int, "related_resource_id": int,
         "duration_ns": int, "status": int, "status_present": int},
        {"concurrent_work": int, "engine": int, "controller_events": int, "busy_observed": int},
        {"exporter": str, "ordinary_completed_before_exporter_release": bool},
        {"self_wait": str, "observe": str, "close": str},
        {"held": str, "await": str, "release": str},
        {"resource_balance": bool, "context_released_after_drain": bool},
        {"test_fault": int, "ordinary_semantics_unchanged": bool},
        {"checked_kind": int, "native_failure": str},
        {"checked_kind": int, "created_delta": int, "native_status": int},
        {"sample": int, "iterations": int, "batches": int, "duration_ns": int},
    )
    for row in rows:
        shape = next((shape for shape in shapes if set(shape) == set(row)), None)
        if shape is None or any(type(row[key]) is not expected for key, expected in shape.items()):
            raise ValueError("consumer observation has missing/unknown fields or invalid field types")


def inspect_output(output, mode, library, identity, *, stub=None, mismatch=None):
    rows = [parse_json(line.encode()) for line in output.splitlines() if line]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("consumer output is not JSON object lines")
    check_output_structure(rows)
    if stub is not None:
        expected = {"scope": "stub-only", "mode": stub, "kind": 2 if stub == 5 else stub,
                    "bootstrap_calls": 1, "create_calls": int(stub in (0, 4)), "result": "passed"}
        if len(rows) != 1 or set(rows[0]) != set(expected):
            raise ValueError("helper stub result is incomplete or duplicated")
        if rows != [expected]:
            raise ObservationFailure("helper stub did not prove the exact limited branch")
        return expected
    terminal = only(rows, "result")
    if set(terminal) != {"result"} or rows[-1] is not terminal:
        raise ValueError("missing unique terminal success")
    if terminal["result"] != "passed":
        raise ObservationFailure("complete terminal result is not successful")
    loaded = only(rows, "loaded_module")
    if loaded["loaded_module"] != str(library.resolve()) or type(loaded.get("pid")) is not int or loaded["pid"] <= 0:
        raise ObservationFailure("actual loaded module or process identity differs")
    expected_identity = identity["interface_digest"][7:] + identity["profile_digest"][7:]
    if only(rows, "actual_identity") != {"actual_identity": expected_identity}:
        raise ObservationFailure("actual native bootstrap differs from the loaded candidate")
    events = [row for row in rows if "record_id" in row]
    for event in events:
        if set(event) != {"record_id", "symbol_id", "phase", "resource_id", "related_resource_id", "duration_ns", "status", "status_present"}:
            raise ValueError("event observation has unknown/missing fields")
        if event["duration_ns"] < 0:
            raise ObservationFailure("event duration is negative")
    if mode in {"ordinary", "off", "events", "instance", "exporter", "fault-isolation"}:
        ordinary = only(rows, "ordinary")
        if ordinary.get("ordinary") is not True or ordinary.get("sum") != 511 or ordinary.get("callbacks") != 1 or ordinary.get("close") != "confirmed":
            raise ObservationFailure("ordinary data/callback/normal close was not proved")
        if type(ordinary.get("engine")) is not int or type(ordinary.get("subscription")) is not int or not 0 < ordinary["engine"] < ordinary["subscription"]:
            raise ObservationFailure("ordinary resource identities are invalid")
    if mode in {"off", "events", "instance", "full", "toggle", "rejections", "concurrent"}:
        stats = only(rows, "events")
        if any(v < 0 for v in stats.values()):
            raise ObservationFailure("diagnostic counters are negative")
        controller_events = only(rows, "concurrent_work")["controller_events"] if mode == "concurrent" else 0
        if not 0 <= controller_events <= 1000:
            raise ObservationFailure("concurrent controller drain count is outside its bounded work")
        recorded = stats["events"] + controller_events
        if len(events) != recorded:
            raise ValueError("raw diagnostic events do not match the complete drain count")
        if mode in {"off", "events", "instance"}:
            enabled = mode != "off"
            if stats != {"events": 11 if enabled else 0, "completed_calls": 10, "failed_calls": 1,
                         "completed_callbacks": 1, "dropped_events": 0, "capture_enabled": int(enabled)}:
                raise ObservationFailure("ordinary and diagnostic control counters differ")
            if len(events) != (11 if enabled else 0):
                raise ObservationFailure("wrong event cardinality")
            if enabled:
                pair = only(rows, "ordinary"); engine, subscription = pair["engine"], pair["subscription"]
                symbols = [1, 2, 3, 3, 8, 7, 4, 5, 5, 6, 6]
                resources = [0, engine, engine, 0, subscription, engine, engine, engine, subscription, subscription, engine]
                for n, event in enumerate(events):
                    expected = {"record_id": n + 1, "symbol_id": symbols[n], "phase": 2 if n == 4 else 1,
                                "resource_id": resources[n], "related_resource_id": engine if n == 4 else subscription if n == 5 else 0,
                                "status": 2 if n == 3 else 0, "status_present": 0 if n == 4 else 1}
                    # INVALID_HANDLE is checked against the real public constant by C;
                    # the established C ABI fixes its numeric value to 2.
                    if {key: value for key, value in event.items() if key != "duration_ns"} != expected:
                        raise ObservationFailure("event responsibility, identity, phase or status differs")
        elif mode == "full":
            if stats != {"events": 64, "completed_calls": 88, "failed_calls": 0, "completed_callbacks": 1, "dropped_events": 23, "capture_enabled": 1}:
                raise ObservationFailure("full ring affected resource work or failed exact drop-new accounting")
            if len(events) != 64 or [r["record_id"] for r in events] != list(range(1, 65)):
                raise ObservationFailure("ring FIFO/capacity differs")
            if any((r["symbol_id"], r["phase"], r["status"], r["status_present"], r["related_resource_id"]) != (3, 1, 0, 1, 0) for r in events) or len({r["resource_id"] for r in events}) != 1:
                raise ObservationFailure("ring replaced retained checksum events")
        elif mode == "toggle":
            if [r["record_id"] for r in events] != [1, 2] or stats != {"events": 2, "completed_calls": 3, "failed_calls": 0, "completed_callbacks": 0, "dropped_events": 0, "capture_enabled": 0}:
                raise ObservationFailure("toggle reset IDs/counters or lost retained events")
        elif mode == "rejections":
            expected_event = {"record_id": 1, "symbol_id": 1, "phase": 1, "resource_id": 0, "related_resource_id": 0, "status": 0, "status_present": 1}
            if (len(events) != 1 or {key: value for key, value in events[0].items() if key != "duration_ns"} != expected_event
                    or stats != {"events": 1, "completed_calls": 1, "failed_calls": 0, "completed_callbacks": 0, "dropped_events": 0, "capture_enabled": 1}):
                raise ObservationFailure("rejected diagnostics consumed queue or produced control events")
        else:
            work = only(rows, "concurrent_work")
            if (stats["completed_calls"] != 4005 or stats["failed_calls"] or stats["completed_callbacks"] or stats["capture_enabled"] != 0
                    or stats["events"] > 64 or work.get("concurrent_work") != 4000 or type(work.get("engine")) is not int or work["engine"] <= 0
                    or type(work.get("controller_events")) is not int or not 0 <= work["controller_events"] <= 1000
                    or type(work.get("busy_observed")) is not int or not 0 <= work["busy_observed"] <= 1000
                    or len(events) != work["controller_events"] + stats["events"]):
                raise ObservationFailure("concurrent work/control result differs")
            last_id = 0
            for event in events:
                if (event["record_id"] <= last_id or event["symbol_id"] != 3 or event["resource_id"] != work["engine"]
                        or (event["phase"], event["related_resource_id"], event["status"], event["status_present"]) != (1, 0, 0, 1)):
                    raise ObservationFailure("concurrent pulled event identity, phase or status differs")
                last_id = event["record_id"]
    if mode == "exporter" and only(rows, "exporter") != {"exporter": "consumer-blocked-dropped", "ordinary_completed_before_exporter_release": True}:
        raise ObservationFailure("exporter did not remain independent of SDK work")
    if mode == "self-wait" and only(rows, "self_wait") != {"self_wait": "WOULD_DEADLOCK", "observe": "CLOSING", "close": "confirmed"}:
        raise ObservationFailure("callback self-wait protection differs")
    if mode in {"operation-close", "source-lease", "exhaustion", "fault-isolation"}:
        if only(rows, "resource_balance") != {"resource_balance": True, "context_released_after_drain": True}:
            raise ObservationFailure("companion resource balance/confirmed lifetime missing")
        if mode in {"operation-close", "source-lease"} and only(rows, "held") != {"held": "operation" if mode == "operation-close" else "source-lease", "await": "TIMEOUT", "release": "BUSY"}:
            raise ObservationFailure("controlled close window did not run")
        if mode == "exhaustion" and only(rows, "checked_kind") != {"checked_kind": 4, "native_failure": "RESOURCE_EXHAUSTED"}:
            raise ObservationFailure("actual create failure was not retained")
        if mode == "fault-isolation" and only(rows, "test_fault") != {"test_fault": 3, "ordinary_semantics_unchanged": True}:
            raise ObservationFailure("existing companion diagnostic fault affected ordinary semantics")
    if mode == "mismatch" and only(rows, "checked_kind") != {"checked_kind": mismatch, "created_delta": 0, "native_status": 0}:
        raise ObservationFailure("actual mismatch created resources or changed bootstrap status")
    if mode.startswith("timing-"):
        samples = [row for row in rows if "sample" in row]
        if len(samples) != 5:
            raise ValueError("actual bounded timing samples are missing")
        if [r["sample"] for r in samples] != list(range(5)) or any(r["iterations"] != 800 or r["batches"] != 25 or r["duration_ns"] <= 0 for r in samples):
            raise ObservationFailure("complete timing samples violate the fixed bounded observation")
    return {"mode": mode, "pid": loaded["pid"], "rows": rows}


class Commands:
    def __init__(self, output):
        self.output = output
        self.logs = []
        self.c_flags = []
        self.system_roots = []
        self.compilations = []
        names = ("HOME", "USER", "LOGNAME", "PATH") + (("DEVELOPER_DIR", "SDKROOT") if platform.system() == "Darwin" else ())
        self.environment = {name: os.environ[name] for name in names if name in os.environ}
        self.environment.update(LC_ALL="C", LANG="C", TMPDIR=str(output / "tmp"))
        if platform.system() == "Darwin": self.environment["MACOSX_DEPLOYMENT_TARGET"] = "14.0"
        (output / "tmp").mkdir()

    def run(self, argv, timeout=60):
        path = self.output / "logs" / f"{len(self.logs) + 1:03d}.json"
        path.parent.mkdir(exist_ok=True)
        start = time.monotonic_ns()
        process = subprocess.Popen([str(x) for x in argv], cwd=self.output, env=self.environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True; os.killpg(process.pid, signal.SIGKILL); stdout, stderr = process.communicate()
        value = {"argv": [str(x) for x in argv], "exit_code": process.returncode, "timeout": timed_out,
                 "duration_ns": time.monotonic_ns() - start, "stdout": stdout.decode(errors="replace"), "stderr": stderr.decode(errors="replace")}
        path.write_text(json.dumps(value, indent=2) + "\n"); self.logs.append({"path": str(path.relative_to(self.output)), **reference(path)})
        if timed_out or process.returncode:
            raise CommandFailure(path, value)
        return stdout.decode(), str(path.relative_to(self.output))


def compile_consumer(commands, clang, include, library, executable, *, test=False, stub=False, mismatch=False, extra_include=None):
    argv = [clang, *commands.c_flags, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread", "-I", include]
    if test: argv.append("-DMADB_LAB_TEST_SUPPORT=1")
    if stub: argv.append("-DMADB_LAB_STUB=1")
    if mismatch: argv.append("-DMADB_LAB_MISMATCH_ONLY=1")
    if extra_include: argv.extend(["-I", extra_include])
    depfile = executable.with_suffix(".d")
    commands.run([*argv, "-M", "-MT", "madb-l02", "-MF", depfile, SOURCE], timeout=120)
    allowed = [include.resolve(), *commands.system_roots] + ([] if extra_include is None else [extra_include.resolve()])
    inputs = dependency_inputs(depfile, "madb-l02", [SOURCE], allowed)
    argv.append(SOURCE)
    if not stub:
        argv.extend([library, "-Wl,-rpath," + str(library.parent)])
        if platform.system() != "Darwin": argv.append("-ldl")
    argv.extend(["-o", executable]); commands.run(argv, timeout=120)
    if any(reference(Path(path)) != expected for path, expected in inputs.items()):
        raise ValueError("actual compile dependency changed during compilation")
    commands.compilations.append({"executable": str(executable.relative_to(commands.output)),
                                  "depfile": {"path": str(depfile.relative_to(commands.output)), **reference(depfile)}, "inputs": inputs})


def run_probe(commands, report, reports, argv, group, mode, library, identity, *, capture=None, stub=None, provider=None, mismatch=None):
    row = ({"header_group": group, "library_group": provider, "case": "actual-mismatch"} if provider else
           {"group": group, "case": "helper-stub", "stub": stub} if stub is not None else
           {"group": group, "case": mode, "capture": capture})
    timeout = reports.begin(row)
    try:
        output, log = commands.run(argv, timeout=timeout)
    except CommandFailure as error:
        reports.started(error.path.relative_to(reports.output).as_posix())
        raise
    reports.started(log)
    if read_json(reports.output / log)["stdout"] != output:
        raise ValueError("returned target output differs from its raw command evidence")
    observed = inspect_output(output, mode, library, identity, stub=stub, mismatch=mismatch)
    reports.complete(row, log)
    report["observations"].append({**row, "log": log, "observed": observed})
    return observed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--candidate-digest", action="append", required=True)
    parser.add_argument("--producer-revision", required=True)
    parser.add_argument("--lab-revision", required=True)
    parser.add_argument("--clang", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output, args.candidates = args.output.resolve(), args.candidates.resolve()
    if any(args.output.is_relative_to(p) or p.is_relative_to(args.output) for p in (ROOT, args.candidates)):
        parser.error("output overlaps source or candidate input")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"scope": "L02 approved native diagnostics and checked construction; four fixed public candidates",
              "result": "failed", "provisional": False, "full_l02_acceptance": False, "full_c05_revalidation": False,
              "preflight": "not_run", "compile": "not_run", "runtime": "not_run", "observations": [], "executables": {},
              "public_header_probes": {},
              "limits": ["private ring poisoning, record-ID exhaustion and counter wrap require separate producer evidence",
                         "no new language/platform certification or publication", "performance samples have no real-time bound",
                         "helper stubs prove only generated helper control flow; native results are separate"]}
    commands = Commands(args.output)
    standard_reports = None
    failure = None
    try:
        report["preflight"] = "started"
        if platform.python_version() != (ROOT / ".python-version").read_text().strip(): raise ValueError("use pinned Lab Python")
        if not REVISION.fullmatch(args.producer_revision): raise ValueError("full producer revision required")
        pins = parse_pins(args.candidate_digest)
        lab_files = lab_identity(ROOT, args.lab_revision)
        report["lab"] = {"revision": args.lab_revision, "files": lab_files, "source_digest": file_digest(canonical_json(lab_files))}
        target = native_target(platform.system(), platform.machine(), platform.libc_ver()[0])
        report["environment"] = {"host": target, "platform": platform.platform(), "python": platform.python_version()}
        if target == "aarch64-apple-darwin":
            clang = args.clang or Path(commands.run(["xcrun", "--find", "clang"])[0].strip())
            nm = Path(commands.run(["xcrun", "--find", "nm"])[0].strip()).resolve(strict=True)
            sdk = Path(commands.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"])[0].strip()).resolve(strict=True)
        else:
            clang = args.clang or Path("/usr/bin/clang")
            inspector = shutil.which("llvm-nm") or shutil.which("nm")
            if inspector is None: raise ValueError("Linux native symbol inspector is unavailable")
            nm = Path(inspector).resolve(strict=True)
            sdk = None
        clang = clang.resolve(strict=True); compiler_ref = reference(clang)
        resources = Path(commands.run([clang, "-print-resource-dir"])[0].strip()).resolve(strict=True)
        if target == "x86_64-unknown-linux-gnu" and (len(resources.parts) < 4 or not (resources / "include").is_dir()):
            raise ValueError("Linux compiler resource directory is not a bounded header installation")
        commands.c_flags, expected_compiler = compiler_configuration(target, sdk, resources)
        commands.system_roots = [sdk, resources] if sdk is not None else [Path("/usr/include").resolve(strict=True), resources]
        report["tools"] = {"clang": {"path": str(clang), **compiler_ref, "version": commands.run([clang, "--version"])[0]},
                           "nm": {"path": str(nm), **reference(nm)}}
        candidates = {}; originals = {}; installs = {}; sdk_receipts = {}; toolchains = {}
        for group in GROUPS:
            path = args.candidates / group
            value = verify_candidate(path); check_selection(group, value, pins[group], args.producer_revision, target)
            if target == "x86_64-unknown-linux-gnu" and value["profile"]["deployment_target"] != "native-host":
                raise CandidateError("ProfileMismatch", "Linux candidate deployment target differs from native-host")
            matching = [tool for tool in value["profile"]["tools"] if tool["id"] == "c05-clang"]
            if len(matching) != 1 or matching[0]["sha256"] != compiler_ref["sha256"]:
                raise CandidateError("ProfileMismatch", "actual Clang differs from candidate-fixed compiler")
            matching_nm = [tool for tool in value["profile"]["tools"] if tool["id"] == "c05-nm"]
            if len(matching_nm) != 1 or matching_nm[0]["sha256"] != reference(nm)["sha256"]:
                raise CandidateError("ProfileMismatch", "actual nm differs from candidate-fixed inspector")
            receipt = read_json(path / "toolchain.json")
            if receipt["compiler"] != expected_compiler:
                raise CandidateError("ProfileMismatch", "candidate compiler target/options differ from this fixed consumer")
            if sdk is not None:
                sdk_receipts[group] = sdk_binding(receipt, sdk, resources)
            toolchains[group] = receipt
            originals[group] = inventory(path); candidates[group] = value
            install = args.output / group / "install"; install.parent.mkdir(); shutil.copytree(path, install); verify_candidate(install); installs[group] = install
        if len({v["identity"]["profile_digest"] for v in candidates.values()}) != 4:
            raise CandidateError("ProfileMismatch", "four profiles must have distinct identities")
        report["candidates"] = {group: {"root": str(v["root"]), "manifest": v["manifest"], "identity": v["identity"], "provenance": v["provenance"]} for group, v in candidates.items()}
        report["sdk_inputs"] = sdk_receipts
        actual_environment = [{"id": "c05-clang", "version": report["tools"]["clang"]["version"].splitlines()[0],
                               "sha256": compiler_ref["sha256"], "host": target, "target": target,
                               "source": str(clang), "arguments": [*commands.c_flags, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread"]},
                              {"id": "lab-python", "version": platform.python_version(), "sha256": reference(Path(sys.executable).resolve())["sha256"],
                               "host": target, "target": target, "source": str(Path(sys.executable).resolve()), "arguments": ["-B"]}]
        if any(not item["version"] or len(item["version"]) > 128 for item in actual_environment):
            raise ValueError("actual environment version cannot fit the public report")
        standard_reports = Reports(ROOT, args.output, candidates, args.lab_revision, actual_environment)
        report["case_inputs"] = standard_reports.index_reference
        if sdk is None:
            # Definitions are already frozen; no target code is executed by -M.
            for group, install in installs.items():
                probe = public_header_probe(commands, clang, install / "include", install.parent)
                report["public_header_probes"][group] = probe
                sdk_receipts[group] = linux_sdk_binding(toolchains[group], resources, commands.system_roots[0], probe["system_dependencies"])
        report["preflight"] = "passed"
        report["compile"] = "started"
        suffix = "dylib" if platform.system() == "Darwin" else "so"
        libraries = {group: install / ("lib/libmadb_engine." + suffix) for group, install in installs.items()}
        executables = {}
        for group, install in installs.items():
            flags = ["-gU"] if platform.system() == "Darwin" else ["-g", "--defined-only"]
            output, log = commands.run([nm, *flags, libraries[group]])
            report["observations"].append({"group": group, "case": "exact-exports", "symbols": inspect_exports(output, group, candidates[group]["contract"]), "log": log})
            executable = install.parent / "consumer"
            compile_consumer(commands, clang, install / "include", libraries[group], executable, test=group.endswith("-test")); executables[group] = executable
            report["executables"][str(executable.relative_to(args.output))] = reference(executable)
        report["compile"] = "passed"; report["runtime"] = "started"
        for group, executable in executables.items():
            modes = [("ordinary", None)]
            if "diagnostics" in group:
                modes += [(mode, None) for mode in ("off", "events", "full", "toggle", "rejections", "concurrent", "exporter", "instance", "instance", "timing-off", "timing-on", "timing-full")]
            else:
                modes += [("timing-off", None)]
            captures = range(3) if "diagnostics" in group else (None,)
            if group.endswith("-test"):
                modes += [(mode, capture) for mode in ("operation-close", "source-lease") for capture in captures]
            modes += [("self-wait", capture) for capture in captures]
            if group.endswith("-test"):
                modes += [("fault-isolation", capture) for capture in captures]
                modes += [("exhaustion", None)]
            instances = []
            for mode, capture in modes:
                observed = run_probe(commands, report, standard_reports,
                                     [executable, mode, libraries[group]] + ([] if capture is None else [str(capture)]),
                                     group, mode, libraries[group], candidates[group]["identity"], capture=capture)
                if mode == "instance": instances.append(observed["pid"])
            if instances and (len(instances) != 2 or len(set(instances)) != 2): raise ValueError("independent image observations require distinct real processes")
            stub = installs[group].parent / "helper-stub"
            compile_consumer(commands, clang, installs[group] / "include", None, stub, stub=True)
            report["executables"][str(stub.relative_to(args.output))] = reference(stub)
            identity = candidates[group]["identity"]; native_hex = identity["interface_digest"][7:] + identity["profile_digest"][7:]
            for mode in range(6):
                run_probe(commands, report, standard_reports, [stub, str(mode), native_hex], group, "stub", None, None, stub=mode)
            verify_candidate(installs[group]); verify_candidate(candidates[group]["root"])
            if inventory(candidates[group]["root"]) != originals[group] or inventory(installs[group]) != originals[group]: raise ValueError("candidate changed during consumer execution")
        # Real wrong-library pairs: companion counters establish no create occurred.
        for header_group, provider, kind in (("c-to-rust", "c-to-rust-test", 3), ("c-to-rust", "c-to-rust-diagnostics-test", 2),
                                             ("c-to-rust-diagnostics", "c-to-rust-diagnostics-test", 3), ("c-to-rust-diagnostics", "c-to-rust-test", 2)):
            header = installs[header_group] / "include"; library = libraries[provider]
            actual = candidates[provider]["identity"]; expected = candidates[header_group]["identity"]
            if (actual["interface_digest"] == expected["interface_digest"]) != (kind == 3) or actual["profile_digest"] == expected["profile_digest"]:
                raise ValueError("real mismatch pairing lacks the required interface/profile difference")
            executable = args.output / ("wrong-" + header_group + "-to-" + provider)
            compile_consumer(commands, clang, header, library, executable, test=True, mismatch=True, extra_include=installs[provider] / "include")
            report["executables"][str(executable.relative_to(args.output))] = reference(executable)
            run_probe(commands, report, standard_reports, [executable, "mismatch", library, str(kind)],
                      header_group, "mismatch", library, actual, provider=provider, mismatch=kind)
        if lab_identity(ROOT, args.lab_revision) != lab_files or reference(clang) != compiler_ref:
            raise ValueError("Lab source or compiler changed during execution")
        if reference(nm) != {key: report["tools"]["nm"][key] for key in ("sha256", "size")}:
            raise ValueError("native symbol inspector changed during execution")
        if any(reference(Path(item["source"]))["sha256"] != item["sha256"] for item in actual_environment):
            raise ValueError("report environment tool image changed during execution")
        if any(reference(args.output / item["path"]) != {key: item[key] for key in ("sha256", "size")} for item in commands.logs):
            raise ValueError("raw command evidence changed during execution")
        if any(reference(args.output / name) != expected for name, expected in report["executables"].items()):
            raise ValueError("consumer executable changed during execution")
        for compilation in commands.compilations:
            if any(reference(Path(name)) != expected for name, expected in compilation["inputs"].items()):
                raise ValueError("compiler-observed public/system dependency changed during runtime")
        for probe in report["public_header_probes"].values():
            if any(reference(Path(name)) != expected for name, expected in probe["inputs"].items()):
                raise ValueError("public header probe dependency changed during runtime")
            for kind in ("source", "depfile"):
                ref = probe[kind]
                if reference(args.output / ref["path"]) != {key: ref[key] for key in ("sha256", "size")}:
                    raise ValueError("public header probe evidence changed during runtime")
        for group in GROUPS:
            verify_candidate(installs[group]); verify_candidate(candidates[group]["root"])
            if inventory(installs[group]) != originals[group] or inventory(candidates[group]["root"]) != originals[group]: raise ValueError("final candidate bytes changed")
            receipt = read_json(installs[group] / "toolchain.json")
            actual_sdk = (sdk_binding(receipt, sdk, resources) if sdk is not None else
                          linux_sdk_binding(receipt, resources, commands.system_roots[0], report["public_header_probes"][group]["system_dependencies"]))
            if actual_sdk != sdk_receipts[group]:
                raise ValueError("SDK input changed during execution")
        with tarfile.open(args.output / "consumer-sources.tar", "w") as archive:
            names = ["consumers/c/l02_diagnostics.c", "consumers/c/README-l02.md", "scripts/verify_l02.py", "scripts/test_l02.py", "harness/candidate.py", "harness/check_cases.py", "harness/l02_reports.py"]
            names += ["cases/l02/" + group + "/" + name + ".json" for group, cases in CASE_NAMES.items() for name in cases]
            for name in names:
                archive.add(ROOT / name, arcname=name)
        report["source_archive"] = reference(args.output / "consumer-sources.tar")
        report["l02_case_results"] = case_results(report["observations"])
        report["existing_required_cases_not_recertified_here"] = {group: [name for name in v["manifest"]["required_cases"] if not name.startswith("l02.")]
                                                                  for group, v in candidates.items()}
        standard_reports.verify()
        report["runtime"] = "passed"; report["result"] = "passed"
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        failure = error
        report["error"] = str(error)
        for stage in ("preflight", "compile", "runtime"):
            if report[stage] == "started": report[stage] = "failed"
    report["logs"] = commands.logs
    report["compilations"] = commands.compilations
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if standard_reports is not None:
        standard_reports.write(report, failure)
    print(json.dumps({"result": report["result"], "report": str(args.output / "report.json"), "error": report.get("error")}))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
