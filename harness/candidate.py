"""Read-only public candidate checks; no MadB implementation is imported."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]*\Z")


class CandidateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def file_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _integer(value: str) -> int:
    number = int(value)
    if value == "-0" or abs(number) > 9007199254740991:
        raise CandidateError("FormatInvalid", "integer outside the public JSON subset")
    return number


def _reject_number(value: str):
    raise CandidateError("FormatInvalid", f"non-integer JSON number: {value}")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CandidateError("FormatInvalid", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path):
    data = path.read_bytes()
    if len(data) > 1024 * 1024:
        raise CandidateError("FormatInvalid", "JSON exceeds 1 MiB")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_object,
                           parse_int=_integer, parse_float=_reject_number,
                           parse_constant=_reject_number)
        def check(item, depth=0):
            if depth > 64:
                raise CandidateError("FormatInvalid", "JSON depth exceeds 64")
            if isinstance(item, str):
                item.encode("utf-8")
            elif isinstance(item, dict):
                for key, child in item.items():
                    check(key, depth + 1); check(child, depth + 1)
            elif isinstance(item, list):
                for child in item:
                    check(child, depth + 1)
        check(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CandidateError("FormatInvalid", str(error)) from error


def canonical_json(value) -> bytes:
    """JCS for MadB's integer-only subset, including UTF-16 object-key ordering."""
    if isinstance(value, dict):
        pairs = sorted(value.items(), key=lambda pair: pair[0].encode("utf-16-be"))
        return ("{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + canonical_json(item).decode("utf-8")
            for key, item in pairs) + "}").encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(canonical_json(item) for item in value) + b"]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def semantic_digest(domain: str, value) -> str:
    return file_digest(domain.encode("utf-8") + b"\n" + canonical_json(value))


def candidate_digest(manifest: dict) -> str:
    projection = {key: value for key, value in manifest.items() if key != "candidate_digest"}
    for name in ("files", "dependencies", "build_evidence"):
        projection[name] = sorted(projection[name], key=lambda item: item["path"])
    for name in ("public_symbols", "required_cases"):
        projection[name] = sorted(projection[name])
    return semantic_digest("madb.candidate/1", projection)


def profile_digest(profile: dict) -> str:
    """Public madb.profile/1 projection; behavior expectations do not use this codec."""
    projection = {key: value for key, value in profile.items() if key != "extensions"}
    projection["defaults"] = profile["defaults"]["values"]
    for name, key in (("tools", "id"), ("macros", "name"), ("restrictions", "feature")):
        projection[name] = sorted(profile[name], key=lambda item: item[key])
        if len({item[key] for item in profile[name]}) != len(profile[name]):
            raise CandidateError("ProfileMismatch", f"duplicate profile {name}")
    for name in ("required_features", "supported_features"):
        projection[name] = sorted(profile[name])
        if len(set(profile[name])) != len(profile[name]):
            raise CandidateError("ProfileMismatch", f"duplicate profile {name}")
    return semantic_digest("madb.profile/1", projection)


def project_digest(project: dict) -> str:
    """Public madb.project/1 projection, retaining source/profile file identities."""
    projection = {key: value for key, value in project.items() if key not in {"origin", "extensions"}}
    projection["boundaries"] = sorted(project["boundaries"], key=lambda item: item["id"])
    projection["policy_families"] = sorted(
        ({key: value for key, value in family.items() if key not in {"origin", "extensions"}}
         for family in project["policy_families"]), key=lambda item: item["id"])
    policies = []
    for policy in project["policies"]:
        item = {key: value for key, value in policy.items() if key not in {"origin", "extensions"}}
        item["families"] = sorted(policy["families"])
        policies.append(item)
    projection["policies"] = sorted(policies, key=canonical_json)
    return semantic_digest("madb.project/1", projection)


