"""Bind public C07 route build receipts to the admitted native/HAR bytes.

This verifies the published source/tool/object/link chain. It does not replace
independent source review or claim that arbitrary machine code was decompiled.
All inputs are candidate members; no neighboring producer checkout is imported.
"""
import re

from candidate import CandidateError, file_digest, read_json

PROVIDERS = {
    "c": ("sdk/c/arkts-provider/src/provider.c", "c17", "clang"),
    "cpp": ("sdk/cpp/arkts-provider/src/provider.cpp", "c++17", "clangxx"),
    "rust": ("sdk/rust/arkts-provider/src/lib.rs", None, "cargo"),
}


def _require(condition, message):
    if not condition:
        raise CandidateError("ArtifactMismatch", "route ownership: " + message)


def _one(values, label):
    _require(len(values) == 1, "missing or ambiguous " + label)
    return values[0]


def _ref(value):
    _require(isinstance(value, dict) and isinstance(value.get("path"), str) and
             isinstance(value.get("sha256"), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value["sha256"]) and
             type(value.get("size")) is int and value["size"] >= 0, "malformed public file reference")
    return {key: value[key] for key in ("path", "sha256", "size")}


def verify_route_ownership(candidate):
    route, manifest = candidate["route"], candidate["manifest"]
    _require(route in PROVIDERS, "route requires a separate ownership implementation")
    root = candidate["root"]
    inventory = {item["path"]: _ref(item) for collection in ("files", "dependencies", "build_evidence")
                 for item in manifest[collection]}
    used = set()
    def data(name):
        _require(name in inventory, "unlisted candidate evidence: " + name)
        value = (root / name).read_bytes()
        _require(len(value) == inventory[name]["size"] and file_digest(value) == inventory[name]["sha256"], "changed candidate evidence: " + name)
        used.add(name)
        return value
    def document(name):
        data(name)
        return read_json(root / name)
    def tool(command, name):
        expected = _one([item for item in candidate["toolchain"]["tools"] if item["id"] == ("ohrs" if name == "ohrs" else "c07-" + name)], "tool " + name)
        _require(command.get("tool") == name and type(command.get("exit_code")) is int and command["exit_code"] == 0 and
                 command.get("tool_sha256") == expected["sha256"], "compiler command/tool identity differs: " + name)
        return {"id": expected["id"], "sha256": expected["sha256"]}

    stages = {}
    for item in manifest["build_evidence"]:
        evidence = document(item["path"])
        phase = evidence.get("phase")
        if phase not in ("compile", "link"):
            continue
        _require(phase not in stages and evidence.get("schema") == "madb.build-evidence/1" and
                 evidence.get("status") == "passed" and type(evidence.get("exit_code")) is int and evidence["exit_code"] == 0 and
                 evidence.get("generation_id") == manifest["generation_id"] and
                 evidence.get("profile_digest") == manifest["selector"]["profile_digest"] and
                 evidence.get("input_digest") == candidate["provenance"]["input_digest"], "build phase is not bound to this candidate")
        for log in evidence["logs"]:
            _require(_ref(log) == inventory.get(log["path"]), "build log reference differs from candidate")
        stages[phase] = evidence
    _require(set(stages) == {"compile", "link"}, "compile/link receipts are incomplete")
    compile_rows = document("logs/compile-commands.json")
    link_rows = document("logs/link-commands.json")
    for phase, name in (("compile", "logs/compile-commands.json"), ("link", "logs/link-commands.json")):
        _require(any(log["path"] == name for log in stages[phase]["logs"]), phase + " receipt does not name its actual command log")

    source, standard, compiler = PROVIDERS[route]
    lock = document("madb.lock")
    source_ref = _ref(_one([item for item in lock["inputs"] if item["path"] == source], "locked route provider source"))
    header = data("generated/native/identity.generated.hpp")
    header = re.sub(rb"//[^\n]*", b"", re.sub(rb"/\*.*?\*/", b"", header, flags=re.S))
    factories = re.findall(rb"GatewayProviderCreate\s*=\s*::(mp_[a-z]+_create)\s*;", header)
    _require(factories == [("mp_" + route + "_create").encode()], "gateway does not select exactly the declared route provider")
    module = candidate["module"]
    dso = "native/lib" + module + ".so"
    actual = data(dso)
    _require(candidate["native_members"].get("package/libs/arm64-v8a/lib" + module + ".so") == actual,
             "actual HAR/native provider bytes differ")
    linked = _ref(_one([item for item in stages["link"]["outputs"] if item["path"] == dso], "linked route DSO"))
    _require(linked == inventory[dso], "linked route DSO receipt differs from actual candidate bytes")
    objects = {item["path"]: _ref(item) for item in stages["compile"]["outputs"]}
    tools = []
    details = {}
    if route in ("c", "cpp"):
        commands = [row for row in compile_rows if isinstance(row.get("arguments"), list) and
                    any(arg.endswith("/inputs/" + source) for arg in row["arguments"])]
        command = _one(commands, "actual provider compilation")
        tools.append(tool(command, compiler))
        arguments = command["arguments"]
        _require([arg for arg in arguments if arg.startswith("-std=")] == ["-std=" + standard] and
                 "--target=aarch64-linux-ohos23.0.0" in arguments and "-c" in arguments and "-o" in arguments,
                 "provider language/target/compile mode differs")
        _require(arguments[arguments.index("-c") + 1].endswith("/inputs/" + source) and
                 arguments[arguments.index("-o") + 1].endswith("/work/objects/provider.o"), "provider compile input/output differs")
        dependencies = _one([row for row in compile_rows if row.get("kind") == "actual-compiler-dependencies" and row.get("unit") == "provider"], "provider dependency observation")
        frozen = _one([item for item in dependencies["dependencies"] if item.get("path") == source and item.get("origin") == "frozen-input"], "actual provider compiler dependency")
        _require(_ref(frozen) == source_ref, "compiled provider source differs from locked source")
        _require("objects/provider.o" in objects, "provider object has no compiler output receipt")
        link = _one([row for row in link_rows if isinstance(row.get("arguments"), list) and "-shared" in row["arguments"]], "actual native link")
        tools.append(tool(link, "clangxx"))
        _require(sum(arg.endswith("/inputs/objects/provider.o") for arg in link["arguments"]) == 1 and
                 "-Wl,-soname,lib" + module + ".so" in link["arguments"], "final link does not consume the route provider object")
        details = {"provider_object": objects["objects/provider.o"], "language_standard": standard}
    else:
        rust_link = document("rust-link.json")
        rust_symbols = document("rust-symbols.json")
        archive = objects.get("objects/libmadb_arkts_gateway.a")
        _require(archive is not None and rust_link.get("source_archive_sha256") == archive["sha256"] and
                 rust_link.get("elf_soname") == "lib" + module + ".so", "Rust backend consumes a different gateway archive/soname")
        command = _one([row for row in link_rows if row.get("tool") == "ohrs"], "actual Rust backend link")
        tools.append(tool(command, "ohrs"))
        _require(all(flag in command["arguments"] for flag in ("build", "--release", "--offline", "--locked")) and
                 "lib" + module + ".so" in command["arguments"], "Rust backend flags/route soname differ")
        check = _one([row for row in compile_rows if row.get("tool") == "cargo" and "check" in row.get("arguments", [])], "actual Rust frontend compilation")
        tools.append(tool(check, "cargo"))
        _require(all(flag in check["arguments"] for flag in ("--offline", "--locked", "--release", "aarch64-unknown-linux-ohos")), "Rust frontend flags/target differ")
        macro = rust_link.get("actual_macro", {})
        exports = macro.get("descriptor", {}).get("exports", [])
        _require(exports and len({entry["name"] for entry in exports}) == len(exports) and
                 "napi_register_module_v1" in rust_symbols.get("dynamic_defined", []) and
                 isinstance(rust_symbols.get("frontend", {}).get("macro"), dict), "actual Rust macro/import inventory is missing")
        details = {"gateway_archive": archive, "macro_exports": len(exports),
                   "frontend_evidence": inventory["rust-symbols.json"],
                   "frontend_scope": "separate published macro/import evidence; gateway dynamic counters do not cover it"}
    return {"status": "bound", "candidate_digest": manifest["candidate_digest"], "route": route,
            "producer_revision": candidate["provenance"]["producer_revision"], "expected_identity": candidate["identity"]["expected_identity"],
            "provider_source": source_ref, "native_artifact": linked, "tools": tools, "details": details,
            "inputs": [inventory[name] for name in sorted(used)],
            "scope": "public recorded source/tool/object/link chain and exact admitted native/HAR bytes",
            "limits": ["Source content/destructor semantics require independent source review at the recorded revision/hash.",
                       "Intermediate object bytes are not shipped in this candidate; their hashes remain compiler output receipts.",
                       "Runtime computation/free, child baseline and physical cleanup must pass this candidate's actual controlled scenarios."]}
