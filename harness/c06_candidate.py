"""Strict C06 public candidate admission, retaining C05's independent route gate."""
from __future__ import annotations

from pathlib import Path

from candidate import CandidateError, read_json, verify_public_candidate
from c06_contract import ROUTES, TARGET, required_cases


def verify_candidate(root: Path, group: str) -> dict:
    if group not in ROUTES:
        raise CandidateError("ProfileMismatch", "unknown C06 consumer group")
    route = ROUTES[group]
    candidate = verify_public_candidate(root, allowed_routes={route["route"]})
    manifest, profile = candidate["manifest"], candidate["profile"]
    if manifest["selector"]["target"] != TARGET:
        raise CandidateError("ProfileMismatch", "C06 acceptance is limited to actual macOS Arm64 consumers")
    for role in ("provider", "consumer"):
        if profile[role]["language"] != route[role]:
            raise CandidateError("ProfileMismatch", f"C06 {role} language differs from its direct route")
    if set(manifest["required_cases"]) != required_cases(group):
        raise CandidateError("ArtifactMismatch", "candidate mandatory cases differ from the independent C06 scope")
    candidate["group"] = group
    toolchain = read_json(candidate["root"] / "toolchain.json")
    if toolchain.get("schema") != "madb.native-toolchain/1":
        raise CandidateError("FormatInvalid", "unsupported C06 native toolchain metadata")
    if toolchain.get("compiler") != {"target": "arm64-apple-macosx14.0", "deployment_target": "14.0", "configuration": "Release"}:
        raise CandidateError("ProfileMismatch", "C06 compiler target/configuration differs from the declared complete profile")
    managed = toolchain.get("managed_installation", {})
    if set(managed) != {"receipt_sha256", "recipe_sha256", "components"}:
        raise CandidateError("ArtifactMismatch", "C06 candidate omits its managed compiler closure")
    protocol = toolchain.get("runtime_protocol", {})
    if protocol.get("schema") != "madb.native-runtime-protocol/1":
        raise CandidateError("FormatInvalid", "unsupported C06 runtime protocol metadata")
    budgets = protocol.get("budgets", {})
    expected = {"max_payload_bytes": 1024, "max_retained_payload_bytes": 4096, "max_pending_events": 8,
                "state_pending_capacity_per_subscription": 1, "max_subscription_handles": 8,
                "max_operation_handles": 8, "max_registered_waiters": 32, "owned_worker_threads_per_engine": 1}
    if any(type(budgets.get(name)) is not int or budgets[name] != value for name, value in expected.items()):
        raise CandidateError("ProfileMismatch", "C06 public budgets differ from the independently tested limits")
    if toolchain.get("provider_role") != "conformance-provider" or toolchain.get("test_support") is not (group == "swift-kotlin"):
        raise CandidateError("ProfileMismatch", "C06 provider role or exported test-support scope differs")
    locked_inputs = read_json(candidate["root"] / "madb.lock")["inputs"]
    if group != "swift-kotlin":
        helper_name = "metadata_v029" if group == "kotlin-native-rust" else "metadata_v032"
        helper = toolchain.get("declaration_helpers", {}).get(helper_name, {})
        inputs = helper.get("inputs", [])
        features = ["gobley-029"] if group == "kotlin-native-rust" else []
        if not inputs or helper.get("features") != features or len({item.get("path") for item in inputs}) != len(inputs):
            raise CandidateError("ArtifactMismatch", "declaration helper source/features proof is missing or duplicated")
        for item in inputs:
            if item not in locked_inputs or set(item) != {"path", "sha256", "size"}:
                raise CandidateError("ArtifactMismatch", "declaration helper input differs from locked author input")
    reference = toolchain.get("runtime_protocol_source", {})
    actual = {name: reference.get(name) for name in ("path", "sha256", "size")}
    locked = [entry for entry in locked_inputs if entry["path"] == actual["path"]]
    if locked != [actual]:
        raise CandidateError("ArtifactMismatch", "runtime protocol is not bound to exactly one locked author input")
    candidate["toolchain"] = toolchain
    return candidate
