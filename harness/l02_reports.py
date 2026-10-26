"""Existing case/report v1 records for the five independent L02 cases.

Definitions are frozen before compilation or target invocation. This module
records evidence; the C consumer and the separate output oracle do the checks.
It neither certifies old C05 cases nor turns helper stubs into native evidence.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from candidate import file_digest, logical_path, parse_json, read_json, semantic_digest
from check_cases import errors as case_errors


CASE_NAMES = {
    "c-to-rust-diagnostics": ("checked-constructor", "diagnostics", "disabled-protection"),
    "c-to-rust-diagnostics-test": ("diagnostics-isolation", "diagnostics-capacity"),
}


def file_reference(path, root):
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("report attachment escapes output or is a symlink")
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": file_digest(data), "size": len(data)}


def case_digest(case):
    projection = deepcopy(case)
    for key in ("problem_ids", "source_ids"):
        projection[key].sort()
    projection["requires"]["features"].sort()
    projection["requires"]["environment"].sort(key=lambda item: item["id"])
    return semantic_digest("madb.case/1", projection)


def catalog_digest(root):
    return file_digest(b"".join(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes()
                               for path in sorted((root / "cases").rglob("*.json"))))


def probe_key(row):
    mode = row["case"]
    return (mode, row.get("capture"), row.get("stub"), row.get("library_group"))


def required_probes(name):
    """Fixed Lab obligations, independent of a candidate's self-declared list."""
    ordinary = lambda mode: (mode, None, None, None)
    captures = lambda mode: [(mode, capture, None, None) for capture in range(3)]
    if name == "checked-constructor":
        return [ordinary("ordinary"), *[("helper-stub", None, n, None) for n in range(6)],
                ("actual-mismatch", None, None, "c-to-rust-diagnostics-test"),
                ("actual-mismatch", None, None, "c-to-rust-test")]
    if name == "diagnostics":
        return [ordinary(mode) for mode in ("events", "toggle", "rejections", "concurrent", "exporter",
                                            "instance", "instance", "timing-off", "timing-on", "timing-full")]
    if name == "disabled-protection":
        return [ordinary("off"), *captures("self-wait")]
    if name == "diagnostics-isolation":
        return [key for mode in ("operation-close", "source-lease", "self-wait", "fault-isolation") for key in captures(mode)]
    if name == "diagnostics-capacity":
        return [ordinary("full"), ordinary("exhaustion")]
    raise ValueError("unknown L02 case")


def template_probes(case):
    keys = []
    instances = []
    for step in case["steps"]:
        arguments = {}
        for argument in step["arguments"]:
            if argument.get("kind") != "string":
                raise ValueError("L02 step arguments must use the fixed string descriptors")
            key, separator, value = argument["value"].partition("=")
            if not separator or key in arguments or key not in {"mode", "stub", "header", "provider", "expected-kind", "capture", "instance"}:
                raise ValueError("invalid or duplicate L02 step descriptor")
            arguments[key] = value
        mode = step["entrypoint"]
        if step["action"] != "call" or arguments.get("mode", mode) != mode:
            raise ValueError("L02 case step is not its declared target entrypoint")
        if mode == "actual-mismatch":
            provider = arguments.get("provider")
            expected = {"c-to-rust-diagnostics-test": "3", "c-to-rust-test": "2"}.get(provider)
            if arguments.get("header") != "c-to-rust-diagnostics" or arguments.get("expected-kind") != expected or expected is None:
                raise ValueError("L02 mismatch step has the wrong header/provider expectation")
        if mode == "instance":
            instances.append(arguments.get("instance"))
        expected_arguments = ({"header", "provider", "expected-kind"} if mode == "actual-mismatch" else
                              {"stub"} if mode == "helper-stub" else {"instance"} if mode == "instance" else
                              {"capture"} if "capture" in arguments else {"mode"})
        if set(arguments) != expected_arguments:
            raise ValueError("L02 step contains unused or missing arguments")
        keys.append((mode, int(arguments["capture"]) if "capture" in arguments else None,
                     int(arguments["stub"]) if "stub" in arguments else None, arguments.get("provider")))
    if instances and instances != ["1", "2"]:
        raise ValueError("L02 instance steps must declare two distinct process invocations")
    return keys


class CommandFailure(RuntimeError):
    def __init__(self, path, value):
        super().__init__("command failed; process exit/kill does not prove SDK cleanup: " + str(path))
        self.path, self.value = path, value


class ObservationFailure(ValueError):
    """An observed, complete value contradicted an independent postcondition."""


