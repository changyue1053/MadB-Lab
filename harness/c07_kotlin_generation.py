"""Independent Kotlin author-change oracles over public Source evidence.

KSP facts and the emitted declaration are observations, not expected values.
The expectation is one renamed Int/String record and the existing owned API.
"""
from pathlib import Path
import json
import re
from candidate import file_digest, logical_path, read_json
from c07_execution import ExecutionError

TYPES = "sdk/kotlin/arkts-owned/src/common/BoundaryTypes.kt"
EXPORTS = "sdk/kotlin/arkts-owned/src/common/OwnedExports.kt"
FUNCTIONS = {
    "ownedCancel", "ownedClaimResult", "ownedConnect", "ownedDeliver", "ownedObserve",
    "ownedOpen", "ownedPeek", "ownedPublish", "ownedRequestClose", "ownedRoundtrip",
    "ownedRuntimeClose", "ownedSubmit", "ownedTakeSnapshot", "ownedTakeStatus", "ownedWatchClose",
}
GENERATED = {
    "kotlin/com/madb/c07/GeneratedRecordCodec.kt",
    *{"kotlin/org/cpf/kotlin/akinterop/generated/KNapiGenerated_" + name + ".kt"
      for name in ("Index", "InterfacesProxy", "MetaData", "RegisterEntry")},
    *{"resources/" + name for name in ("ffi_export.d.ts", "frontend-facts.json", "record-export.d.ts", "record-schema.json")},
}
DIAGNOSTICS = {
    "reject-async": ("suspend/generic/extension export unsupported", r"\s*suspend fun onReady\(\)"),
    "reject-async-listener": ("suspend/generic/extension export unsupported", r"\s*suspend fun onValue\("),
    "reject-callback-result": (
        "synchronous return-valued callback is unsupported by the nonblocking notification profile",
        r"\s*fun onValue\(.*\): Int"),
}


def require(condition, message):
    if not condition:
        raise ExecutionError("Kotlin generation oracle: " + message)


def index(items, key):
    result = {item[key]: item for item in items}
    require(len(result) == len(items), "duplicate " + key)
    return result