def source_id(source_key: dict) -> str:
    data = bytearray(b"madb.source-id/1\n")
    for name in ("reader", "package", "module", "kind", "qualified_name", "overload"):
        value = source_key[name]
        if not isinstance(value, str) or not value or "\0" in value:
            raise CandidateError("ArtifactMismatch", "incomplete source identity key")
        encoded = value.encode("utf-8")
        if len(encoded) > 4096:
            raise CandidateError("ArtifactMismatch", "source identity key exceeds its byte limit")
        data.extend(len(encoded).to_bytes(8, "big")); data.extend(encoded)
    return "source:v1:" + hashlib.sha256(data).hexdigest()


def identity_set(items, key):
    identities = [item[key] for item in items]
    if len(set(identities)) != len(identities):
        raise CandidateError("ArtifactMismatch", f"duplicate contract identity: {key}")
    return sorted(items, key=lambda item: item[key].encode("utf-16-be"))


def type_references(definition):
    kind = definition["kind"]
    if kind == "buffer": return [definition["element"]]
    if kind == "nullable": return [definition["inner"]]
    if kind == "record": return [field["type_id"] for field in definition["fields"]]
    if kind == "callback":
        return [parameter["type_id"] for parameter in definition["parameters"]] + [definition["result"]]
    if kind == "variant":
        return [definition["tag_type"]] + [case["payload"] for case in definition["cases"] if case["payload"] is not None]
    return []


def layout_projection(contract, reachable=None):
    return [{"subject": item["subject"], "result": item["result"]}
            for item in identity_set(contract["observations"], "subject")
            if reachable is None or item["subject"] in reachable]


def shape_digest(contract, symbol):
    types = {item["id"]: item for item in identity_set(contract["types"], "id")}
    shape = symbol["shape"]
    pending = [parameter["type_id"] for parameter in shape["parameters"]] + [shape["result"]]
    reachable = set()
    while pending:
        name = pending.pop()
        if name in reachable: continue
        if name not in types:
            raise CandidateError("ArtifactMismatch", f"unknown contract type: {name}")
        reachable.add(name); pending.extend(type_references(types[name]["definition"]))
    projection = {"shape": shape, "types": identity_set([types[name] for name in reachable], "id"),
                  "layouts": layout_projection(contract, reachable)}
    return semantic_digest("madb.shape/1", projection)


def structure_digest(contract):
    features = contract["required_features"]
    if len(set(features)) != len(features):
        raise CandidateError("ArtifactMismatch", "duplicate contract required feature")
    projection = {"schema": "madb.structure/1", "sdk_namespace": contract["sdk_namespace"],
                  "boundary_id": contract["boundary_id"], "types": identity_set(contract["types"], "id"),
                  "symbols": [{"public_id": symbol["public_id"], "shape": symbol["shape"]}
                              for symbol in identity_set(contract["symbols"], "public_id")],
                  "required_features": sorted(features, key=lambda value: value.encode("utf-16-be")),
                  "layouts": layout_projection(contract)}
    return semantic_digest("madb.contract/1", projection)


def policy_digest(contract):
    policies = []
    keys = set()
    symbols = {symbol["public_id"]: symbol for symbol in contract["symbols"]}
    for policy in contract["policies"]:
        symbol_id, slot = policy["symbol_id"], policy["slot"]
        key = (symbol_id, slot["kind"], slot.get("name", "") if slot["kind"] == "parameter" else "")
        if key in keys or symbol_id not in symbols:
            raise CandidateError("ArtifactMismatch", "duplicate or unknown effective policy slot")
        if slot["kind"] == "parameter" and slot["name"] not in {p["name"] for p in symbols[symbol_id]["shape"]["parameters"]}:
            raise CandidateError("ArtifactMismatch", "effective policy names an unknown parameter")
        keys.add(key)
        policies.append((key, {"symbol_id": symbol_id, "slot": slot, "values": policy["values"]}))
    return semantic_digest("madb.policy/1", [value for _, value in sorted(policies, key=lambda item: item[0])])


