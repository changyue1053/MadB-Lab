"""Finite Kotlin source review + public C04 receipt binding, not runtime proof.

Only admitted candidate members and a fixed Lab review inventory are read. No
producer checkout, compiler, cache, or patch implementation is imported.
"""
from pathlib import Path
import json
import re

from candidate import CandidateError, file_digest, logical_path, read_json
from source_review_selection import select_source_review

REVIEW = Path(__file__).resolve().parents[1] / "expected/c07/kotlin-source-review.json"
HELPERS = "array arraybuffer cb_info clazz exception function knapi module object property reference type".split()
SUPPORT = "executor lifecycle main_gate".split()
ERRORS = (CandidateError, OSError, KeyError, TypeError, ValueError, IndexError)


def _require(value, message):
    if not value:
        raise CandidateError("ArtifactMismatch", "Kotlin source review: " + message)


def _one(values, label):
    _require(len(values) == 1, "missing/ambiguous " + label)
    return values[0]


def _refs(values, label):
    result = {}
    for value in values:
        path = str(logical_path(value["path"]))
        _require(path not in result and re.fullmatch(r"sha256:[0-9a-f]{64}", value["sha256"]) and
                 type(value["size"]) is int and value["size"] >= 0, "invalid/duplicate " + label)
        result[path] = {k: value[k] for k in ("path", "sha256", "size")}
    return result


def _review_sources(candidate, review, declaration, lock):
    _require(review["schema"] == "madb-lab.c07-kotlin-source-review/1" and
             review["status"] == "reviewed" and
             review["producer_revision"] == candidate["provenance"]["producer_revision"],
             "independent review/final producer revision is not approved")
    test = candidate.get("companion", False)
    variant = "test" if test else "ordinary"
    _require(candidate["profile"]["id"].endswith("-test") is test and
             declaration["test_support"] is test and candidate["toolchain"]["kotlin"]["test_support"] is test,
             "profile/KSP/toolchain variant differs")
    record = review["variants"][variant]
    known = _refs(review["source_files"], "reviewed source")
    sources = _refs(declaration["source_inputs"], "KSP frozen input")
    locked = _refs(lock["inputs"], "locked input")
    expected = {name: known[name] for name in record["source_inputs"]}
    _require(sources == expected and all(locked.get(n) == v for n, v in expected.items()),
             "unknown or changed source/patch/header/recipe in actual KSP inputs")
    _require(declaration["frontend_policy"] == record["frontend_policy"], "frontend policy differs from review")
    generated = _refs(declaration["generated"], "actual KSP output")
    _require(generated == _refs(record["generated_files"], "reviewed KSP output"), "actual KSP output differs from finite review")
    derivation = review["runtime_derivation"]
    _require(known[derivation["patch"]]["sha256"] == "sha256:" + derivation["patch_sha256"], "review patch identity differs")
    for base in derivation["base_files"]:
        name = "upstream/akinterop/" + base["path"]
        _require(sources[name] == dict(path=name, sha256="sha256:" + base["sha256"], size=base["size"]), "reviewed upstream base differs")
    if test:
        memory = review["test_runtime_derivation"]
        _require(sources[memory["patch"]]["sha256"] == "sha256:" + memory["patch_sha256"] and
                 sources[memory["added_source"]]["sha256"] == "sha256:" + memory["added_sha256"], "test codec derivation differs")
    return {"status": "bound", "variant": variant, "source_count": len(sources),
            "generated_count": len(generated), "original_inputs": list(expected.values()), "independent_patch_replay": False}


def _ksp(declaration, document):
    _require(declaration["authority"] == "actual CPF Kotlin KSP1 and akinterop 1.1.0; managed single-record profile" and
             declaration["typed_api_inferred"] is False, "KSP authority differs")
    generated = {}
    for value in declaration["generated"]:
        raw = value["text"].encode("utf-8")
        _require(file_digest(raw) == value["sha256"] and len(raw) == value["size"] and
                 value["path"] not in generated, "actual KSP text/hash differs")
        generated[value["path"]] = value["text"]
    for name, key in (("frontend-facts.json", "facts"), ("record-schema.json", "record_schema")):
        _require(json.loads(generated["resources/" + name]) == declaration[key], "KSP duplicated " + key + " differs")
    _require(generated["resources/record-export.d.ts"] == declaration["declaration"], "KSP declaration differs")
    _require(document("generated/contract/kotlin-ksp-facts.json") == declaration["facts"] and
             document("generated/contract/kotlin-record-schema.json") == declaration["record_schema"], "Source/KSP exported facts differ")
    for function in declaration["facts"]["functions"]:
        _require(function["source"]["path"] in {r["path"] for r in declaration["source_inputs"]}, "KSP function has foreign author source")