class Reports:
    def __init__(self, root, output, candidates, lab_revision, environment):
        findings = case_errors(root)
        if findings:
            raise ValueError("; ".join(findings))
        self.root, self.output = root, output
        self.candidates = deepcopy({group: {key: candidates[group][key] for key in ("manifest", "provenance")} for group in CASE_NAMES})
        self.lab_revision, self.environment = lab_revision, deepcopy(environment)
        self.started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.catalog = catalog_digest(root)
        self.cases, self.references, self.records = {}, {}, {}
        self.active = None
        self.active_started = False
        self.active_log = None
        self.active_duration_ns = 0
        for group, names in CASE_NAMES.items():
            expected_ids = {"l02." + group + "." + name for name in names}
            declared = {item for item in candidates[group]["manifest"]["required_cases"] if item.startswith("l02.")}
            if declared != expected_ids:
                raise ValueError("candidate required L02 set differs from independent cases")
            for name in names:
                case = read_json(root / "cases/l02" / group / (name + ".json"))
                if case["id"] != "l02." + group + "." + name or case["expected_result"] != {"kind": "success"}:
                    raise ValueError("unexpected L02 case identity or result")
                if template_probes(case) != required_probes(name):
                    raise ValueError("case steps differ from the fixed L02 responsibilities")
                if case["timeout_policy"] != {"timeout_ms": len(case["steps"]) * 60000, "on_timeout": "error", "recovery": "isolate"}:
                    raise ValueError("L02 case budget differs from its bounded target steps")
                case["kind"] = "instance"
                case["selector"] = deepcopy(candidates[group]["manifest"]["selector"])
                case["requires"]["environment"] = [{"id": item["id"], "version": item["version"]} for item in environment]
                path = output / "cases/l02" / group / (name + ".json")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n")
                self.cases[(group, name)] = case
                self.references[(group, name)] = file_reference(path, output)
                self.records[(group, name)] = []
        index = {"started_at": self.started_at, "lab_revision": lab_revision, "case_catalog_digest": self.catalog,
                 "cases": [{"id": case["id"], "case_digest": case_digest(case), "instance": self.references[key],
                            "candidate_digest": self.candidates[key[0]]["manifest"]["candidate_digest"]}
                           for key, case in self.cases.items()]}
        index_path = output / "case-inputs.json"
        index_path.write_text(json.dumps(index, indent=2) + "\n")
        self.index_reference = file_reference(index_path, output)

    def owner(self, row):
        group = row.get("group", row.get("header_group"))
        for name in CASE_NAMES.get(group, ()):
            if row["case"] in {key[0] for key in required_probes(name)}:
                return group, name
        return None

    def begin(self, row):
        self.active = deepcopy(row)
        self.active_started = False
        self.active_log = None
        self.active_duration_ns = 0
        owner = self.owner(row)
        if owner is None:
            return 60
        elapsed = sum(item["duration_ns"] for item in self.records[owner])
        expected = required_probes(owner[1])
        if len(self.records[owner]) >= len(expected) or probe_key(row) != expected[len(self.records[owner])]:
            raise ValueError("target step differs from the next frozen case step")
        remaining = self.cases[owner]["timeout_policy"]["timeout_ms"] / 1000 - elapsed / 1_000_000_000
        if remaining <= 0:
            raise RuntimeError("case target budget exhausted; SDK cleanup is unproved")
        return min(60, remaining)

    def started(self, log=None):
        if self.active is None:
            raise ValueError("target was not declared before execution")
        self.active_started = True
        if log is not None:
            self.active_log = file_reference(self.output / str(logical_path(log)), self.output)
            duration = read_json(self.output / log).get("duration_ns")
            if type(duration) is not int or duration < 0:
                raise ValueError("actual target duration is missing")
            self.active_duration_ns = duration

    def complete(self, row, log):
        if self.active != row or not self.active_started:
            raise ValueError("target completion has no matching started probe")
        owner = self.owner(row)
        reference = file_reference(self.output / str(logical_path(log)), self.output)
        if self.active_log is not None and reference != self.active_log:
            raise ValueError("raw target evidence changed during the independent oracle check")
        value = read_json(self.output / log)
        if (value.get("timeout") is not False or type(value.get("exit_code")) is not int or value["exit_code"] != 0
                or type(value.get("duration_ns")) is not int or value["duration_ns"] < 0):
            raise ValueError("completed target lacks a successful, timed raw command")
        output = [parse_json(line.encode()) for line in value.get("stdout", "").splitlines() if line]
        if not output or not isinstance(output[-1], dict) or output[-1].get("result") != "passed":
            raise ValueError("completed target lacks raw terminal evidence")
        if owner:
            self.records[owner].append({"probe": deepcopy(row), "log": reference, "duration_ns": value["duration_ns"]})
        self.active = None
        self.active_started = False
        self.active_log = None
        self.active_duration_ns = 0

    def verify(self):
        if catalog_digest(self.root) != self.catalog or case_errors(self.root):
            raise ValueError("case catalog or fixture changed after execution began")
        if file_reference(self.output / self.index_reference["path"], self.output) != self.index_reference:
            raise ValueError("pre-execution case input index changed")
        for key, case in self.cases.items():
            ref = self.references[key]
            path = self.output / ref["path"]
            if file_reference(path, self.output) != ref or read_json(path) != case:
                raise ValueError("frozen case instance changed during execution")
            rows = self.records[key]
            if [probe_key(row["probe"]) for row in rows] != required_probes(key[1]):
                raise ValueError("missing or duplicated exact target steps for " + case["id"])
            if sum(row["duration_ns"] for row in rows) > case["timeout_policy"]["timeout_ms"] * 1_000_000:
                raise RuntimeError("case target budget exceeded")
            for row in rows:
                if file_reference(self.output / row["log"]["path"], self.output) != row["log"]:
                    raise ValueError("target log changed after its oracle check")

    def write(self, local, error=None):
        """Write two selector reports, only after the run's final integrity gate.

        On a shared prerequisite failure no completed probe can acquire a pass.
        The active owning case carries the failure; all other case qualifications
        are blocked by that case's failed shared run/closure prerequisite.
        """
        if error is None:
            self.verify()
            if local["result"] != "passed":
                raise ValueError("local failure cannot become a standard passed report")
        failed_owner = self.owner(self.active) if self.active else None
        failed_owner = failed_owner or next(iter(self.cases))
        failure_id = self.cases[failed_owner]["id"]
        assertion_failed = isinstance(error, ObservationFailure)
        if isinstance(error, CommandFailure) and self.active_started:
            value = error.value
            assertion_failed = (value.get("timeout") is False and value.get("exit_code") == 2
                                and re.search(r"(?m)^L02 assertion:[0-9]+:.+$", value.get("stderr", "")) is not None)
        attachments = [file_reference(self.output / "report.json", self.output)]
        if (self.output / self.index_reference["path"]).is_file():
            attachments.append(file_reference(self.output / self.index_reference["path"], self.output))
        for item in local["logs"]:
            path = self.output / str(logical_path(item["path"]))
            if path.is_file() and not path.is_symlink():
                attachments.append(file_reference(path, self.output))
        if (self.output / "consumer-sources.tar").is_file():
            attachments.append(file_reference(self.output / "consumer-sources.tar", self.output))
        # Public installed candidate metadata and all concrete executable/depfile
        # identities remain in the attached local record; the bytes remain in run output.
        result_paths = []
        for group, names in CASE_NAMES.items():
            candidate = self.candidates[group]
            manifest, provenance = candidate["manifest"], candidate["provenance"]
            results = []
            for name in names:
                key = group, name; case = self.cases[key]; rows = self.records[key]
                status = "passed" if error is None else ("failed" if assertion_failed else "error") if key == failed_owner else "blocked"
                active_here = bool(self.active_started and self.active and self.owner(self.active) == key)
                complete = [probe_key(row["probe"]) for row in rows] == required_probes(name) and not active_here
                failed_duration = (self.active_duration_ns or (error.value.get("duration_ns", 0) if isinstance(error, CommandFailure) else 0)) if active_here else 0
                reason = ("all exact target steps and final source/tool/candidate closure passed; stub steps remain helper-only"
                          if error is None else str(error)[:3500] + ("" if key == failed_owner else "; blocked by failed shared run prerequisite " + failure_id))
                actual = {"kind": "success" if status == "passed" else "rejection" if status == "failed" else "unavailable" if rows or active_here or status == "error" else "not-run",
                          "code": "AssertionFailed" if status == "failed" else None, "stage": "run" if status == "failed" else None,
                          "exit_code": 0 if status == "passed" else None, "reason": reason}
                results.append({"case_id": case["id"], "case_digest": case_digest(case), "status": status,
                                "expected": case["expected_result"], "actual": actual,
                                "evidence_level": "target-run" if rows or active_here else "compiled" if local["compile"] == "passed" else "static",
                                "duration_ms": (sum(row["duration_ns"] for row in rows) + failed_duration) // 1_000_000,
                                "resource_observations": [],
                                "diagnostics": [{"code": "LAB.ResourceEvidence", "message": "Actual C close/release assertions are in raw logs; no numeric resource snapshots were emitted.", "location": None}]
                                               + ([] if error is None else [{"code": "LAB.Execution", "message": reason, "location": None}]),
                                "cleanup": "complete" if complete and error is None else "failed" if rows or active_here else "not-run",
                                "attachments": ([file_reference(self.output / self.references[key]["path"], self.output)]
                                                if (self.output / self.references[key]["path"]).is_file() else []) + attachments,
                                "blocked_by": [failure_id] if status == "blocked" else []})
            report = {"schema": "madb.report/1", "run_id": "l02." + manifest["selector"]["profile_id"],
                      "identity": {"input_digest": provenance["input_digest"], "tool_digest": provenance["tool_digest"],
                                   "profile_digest": manifest["selector"]["profile_digest"], "candidate_digest": manifest["candidate_digest"],
                                   "lab_revision": self.lab_revision, "case_catalog_digest": self.catalog},
                      "selector": manifest["selector"], "started_at": self.started_at, "environment": self.environment,
                      "results": results}
            path = self.output / (group + ".report.json")
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            result_paths.append(file_reference(path, self.output))
        return result_paths