def verify_contract_digests(contract):
    sources = set()
    for symbol in identity_set(contract["symbols"], "public_id"):
        if symbol["precision"] not in {"artifact-derived", "compiler-derived", "schema-derived"}:
            raise CandidateError("ArtifactMismatch", "first-route declaration precision is not authoritative")
        actual_source = source_id(symbol["source_key"])
        if symbol["source_id"] != actual_source or actual_source in sources:
            raise CandidateError("ArtifactMismatch", "contract source identity differs or is duplicated")
        sources.add(actual_source)
        if symbol["public_id_origin"] == "derived" and symbol["public_id"] != contract["sdk_namespace"] + "." + actual_source[10:]:
            raise CandidateError("ArtifactMismatch", "derived public ID differs from source identity")
        if symbol["shape_digest"] != shape_digest(contract, symbol):
            raise CandidateError("AbiMismatch", "contract shape digest differs from its declaration")
    if structure_digest(contract) != contract["structure_digest"]:
        raise CandidateError("AbiMismatch", "contract structure digest differs from its declarations")
    if policy_digest(contract) != contract["policy_digest"]:
        raise CandidateError("ArtifactMismatch", "effective policy digest differs from its declared values")


def verify_layout_sources(contract, profile):
    records = {item["id"] for item in contract["types"]
               if item["definition"]["kind"] == "record" and item["definition"].get("layout") == "c"}
    tools = {tool["id"]: tool for tool in profile["tools"]}
    observations = identity_set(contract["observations"], "subject")
    if {item["subject"] for item in observations} != records:
        raise CandidateError("AbiMismatch", "C record compiler layout observations are incomplete or unrelated")
    for item in observations:
        if (item["kind"] != "layout" or item["precision"] != "compiler-derived"
                or item["selector"] != contract["selector"] or item["input_digest"] != contract["source_digest"]):
            raise CandidateError("AbiMismatch", "layout observation does not match the selected inputs/target/precision")
        producer = item["producer"]
        tool = tools.get(producer["id"])
        if tool is None or any(producer[key] != tool[key] for key in ("version", "sha256")):
            raise CandidateError("AbiMismatch", "layout observation compiler differs from the locked profile")


def verify_reference(root: Path, reference: dict, schema: str, path: str | None = None):
    _keys(reference, ("path", "sha256", "size", "schema"), "public file reference")
    relative = str(logical_path(reference["path"]))
    if reference["schema"] != schema or (path is not None and relative != path):
        raise CandidateError("ArtifactMismatch", "public file reference has wrong schema/path")
    data = (root / relative).read_bytes()
    if type(reference["size"]) is not int or len(data) != reference["size"] or file_digest(data) != reference["sha256"]:
        raise CandidateError("ArtifactMismatch", f"inner file reference differs: {relative}")


def verify_lock_closure(root, manifest, profile, contract):
    if file_digest((root / "madb.lock").read_bytes()) != manifest["lock_digest"]:
        raise CandidateError("ArtifactMismatch", "candidate lock_digest differs from actual madb.lock bytes")
    if profile_digest(profile) != manifest["selector"]["profile_digest"]:
        raise CandidateError("ProfileMismatch", "public profile semantic digest differs")
    verify_reference(root, profile["sdk"], "madb.native-toolchain/1", "toolchain.json")
    lock = read_json(root / "madb.lock")
    if lock.get("schema") != "madb.lock/1":
        raise CandidateError("FormatInvalid", "unsupported public lock schema")
    for name in ("profiles", "tools", "components", "inputs", "schemas"):
        if not isinstance(lock.get(name), list) or not 1 <= len(lock[name]) <= 4096:
            raise CandidateError("FormatInvalid", f"invalid public lock {name}")
    available = {item["path"]: item for item in manifest["files"]}
    for collection in ("inputs", "schemas"):
        seen = set()
        for item in lock[collection]:
            _keys(item, ("path", "sha256", "size"), "locked input file")
            relative = str(logical_path(item["path"]))
            if relative in seen:
                raise CandidateError("ArtifactMismatch", "duplicate locked input path")
            seen.add(relative)
            if relative in available and item != available[relative]:
                raise CandidateError("ArtifactMismatch", f"available locked input differs: {relative}")
    source_projection = sorted(lock["inputs"], key=lambda item: item["path"].encode("utf-16-be"))
    if semantic_digest("madb.source/1", source_projection) != contract["source_digest"]:
        raise CandidateError("ArtifactMismatch", "locked source inventory differs from the contract input digest")
    selected = [entry for entry in lock["profiles"] if entry["id"] == profile["id"]]
    if len(selected) != 1 or selected[0]["semantic_digest"] != manifest["selector"]["profile_digest"]:
        raise CandidateError("ProfileMismatch", "lock does not bind exactly one matching profile")
    verify_reference(root, selected[0]["file"], "madb.profile/1", "profile.json")
    locked_tools = {tool["id"]: tool for tool in lock["tools"]}
    if len(locked_tools) != len(lock["tools"]) or any(locked_tools.get(tool["id"]) != tool for tool in profile["tools"]):
        raise CandidateError("ProfileMismatch", "profile tools differ from the public lock")
    project = read_json(root / "project.json")
    if project.get("schema") != "madb.project/1" or project_digest(project) != lock["project_digest"]:
        raise CandidateError("ArtifactMismatch", "locked project semantic digest differs")
    boundaries = [boundary for boundary in project["boundaries"] if boundary["id"] == contract["boundary_id"]]
    if len(boundaries) != 1:
        raise CandidateError("ProfileMismatch", "contract boundary is not uniquely selected by project")
    boundary = boundaries[0]
    if any(boundary[key] != manifest["selector"][key] for key in ("route", "target", "direction")):
        raise CandidateError("ProfileMismatch", "project boundary selects a different native configuration")
    verify_reference(root, boundary["profile"], "madb.profile/1", "profile.json")