def validate_facts(kotlin):
    """Do not reuse a producer policy or mapping implementation as the oracle."""
    require(kotlin["authority"] == "actual CPF Kotlin KSP1 and akinterop 1.1.0; managed single-record profile"
            and kotlin["test_support"] is False and kotlin["typed_api_inferred"] is False,
            "wrong Kotlin declaration authority or companion scope")
    facts, descriptor = kotlin["facts"], kotlin["descriptor"]
    require(facts["schema"] == "madb.kotlin-ksp-facts/1" and descriptor["authority"] ==
            "actual KSP symbols plus emitted declaration parsed by pinned TypeScript AST",
            "missing actual KSP and emitted-declaration evidence")
    record = facts["record"]
    expected_fields = [("value", "kotlin.Int"), ("text", "kotlin.String")]
    require(record["qualifiedName"] == "com.madb.c07.Parcel" and
            [(f["name"], f["kotlinType"]) for f in record["fields"]] == expected_fields,
            "Kotlin record was not actually renamed with its Int/String shape")
    schema = kotlin["record_schema"]
    require(schema["qualifiedName"] == record["qualifiedName"] and schema["source"] == TYPES and
            [(f["name"], f["kotlinType"]) for f in schema["fields"]] == expected_fields,
            "record codec schema differs from actual KSP facts")
    functions = index(facts["functions"], "name")
    exports = index(descriptor["functions"], "name")
    require(set(functions) == set(exports) == FUNCTIONS, "ordinary owned export set changed")
    mapped = {"kotlin.Int": "number", "kotlin.String": "string", "kotlin.Unit": "void",
              "com.madb.c07.Parcel": "Parcel", "com.madb.c07.RuntimeDispatcher": "RuntimeDispatcher"}
    for name, function in functions.items():
        require(function["qualifiedName"] == "com.madb.c07." + name,
                "export resolved to a different Kotlin declaration")
        require(all(p["kotlinType"] in mapped for p in function["parameters"]) and function["returnType"] in mapped,
                "export retained Snapshot or an unsupported Kotlin type")
        exported = exports[name]
        require([(p["name"], mapped[p["kotlinType"]]) for p in function["parameters"]] ==
                [(p["name"], p["type"]) for p in exported["parameters"]] and
                mapped[function["returnType"]] == exported["returnType"], "KSP/exported declaration mismatch")
    roundtrip = functions["ownedRoundtrip"]
    require([(p["name"], p["kotlinType"]) for p in roundtrip["parameters"]] ==
            [("snapshot", "com.madb.c07.Parcel"), ("engine", "kotlin.String")] and
            roundtrip["returnType"] == "com.madb.c07.Parcel", "actual Kotlin roundtrip did not use Parcel")
    interfaces = index(descriptor["interfaces"], "name")
    require(set(interfaces) == {"Parcel", "RuntimeDispatcher"}, "emitted record/interface names differ")
    require([(m["kind"], m["name"], m["type"], m["readonly"]) for m in interfaces["Parcel"]["members"]] ==
            [("property", "value", "number", True), ("property", "text", "string", True)],
            "emitted record field shape differs")
    require(len(facts["interfaces"]) == 1 and facts["interfaces"][0]["qualifiedName"] ==
            "com.madb.c07.RuntimeDispatcher", "wrong notification interface")
    methods = index(facts["interfaces"][0]["methods"], "name")
    declared = index(interfaces["RuntimeDispatcher"]["members"], "name")
    expected_methods = {"onReady": [], "onValue": [("handle", "kotlin.String"), ("snapshot", "com.madb.c07.Parcel")],
                        "onClosed": [("handle", "kotlin.String"), ("status", "kotlin.Int")]}
    require(set(methods) == set(declared) == set(expected_methods), "notification method set differs")
    for name, parameters in expected_methods.items():
        require([(p["name"], p["kotlinType"]) for p in methods[name]["parameters"]] == parameters and
                methods[name]["returnType"] == "kotlin.Unit" and declared[name]["kind"] == "method" and
                declared[name]["returnType"] == "void" and
                [(p["name"], p["type"]) for p in declared[name]["parameters"]] == [(n, mapped[t]) for n, t in parameters],
                "notification Parcel/void contract differs")
    generated = index(kotlin["generated"], "path")
    require(set(generated) == GENERATED, "actual KSP nine-file output inventory differs")
    for item in generated.values():
        data = item["text"].encode("utf-8")
        require(file_digest(data) == item["sha256"] and len(data) == item["size"], "KSP generated bytes differ from inventory")
    require(json.loads(generated["resources/frontend-facts.json"]["text"]) == facts and
            json.loads(generated["resources/record-schema.json"]["text"]) == schema and
            generated["resources/record-export.d.ts"]["text"] == kotlin["declaration"], "generated KSP facts disagree")
    require('KSPClass("Parcel", "com.madb.c07.Parcel")' in generated[
        "kotlin/org/cpf/kotlin/akinterop/generated/KNapiGenerated_MetaData.kt"]["text"],
        "stock akinterop metadata did not include the real renamed class")
    return facts