def _tool(command, name, candidate):
    identifier = "c07-" + (name if name in ("node", "typescript") else "kotlin-" + name)
    admitted = _one([t for t in candidate["toolchain"]["tools"] if t["id"] == identifier], "tool " + name)
    _require(command.get("tool") == name and type(command.get("exit_code")) is int and command["exit_code"] == 0 and
             command.get("tool_sha256") == admitted["sha256"], "unsuccessful/foreign tool " + name)


def _gradle(rows, task, declaration, candidate):
    command = _one([r for r in rows if r.get("tool") == "gradle"], "actual Gradle task")
    args = command["arguments"]
    _require(type(command["exit_code"]) is int and command["exit_code"] == 0 and len(args) == 13 and
             args[1:4] == ["-Xmx64m", "-Xms64m", "-Dorg.gradle.appname=gradle"] and
             args[4].startswith("-javaagent:/") and args[4].endswith("/lib/agents/gradle-instrumentation-agent-8.14.6.jar") and
             args[5] == "-jar" and args[7] == "-p" and args[8].startswith("/") and
             args[9:] == ["--no-daemon", "--console=plain", "--offline", task], "unreviewed Gradle task/flags")
    for name, field in (("cpf_java", "java_sha256"), ("gradle_cli", "cli_sha256")):
        tool = _one([t for t in candidate["toolchain"]["tools"] if t["id"] == "c07-kotlin-" + name], name)
        _require(command[field] == tool["sha256"] == declaration["tools"][name]["sha256"], "Gradle tool identity differs")
    parser = _one([r for r in rows if r.get("tool") == "node"], "actual KSP declaration parser")
    _tool(parser, "node", candidate)
    _require(len(parser["arguments"]) == 3 and parser["arguments"][1].endswith("/inputs/adapters/generators/arkts/read_kotlin_exports.cjs") and
             json.loads(parser["stdout"]) == declaration["descriptor"], "actual parser input/output differs")
    return args[8]