def logical_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise CandidateError("ArtifactMismatch", "invalid logical path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise CandidateError("ArtifactMismatch", f"non-relative logical path: {value}")
    return path


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise CandidateError("FormatInvalid", f"invalid {label} fields")


def verify_candidate(root: Path) -> dict:
    root = root.resolve(strict=True)
    manifest = read_json(root / "candidate.json")
    _keys(manifest, ("schema", "candidate_digest", "selector", "generation_id", "contract_digest",
                     "policy_digest", "lock_digest", "manifest_path", "files", "dependencies",
                     "public_symbols", "required_cases", "build_evidence"), "candidate")
    if manifest["schema"] != "madb.candidate/1" or manifest["manifest_path"] != "candidate.json":
        raise CandidateError("FormatInvalid", "unsupported candidate schema/manifest path")
    for name in ("candidate_digest", "generation_id", "contract_digest", "policy_digest", "lock_digest"):
        if not isinstance(manifest[name], str) or not DIGEST.fullmatch(manifest[name]):
            raise CandidateError("FormatInvalid", f"invalid {name}")
    selector = manifest["selector"]
    _keys(selector, ("route", "profile_id", "profile_digest", "target", "direction"), "selector")
    if selector["route"] != "RUST-C-ABI" or selector["direction"] != "consumer-to-provider":
        raise CandidateError("ProfileMismatch", "candidate is not a direct first-route consumer")
    if not DIGEST.fullmatch(selector["profile_digest"]):
        raise CandidateError("FormatInvalid", "invalid profile digest")
    for name in ("profile_id", "target"):
        if not isinstance(selector[name], str) or not ID.fullmatch(selector[name]):
            raise CandidateError("FormatInvalid", f"invalid selector {name}")
    for name in ("public_symbols", "required_cases"):
        values = manifest[name]
        if not isinstance(values, list) or not values or len(values) > 4096 or any(not isinstance(v, str) or not ID.fullmatch(v) for v in values) or len(set(values)) != len(values):
            raise CandidateError("FormatInvalid", f"invalid {name}")
    files = {}
    for name in ("files", "dependencies", "build_evidence"):
        entries = manifest[name]
        if not isinstance(entries, list) or len(entries) > 4096 or (name != "dependencies" and not entries):
            raise CandidateError("FormatInvalid", f"invalid {name}")
        seen = set()
        for entry in entries:
            required_fields = {"path", "sha256", "size"} if name == "files" else {"path", "sha256", "size", "schema"}
            if not isinstance(entry, dict) or set(entry) != required_fields:
                raise CandidateError("FormatInvalid", f"invalid {name} file reference")
            if name != "files" and (not isinstance(entry["schema"], str) or not ID.fullmatch(entry["schema"])):
                raise CandidateError("FormatInvalid", "invalid referenced schema identity")
            relative = str(logical_path(entry["path"]))
            if relative == "candidate.json" or relative in seen:
                raise CandidateError("ArtifactMismatch", "duplicate/self-referencing candidate file")
            seen.add(relative)
            if not isinstance(entry["sha256"], str) or not DIGEST.fullmatch(entry["sha256"]) or type(entry["size"]) is not int or entry["size"] < 0:
                raise CandidateError("FormatInvalid", "invalid file digest/size")
            if relative in files and files[relative] != (entry["sha256"], entry["size"]):
                raise CandidateError("ArtifactMismatch", "inconsistent file references")
            files[relative] = (entry["sha256"], entry["size"])
    if candidate_digest(manifest) != manifest["candidate_digest"]:
        raise CandidateError("ArtifactMismatch", "candidate semantic digest differs")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise CandidateError("ArtifactMismatch", "candidate contains a symbolic link")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise CandidateError("ArtifactMismatch", "candidate contains a special file")
    if actual != set(files) | {"candidate.json"}:
        raise CandidateError("ArtifactMismatch", "candidate file inventory differs")
    for relative, (digest, size) in files.items():
        data = (root / relative).read_bytes()
        if len(data) != size or file_digest(data) != digest:
            raise CandidateError("ArtifactMismatch", f"file bytes differ: {relative}")
    identity = read_json(root / "identity.json")
    _keys(identity, ("schema", "bootstrap_version", "interface_digest", "profile_digest"), "native identity")
    if identity["schema"] != "madb.native-identity/1" or type(identity["bootstrap_version"]) is not int or identity["bootstrap_version"] != 1:
        raise CandidateError("AbiMismatch", "unsupported bootstrap identity")
    if not DIGEST.fullmatch(identity["interface_digest"]) or identity["profile_digest"] != selector["profile_digest"]:
        raise CandidateError("ProfileMismatch", "native identity differs from selected profile")
    provenance = read_json(root / "provenance.json")
    provenance_fields = {"schema", "producer_revision", "input_digest", "tool_digest"}
    if "provisional" in provenance:
        provenance_fields.add("provisional")
        if type(provenance["provisional"]) is not bool:
            raise CandidateError("FormatInvalid", "provisional must be a boolean")
    _keys(provenance, provenance_fields, "native provenance")
    if provenance["schema"] != "madb.native-provenance/1" or not REVISION.fullmatch(provenance["producer_revision"]) or not DIGEST.fullmatch(provenance["input_digest"]) or not DIGEST.fullmatch(provenance["tool_digest"]):
        raise CandidateError("ArtifactMismatch", "invalid producer provenance")
    contract = read_json(root / "contract.json")
    if (contract.get("schema") != "madb.contract-ir/1" or contract.get("selector") != selector
            or contract.get("structure_digest") != manifest["contract_digest"]
            or contract.get("policy_digest") != manifest["policy_digest"]
            or contract.get("source_digest") != provenance["input_digest"]):
        raise CandidateError("ArtifactMismatch", "candidate and public contract identities differ")
    public_ids = [symbol["public_id"] for symbol in contract["symbols"]]
    if sorted(public_ids) != sorted(manifest["public_symbols"]) or len(set(public_ids)) != len(public_ids):
        raise CandidateError("ArtifactMismatch", "declared public symbols differ from the contract")
    verify_contract_digests(contract)
    profile = read_json(root / "profile.json")
    if profile.get("schema") != "madb.profile/1" or any(profile.get(key) != selector[key] for key in ("route", "target", "direction")) or profile.get("id") != selector["profile_id"]:
        raise CandidateError("ProfileMismatch", "candidate and public profile selection differ")
    verify_lock_closure(root, manifest, profile, contract)
    verify_layout_sources(contract, profile)
    return {"root": root, "manifest": manifest, "identity": identity, "provenance": provenance,
            "contract": contract, "profile": profile}
