"""Independent encoding of the public madb.c07-abi/1 semantic projection.

Source text, tool images and generation receipts remain bound by candidate file
and build identities. This module compares protocol facts, never producer code.
"""
from candidate import CandidateError, read_json, semantic_digest

PROVENANCE_KEYS = frozenset(("location", "source", "schema", "authority", "compilerApiVersion",
                             "imports", "tools", "tool", "sdkDependencies", "dependencies"))
BACKENDS = frozenset(("napi-ohos", "napi-sys-ohos", "napi-build-ohos", "napi-derive-ohos", "napi-derive-backend-ohos"))
ROLE_KEYS = ("values", "calls", "slots", "limits", "error_channel", "value_slots", "test_types", "execution_domain")


def semantic_facts(value):
    if isinstance(value, list):
        return [semantic_facts(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {name: semantic_facts(item) for name, item in value.items() if name not in PROVENANCE_KEYS}


def abi_document(contract, declarations, policy):
    logical = {"types": contract["types"], "required_features": contract["required_features"],
               "symbols": [{"public_id": row["public_id"], "shape": row["shape"]} for row in contract["symbols"]],
               "policies": [{name: row[name] for name in ("symbol_id", "slot", "values")} for row in contract["policies"]]}
    physical = {name: semantic_facts(declarations[name]) for name in ("public", "gateway", "c_seam") if name in declarations}
    if "rust" in declarations:
        evidence = declarations["rust"]
        physical["rust"] = {
            "exports": [{name: row[name] for name in ("name", "arity", "parameters", "rawReturn")}
                        for row in evidence["macro"]["descriptor"]["exports"]],
            "napi_features": [{"name": row["name"], "features": row["features"]}
                              for row in evidence["resolved_packages"] if row["name"] in BACKENDS]}
    if "kotlin" in declarations:
        evidence = declarations["kotlin"]
        physical["kotlin"] = {
            "facts": semantic_facts(evidence["facts"]),
            "declaration": semantic_facts(evidence["descriptor"]),
            "record": {name: semantic_facts(evidence["record_schema"][name]) for name in ("qualifiedName", "fields")},
            "notification_interfaces": evidence["frontend_policy"]["notification_interfaces"],
            "parameters": evidence["frontend_policy"]["parameters"],
            "execution_domain": policy["execution_domain"]}
    return {"logical": logical, "physical": physical,
            "runtime_roles": {name: policy[name] for name in ROLE_KEYS if name in policy}}


def verify_abi(candidate, route):
    root = candidate["root"]
    declarations = read_json(root / "declarations.json")
    policy = read_json(root / "generated/contract/runtime-policy.json")
    present = set(declarations) & {"gateway", "c_seam", "rust", "kotlin"}
    expected = {"kotlin"} if route == "kotlin" else {"gateway", "c_seam"} | ({"rust"} if route == "rust" else set())
    if "public" not in declarations or present != expected:
        raise CandidateError("AbiMismatch", "ABI authorities do not match the selected route")
    try:
        value = abi_document(candidate["contract"], declarations, policy)
        actual = semantic_digest("madb.c07-abi/1", value)
    except (KeyError, TypeError) as error:
        raise CandidateError("FormatInvalid", "incomplete public C07 ABI facts") from error
    if actual != candidate["identity"]["abi_digest"]:
        raise CandidateError("AbiMismatch", "public type/protocol facts differ from embedded ABI identity")
    return {"domain": "madb.c07-abi/1", "abi_digest": actual,
            "scope": "logical ContractIR, physical declarations and explicit runtime semantics"}