def _native_compile(rows, project, test, candidate):
    commands = [r for r in rows if r.get("tool") == "cpf_clang"]
    support = SUPPORT + (["provider_observer"] if test else [])
    units = [("helper-" + n, "inputs/runtime/src/nativeInterop/cinterop/cpp/src/" + n + ".cpp",
              "inputs/runtime/src/nativeInterop/cinterop/cpp/include") for n in HELPERS]
    units += [("support-" + n, "native-support/" + n + ".cpp", "native-support") for n in support]
    bootstrap = [("bootstrap", "native-bootstrap/bootstrap.cpp")]
    if test:
        bootstrap.append(("observer", "native-observer/bootstrap_observer.cpp"))
    _require(len(commands) == len(units) + len(bootstrap), "unknown/duplicate native compile unit")
    def command_for(source):
        row = _one([r for r in commands if project + "/" + source in r["arguments"]], "compile " + source)
        _tool(row, "cpf_clang", candidate)
        _require(row.get("environment") == {}, "unreviewed native compile environment")
        sysroot = _one([a for a in row["arguments"] if a.startswith("--sysroot=/")], "CPF sysroot")
        return row["arguments"][1:], sysroot
    for name, source, include in units:
        args, sysroot = command_for(source)
        base = project + "/native/obj/" + name
        expected = (["-DMADB_KN_TEST_SUPPORT=1"] if test and name.startswith("support-") else []) + ["--target=aarch64-linux-ohos", sysroot, "-std=c++17", "-fPIC", "-O2", "-DOHOS_PLATFORM", "-D__OHOS_API__=23",
                    "-I" + project + "/inputs/formal-api/include", "-I" + project + "/" + include,
                    "-MMD", "-MF", base + ".d", "-c", project + "/" + source, "-o", base + ".o"]
        _require(args == expected, "unreviewed native source/flags: " + name)
    for name, source in bootstrap:
        args, sysroot = command_for(source)
        base = project + "/native/bootstrap/" + name
        expected = (["-DMADB_KN_TEST_SUPPORT=1"] if test else []) + ["--target=aarch64-linux-ohos", sysroot, "-std=c++17", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror", "-D__OHOS_API__=23"]
        expected += ["-I" + project + "/" + d for d in ("inputs/formal-api/include", "native-support", "native-bootstrap", "native-observer")]
        expected += ["-MMD", "-MF", base + ".d", "-c", project + "/" + source, "-o", base + ".o"]
        _require(args == expected, "unreviewed bootstrap source/flags")
    archives = [r for r in rows if r.get("tool") == "cpf_ar"]
    _require(len(archives) == 2, "unknown/duplicate native archive")
    for label, names, archive in (("helper", HELPERS, "libnapi_bridge.a"), ("support", support, "libmadb_kn_executor.a")):
        row = _one([r for r in archives if project + "/native/lib/" + archive in r["arguments"]], archive)
        _tool(row, "cpf_ar", candidate)
        _require(row.get("environment") == {} and row["arguments"][1:] == ["rcs", project + "/native/lib/" + archive] +
                 [project + "/native/obj/" + label + "-" + n + ".o" for n in names], "archive member set/order differs")
    return len(commands)


def _linked(candidate, stages, objects, links, linked, symbols, project, data, inventory, record):
    _require(linked["identity"] == candidate["identity"], "Link identity differs")
    correction = _one(linked["linker_correction"], "CPF shared linker correction")
    before, after = correction["before"], correction["after"]
    removed = _one(correction["removed"], "known executable startup removal")
    _require(removed == project + "/konan/dependencies/sysroot-ohos-aarch64-6.0.2.640-04/usr/lib/aarch64-linux-ohos/Scrt1.o" and
             before.count(removed) == 1 and after == [v for v in before if v != removed] and "-shared" in after,
             "unreviewed CPF shared correction")
    normalized = [re.sub(r"/(konan_temp|included)[0-9]+/", r"/\1{temporary}/", arg.replace(project, "{project}")) for arg in after]
    _require(normalized == record["linker_arguments"], "actual CPF linker arguments differ from finite review")
    for archive, suffix in (("libnapi_bridge.a", "runtime/build/classes/kotlin/ohosArm64/main/cinterop/runtime-cinterop-interop/default/targets/ohos_arm64/included/"),
                            ("libmadb_kn_executor.a", "probe/build/classes/kotlin/ohosArm64/main/cinterop/probe-cinterop-executor/default/targets/ohos_arm64/included/")):
        _require(after.count(project + "/" + suffix + archive) == 1 and "objects/" + archive in objects, "Link omits compiled cinterop archive")
    provider = "libmadb_kotlin_owned_runtime.so"
    _require(after.count("--soname=" + provider) >= 1 and
             len([v for v in after if v.startswith(project + "/tmp/konan_temp") and v.endswith("/" + provider + ".o")]) == 1,
             "actual Kotlin shared object input missing/ambiguous")
    bootstrap = _one([r for r in links if r.get("tool") == "cpf_clang" and "-shared" in r.get("arguments", [])], "bootstrap native link")
    _tool(bootstrap, "cpf_clang", candidate)
    args = bootstrap["arguments"]
    expected_objects = [project + "/native/bootstrap/bootstrap.o"] + ([project + "/native/bootstrap/observer.o"] if candidate.get("companion") else [])
    _require([a for a in args if a.endswith(".o")] == expected_objects and
             args.count("-Wl,-soname,lib" + candidate["module"] + ".so") == 1 and args.count("-o") == 1 and
             args[args.index("-o") + 1] == project + "/artifacts/lib" + candidate["module"] + ".so", "bootstrap link object/output differs")
    sysroot = _one([a for a in args if a.startswith("--sysroot=/")], "bootstrap link sysroot")
    library = _one([a for a in args if a.startswith("-L/")], "bootstrap CPF runtime directory")
    expected_args = ["--target=aarch64-linux-ohos", sysroot, "-shared", *expected_objects, *record["bootstrap_wrap_flags"], library,
                     "-lace_napi.z", "-ldl", "-Wl,--no-undefined", "-Wl,-soname,lib" + candidate["module"] + ".so",
                     "-o", project + "/artifacts/lib" + candidate["module"] + ".so"]
    _require(args[1:] == expected_args and bootstrap.get("environment") == {}, "unreviewed bootstrap link flags/environment")
    output_refs = _refs(stages["link"]["outputs"], "Link output")
    linked_outputs = _refs(linked["outputs"], "Kotlin Link output")
    auxiliary = {"kotlin-napi-coverage.json"} if candidate.get("companion") else set()
    _require({n for n in linked_outputs if not n.startswith("native/")} == auxiliary, "unknown Kotlin Link auxiliary output")
    for name in auxiliary:
        _require(linked_outputs[name] == output_refs[name] == inventory[name], "NAPI coverage output differs")
        data(name)
    dsos = {n: v for n, v in linked_outputs.items() if n.startswith("native/")}
    expected = {"native/lib" + candidate["module"] + ".so", "native/" + provider, "native/libc++_shared.so"}
    _require(set(dsos) == expected, "Kotlin linked ELF set differs")
    for name, reference in dsos.items():
        raw = data(name)
        _require(reference == output_refs[name] == inventory[name] and raw.startswith(b"\x7fELF") and
                 candidate["native_members"]["package/libs/arm64-v8a/" + Path(name).name] == raw, "linked ELF/candidate/HAR bytes differ")
    _require(len(symbols["libraries"]) == 2 and {a["path"] for a in symbols["libraries"]} == set(record["loader_symbols"]), "ELF loader library set differs")
    if not candidate.get("companion"):
        test_only = {"madb_kn_owned_thread_probe", "madb_kn_executor_test_command", "madb_kn_executor_test_cleanup_release", "madb_kn_lifecycle_test_command"}
        _require(all(not (test_only & set(a["exports"])) for a in symbols["libraries"]), "ordinary ELF exposes test thread probes")
    for library in symbols["libraries"]:
        _require(library["required_loader_symbols"] == record["loader_symbols"][library["path"]] and
                 set(library["required_loader_symbols"]) <= set(library["exports"]), "actual owner/loader exports differ")
        _require(library["sha256"] == dsos["native/" + library["path"]]["sha256"] and
                 library["soname"] == library["path"], "ELF symbol receipt identity differs")
    return {"status": "bound", "native_artifacts": list(dsos.values()), "compile_outputs": list(objects.values())}


def verify_kotlin_source_review(candidate, *, review_id="c07"):
    """Additional static necessary condition; it never supplies live-thread evidence."""
    result = {"status": "blocked", "scope": "reviewed Kotlin source and public C04 build receipts; not runtime execution",
              "thread_witness": {"status": "not-assessed", "scope": "static-only", "reason": "The controller must verify same-candidate live/final thread21 and owner-loop heartbeat. Source binding does not establish runtime thread liveness; public110/controls31 alone remain insufficient."}}
    try:
        _require(candidate["route"] == "kotlin", "not the Kotlin route")
        review_path = select_source_review(review_id, "kotlin", REVIEW)
        review = read_json(review_path)
        result.update(inventory_sha256=file_digest(review_path.read_bytes()), candidate_digest=candidate["manifest"]["candidate_digest"],
                      producer_revision=candidate["provenance"]["producer_revision"], limits=review["limits"])
        manifest, root = candidate["manifest"], candidate["root"]
        inventory = {}
        for collection in ("files", "dependencies", "build_evidence"):
            for name, value in _refs(manifest[collection], "candidate " + collection).items():
                _require(name not in inventory or inventory[name] == value, "conflicting candidate reference")
                inventory[name] = value
        used = set()
        def data(name):
            _require(name in inventory, "unpublished candidate evidence: " + name)
            raw = (root / name).read_bytes()
            _require(len(raw) == inventory[name]["size"] and file_digest(raw) == inventory[name]["sha256"], "changed evidence: " + name)
            used.add(name)
            return raw
        def document(name):
            return json.loads(data(name))
        declaration = document("declarations.json")["kotlin"]
        lock = document("madb.lock")
        try:
            result["source_review"] = _review_sources(candidate, review, declaration, lock)
        except ERRORS as error:
            result["source_review"] = {"status": "blocked", "reason": str(error)}
        _ksp(declaration, document)
        for name, declared in declaration["tools"].items():
            identifier = "c07-" + (name if name in ("node", "typescript") else "kotlin-" + name)
            admitted = _one([t for t in candidate["toolchain"]["tools"] if t["id"] == identifier], "KSP tool " + name)
            _require(declared["sha256"] == admitted["sha256"], "KSP/admitted tool identity differs")
        selected = candidate["toolchain"]["kotlin"]
        _require(declaration["closure"]["maven"] == selected["dependency_lock"] and
                 {k: v for k, v in declaration["closure"]["trees"].items() if k != "maven"} == selected["trees"],
                 "KSP dependency/compiler tree closure differs")
        stages = {}
        for entry in manifest["build_evidence"]:
            stage = document(entry["path"])
            phase = stage["phase"]
            _require(phase in ("compile", "link") and phase not in stages and stage["schema"] == "madb.build-evidence/1" and
                     stage["status"] == "passed" and type(stage["exit_code"]) is int and stage["exit_code"] == 0 and
                     stage["generation_id"] == manifest["generation_id"] and stage["profile_digest"] == manifest["selector"]["profile_digest"] and
                     stage["input_digest"] == candidate["provenance"]["input_digest"], "foreign/unsuccessful Build receipt")
            _require(_refs(stage["logs"], "Build log") == {"logs/" + phase + "-commands.json": inventory["logs/" + phase + "-commands.json"]}, "Build log binding differs")
            stages[phase] = stage
        _require(set(stages) == {"compile", "link"}, "incomplete Build phases")
        rows, links = document("logs/compile-commands.json"), document("logs/link-commands.json")
        project = _gradle(rows, ":probe:kspKotlinOhosArm64", declaration, candidate)
        count = _native_compile(rows, project, candidate.get("companion", False), candidate)
        linkproject = _gradle(links, ":probe:linkReleaseSharedOhosArm64", declaration, candidate)
        outputs = _refs(stages["compile"]["outputs"], "Compile output")
        objects = {n: v for n, v in outputs.items() if n.startswith("objects/")}
        expected = {"objects/kotlin-bootstrap.o", "objects/libmadb_kn_executor.a", "objects/libnapi_bridge.a"}
        if candidate.get("companion"):
            expected.add("objects/kotlin-observer.o")
        _require(set(objects) == expected and set(outputs) == expected | {"kotlin-compile.json"}, "unknown/missing Compile outputs")
        linked, symbols = document("kotlin-link.json"), document("kotlin-symbols.json")
        for name in ("kotlin-link.json", "kotlin-symbols.json"):
            _require(_refs(stages["link"]["outputs"], "Link output")[name] == inventory[name], "Link receipt bytes differ")
        result["build_receipts"] = _linked(candidate, stages, objects, links, linked, symbols, linkproject, data, inventory, review["variants"]["test" if candidate.get("companion") else "ordinary"])
        result["build_receipts"]["native_compile_units"] = count
        if candidate.get("companion"):
            known = _refs(review["source_files"], "reviewed source")
            for mapping in review["test_public_contracts"]:
                raw = data(mapping["generated"])
                source = known[mapping["source"]]
                _require(len(raw) == source["size"] and file_digest(raw) == source["sha256"], "public thread contract differs from frozen reviewed source")
        actual = document("kotlin-compile.json")
        _require(outputs["kotlin-compile.json"] == inventory["kotlin-compile.json"] and actual["identity"] == candidate["identity"] and
                 actual["kotlin"] == declaration, "actual Compile KSP/identity differs from Source")
        _require(result["source_review"]["status"] == "bound", "independent source review alignment is blocked")
        result.update(status="bound", source_derivation=review["runtime_derivation"],
                      test_source_derivation=review["test_runtime_derivation"] if candidate.get("companion") else None,
                      review_notes=review["review_notes"], independent_patch_replay=False)
        result["inputs"] = [inventory[n] for n in sorted(used)]
    except ERRORS as error:
        result["reason"] = str(error)
    return result


def verify_kotlin_profile_pair(ordinary, companion, *, review_id="c07"):
    """Bind the existing ordinary/test profile pair; runtime reports are caller-owned."""
    result = {"status": "blocked", "scope": "same reviewed Kotlin source/profile pair, not ordinary runtime success"}
    try:
        _require(ordinary["route"] == companion["route"] == "kotlin" and
                 ordinary.get("companion") is False and companion.get("companion") is True,
                 "ordinary/test Kotlin pair roles differ")
        _require(ordinary["profile"]["id"] + "-test" == companion["profile"]["id"] and
                 ordinary["provenance"]["producer_revision"] == companion["provenance"]["producer_revision"],
                 "ordinary/test profile pair or producer revision differs")
        bindings = [verify_kotlin_source_review(c, review_id=review_id) for c in (ordinary, companion)]
        _require(all(b["status"] == "bound" for b in bindings), "ordinary/test reviewed source/build binding is incomplete")
        review_path = select_source_review(review_id, "kotlin", REVIEW)
        review = read_json(review_path)
        _require(bindings[0]["inventory_sha256"] == bindings[1]["inventory_sha256"] == file_digest(review_path.read_bytes()), "source review changed during profile pairing")
        common = set(review["variants"]["ordinary"]["source_inputs"]) & set(review["variants"]["test"]["source_inputs"])
        sources = [_refs(b["source_review"]["original_inputs"], "bound source") for b in bindings]
        _require(common and all(sources[0][n] == sources[1][n] for n in common), "ordinary/test common source closure differs")
        result.update(status="bound", producer_revision=ordinary["provenance"]["producer_revision"],
                      ordinary_candidate_digest=ordinary["manifest"]["candidate_digest"],
                      companion_candidate_digest=companion["manifest"]["candidate_digest"],
                      profiles=[c["profile"]["id"] for c in (ordinary, companion)],
                      common_inputs=[sources[0][n] for n in sorted(common)],
                      inventory_sha256=bindings[0]["inventory_sha256"])
    except ERRORS as error:
        result["reason"] = str(error)
    return result