def validate_kotlin_declarations(declarations, output, source):
    require(not any(k in declarations for k in ("c_seam", "gateway", "rust")), "Kotlin cannot use a substitute C/Rust seam")
    kotlin = declarations["kotlin"]
    facts = validate_facts(kotlin)
    workspace = output / "workspace"
    inputs = index(kotlin["source_inputs"], "path")
    for logical in (TYPES, EXPORTS):
        data = (workspace / logical).read_bytes()
        require(inputs[logical]["sha256"] == file_digest(data) and inputs[logical]["size"] == len(data),
                "KSP source input is not the actual frozen author file")
    for entry, logical, marker in ((facts["record"], TYPES, "data class Parcel("),
                                   (next(f for f in facts["functions"] if f["name"] == "ownedRoundtrip"), EXPORTS,
                                    "fun ownedRoundtrip(snapshot: Parcel, engine: String): Parcel")):
        location = entry["source"]
        require(location["path"] == logical and type(location["line"]) is int, "KSP author source location differs")
        lines = (workspace / logical).read_text().splitlines()
        require(1 <= location["line"] <= len(lines) and marker in lines[location["line"] - 1],
                "KSP location is not on the actual renamed Kotlin declaration")
    require(read_json(source / "generated/contract/kotlin-ksp-facts.json") == facts and
            read_json(source / "generated/contract/kotlin-record-schema.json") == kotlin["record_schema"] and
            (source / "generated/native/record-export.d.ts").read_text() == kotlin["declaration"],
            "Source Kotlin evidence differs from its actual frontend")
    binding = read_json(source / "generated/contract/kotlin-binding.json")
    require(binding["record"] == "Parcel", "runtime port binding did not use renamed record")
    port = (source / "generated/facade/KotlinPort.ets").read_text()
    validate_port(port)
    return {"route": "kotlin", "record": facts["record"]["qualifiedName"], "ksp_functions": 15,
            "generated_files": 9, "source": facts["record"]["source"], "typed_api_inferred": False}


def validate_port(port):
    # Private aliases do not create a second record. The imported public name
    # must be Parcel, and the notification must use that exact local binding.
    imports = re.findall(r"import\s+bootstrap,\s*\{\s*OwnedApi,\s*Parcel(?:\s+as\s+([A-Za-z_][A-Za-z_0-9]*))?\s*,\s*RuntimeDispatcher\s*\}\s*from\s*['\"]libmadbc07sdkkotlin\.so['\"]\s*;", port)
    require(len(imports) == 1, "runtime port did not import the actual renamed Parcel")
    local = imports[0] or "Parcel"
    require(re.search(r"onValue\(handle: string, snapshot: " + re.escape(local) + r"\): void", port) is not None,
            "runtime port notification does not use its imported record binding")


def validate_kotlin_rejection(output, command, fixture):
    require(not command["timeout"] and command["exit_code"] == 1, "negative timed out or returned wrong status")
    message, expected_line = DIAGNOSTICS[fixture]
    pattern = r"\[ksp\] ([^\r\n]*?/BoundaryTypes\.kt):([1-9][0-9]*): MADB_RECORD: " + re.escape(message)
    # Port stderr may retain the same authentic compiler line in both summary and tail.
    matches = {(m[1], int(m[2])) for m in re.finditer(pattern, command["stderr"])}
    require(len(matches) == 1, "negative lacks its unique real KSP file/line diagnostic")
    compiler_path, line = matches.pop()
    actual = output / "workspace" / TYPES
    lines = actual.read_text().splitlines()
    require(1 <= line <= len(lines) and re.match(expected_line, lines[line - 1]) is not None,
            "KSP diagnostic is not on the intended unsupported Kotlin declaration")
    # The compiler's isolated copy must be byte-identical to the public Source input.
    compiler_source = Path(compiler_path)
    require(compiler_source.name == "BoundaryTypes.kt" and compiler_source.is_file() and
            not compiler_source.is_symlink() and compiler_source.read_bytes() == actual.read_bytes(),
            "compiler diagnostic points to a different author input")
    result = read_json(output / "result.json")
    require(result.get("requested_stage") == "generate" and result.get("completed_requested_stage") is False and
            result.get("target_executed") is False and "source" not in result and "generation_id" not in result and
            "MADB_RECORD: " + message in result.get("error", ""), "negative result omitted or contradicted its compiler diagnostic")
    require(not (output / "workspace/generate-execution.json").exists() and
            not list((output / "workspace/domain/batches").glob("*/files/outputs.json")), "negative committed generation")
    return {"fixture": fixture, "observation": "passed", "classification": "MADB_RECORD",
            "source": TYPES, "compiler_source": str(compiler_source), "line": line, "column": None,
            "source_text": lines[line - 1], "committed_source": False}
