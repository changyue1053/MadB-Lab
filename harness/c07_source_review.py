"""Finite Lab source-review alignment, separate from recorded build consistency.

The review is maintained in Lab, never selected or supplied by a candidate.
Current public candidates ship source references rather than original source
bytes; this check cannot and does not claim independent patch replay.
"""
from pathlib import Path
import json
import re

from candidate import CandidateError, file_digest, read_json

REVIEW = Path(__file__).resolve().parents[1] / "expected/c07/route-ownership-review.json"


def _require(condition, message):
    if not condition:
        raise CandidateError("ArtifactMismatch", "source review: " + message)


def _refs(values, label):
    result = {}
    for value in values:
        name = value["path"]
        _require(name not in result and isinstance(name, str) and not name.startswith("/") and
                 all(p not in ("", ".", "..") for p in name.split("/")) and
                 re.fullmatch(r"sha256:[0-9a-f]{64}", value["sha256"]) and
                 type(value["size"]) is int and value["size"] >= 0, "invalid/duplicate " + label)
        result[name] = {k: value[k] for k in ("path", "sha256", "size")}
    return result


def _one(values, label):
    _require(len(values) == 1, "missing/ambiguous " + label)
    return values[0]


def _compile(unit, rows, locked, generated, reviewed, tool):
    name, source = unit["name"], unit["source"]
    command = _one([row for row in rows if row.get("tool") in ("clang", "clangxx") and
                    isinstance(row.get("arguments"), list) and "-c" in row["arguments"] and any(str(a).endswith("/work/objects/" + name + ".o") for a in row["arguments"])], name + " compiler command")
    tool(command, "clang" if unit["language"] == "c" else "clangxx")
    args = command["arguments"]
    _require(args.count("-c") == args.count("-o") == 1, name + " compile mode")
    path, output = args[args.index("-c") + 1], args[args.index("-o") + 1]
    suffix = "/inputs/" + source
    _require(path.endswith(suffix) and output.endswith("/work/objects/" + name + ".o"), name + " actual source/output")
    inputs = path[:-len(source)]
    work = output[:-len("objects/" + name + ".o")]
    sysroot = _one([a for a in args if a.startswith("--sysroot=")], name + " Native SDK sysroot")
    includes = ["derived/native/include", "sdk/arkts/native-runtime/include"]
    if any(r.get("unit") == "runtime-ffi" for r in rows):
        includes.append("derived/native/rust-raw")
    includes.append("generated/native")
    expected = ["--target=aarch64-linux-ohos23.0.0", sysroot, "-O2", "-fPIC", "-fvisibility=hidden",
                "-g", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-Werror=date-time",
                "-ffile-prefix-map=" + inputs.rstrip("/") + "=/madb/inputs",
                "-ffile-prefix-map=" + work.rstrip("/") + "=/madb/work", "-fdebug-compilation-dir=/madb/work",
                "-std=" + ("c17" if unit["language"] == "c" else "c++17")]
    if unit["language"] == "cpp":
        expected.append("-fvisibility-inlines-hidden")
    for directory in includes:
        expected.extend(["-I", inputs + directory])
    expected.extend(["-MD", "-MT", "madb-object", "-MF", work + "logs/" + name + ".d", "-c", path, "-o", output])
    _require(args[1:] == expected, name + " compiler flags include unreviewed source semantics")
    deps = _one([r for r in rows if r.get("kind") == "actual-compiler-dependencies" and r.get("unit") == name], name + " actual dependencies")
    frozen = _refs([r for r in deps["dependencies"] if r.get("origin") == "frozen-input"], name + " frozen dependency")
    _require(set(unit["required_dependencies"]) <= set(frozen), name + " required dependency was not actually compiled")
    for path, value in frozen.items():
        _require(value == locked.get(path, generated.get(path)), name + " dependency differs from frozen source: " + path)
        _require(path in reviewed or path == "generated/native/identity.generated.hpp", name + " unreviewed compiler dependency: " + path)
        if path in reviewed:
            _require(value == reviewed[path], name + " dependency differs from review: " + path)
    return {"unit": name, "source": frozen[source], "dependencies": list(frozen.values())}


def _identity(candidate, data, test):
    identity = candidate["identity"]
    constants = {"GatewayAbi": identity["abi_digest"][7:], "GatewayProfile": identity["profile_digest"][7:],
                 "GatewayBuild": identity["build_id"][7:], "GatewayIdentity": identity["expected_identity"],
                 "GatewayRouteIdentity": candidate["route"] + "/" + identity["expected_identity"],
                 "GatewayModuleName": candidate["module"]}
    factory = "mp_" + candidate["route"]
    expected = '#pragma once\n#include "provider_abi.h"\n'
    if test:
        expected += '#include "memory_hook.h"\n'
    expected += "namespace gateway {\n" + "".join("inline constexpr const char* " + k + "=" + json.dumps(v) + ";\n" for k, v in constants.items())
    expected += "inline constexpr auto GatewayProviderCreate = ::" + factory + "_create;\n"
    if test:
        expected += "inline constexpr auto GatewayProviderMemoryBind = ::" + factory + "_test_memory_bind;\n"
    _require(data("generated/native/identity.generated.hpp") == (expected + "}\n").encode(), "gateway factory header has unreviewed content")


def _rust(record, candidate, locked, rows, links, objects, document, tool, upstream):
    declaration = document("declarations.json")["rust"]
    linked, symbols = document("rust-link.json"), document("rust-symbols.json")
    inputs = _refs(declaration["inputs"], "Rust author input")
    authors = [n for n in record["original_inputs"] if n.startswith("sdk/rust/arkts-bridge/")]
    authors += ["sdk/rust/arkts-provider/src/lib.rs"]
    _require(set(inputs) == set(authors) and all(inputs[n] == locked[n] for n in authors), "Rust actual macro author inputs differ from reviewed source")
    test = record["variant"] == "test"
    _require(candidate["toolchain"]["rust"]["test_support"] is test, "Rust toolchain cfg differs from source variant")
    _require(_refs(declaration["frontend_evidence"]["upstream_sources"], "actual Rust frontend source") ==
             _refs(upstream, "reviewed Rust frontend source"), "unreviewed Rust frontend upstream source")
    rustc = _one([t for t in candidate["toolchain"]["tools"] if t["id"] == "c07-rustc"], "Rust compiler identity")
    _require(declaration["tools"]["rustc"]["sha256"] == rustc["sha256"], "Rust macro compiler differs from admitted toolchain")
    _require(declaration["test_support"] is test and declaration["typed_api_inferred"] is False and
             linked["actual_macro"] == declaration["macro"] and symbols["frontend"]["macro"] == declaration["frontend_evidence"],
             "Rust cfg/macro/frontend receipts disagree")
    packages = declaration["resolved_packages"]
    for name, features in (("madb-arkts-bridge", ["default", "test-support"] if test else ["default"]),
                           ("napi-ohos", ["napi1", "napi2", "napi3"]),
                           ("napi-sys-ohos", ["napi" + str(n) for n in range(1, 9)])):
        package = _one([p for p in packages if p["name"] == name], name + " resolved features")
        _require(sorted(package["features"]) == features, "Rust resolved features differ: " + name)
    exports = declaration["macro"]["descriptor"]["exports"]
    _require([[e["name"], e["arity"]] for e in exports] == record["methods"] and
             all(e["rawReturn"] == "unknown" and len(e["parameters"]) == e["arity"] and
                 all(p["rawType"] == "unknown" for p in e["parameters"]) for e in exports), "Rust actual macro surface differs from reviewed raw bridge")
    for commands, name, verb in ((rows, "cargo", "check"), (links, "ohrs", "build")):
        command = _one([r for r in commands if r.get("tool") == name and verb in r.get("arguments", [])], "Rust " + verb)
        args = command["arguments"]
        features = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--features"]
        _require(features == (["test-support"] if test else []) and not any(a in args for a in ["--all-features", "--no-default-features"]), "Rust command cfg selection differs")
        environment = command.get("explicit_environment", command.get("environment", {}))
        _require(not any(k in environment for k in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS")), "unreviewed Rust cfg environment")
        _require(not any(a.startswith(("--cfg", "--config", "--features=")) for a in args), "unreviewed Rust cfg argument")
        if name == "ohrs":
            flags = environment.get("CARGO_RUSTFLAGS", "").split("\x1f")
            _require(len(flags) == 3 and flags[:2] == ["-Clink-arg=--target=aarch64-linux-ohos23.0.0", "-Clink-arg=-Wl,--build-id=sha1"] and
                     re.fullmatch(r"--remap-path-prefix=/[^\r\n]+=/madb/rust", flags[2]), "unreviewed Rust native compiler flags")
        _require(environment.get("MADB_BUILD_PHASE") == ("metadata" if name == "cargo" else "native"), "Rust actual compiler phase differs")
    archive = _one([r for r in rows if r.get("tool") == "ar"], "actual gateway archive")
    tool(archive, "ar")
    arguments = archive["arguments"]
    members = [a.split("/work/")[-1] for a in arguments[3:]]
    _require(arguments[1] == "crsD" and arguments[2].endswith("/work/objects/libmadb_arkts_gateway.a") and
             sorted(members) == sorted("objects/" + u["name"] + ".o" for u in record["units"]), "Rust archive does not contain exactly reviewed native units")
    _require(linked["source_archive_sha256"] == objects["objects/libmadb_arkts_gateway.a"]["sha256"], "Rust actual archive differs")
    return {"provider_inputs": list(inputs.values()), "cfg_test_support": test, "macro_exports": len(exports),
            "scope": "Frozen Rust author refs plus actual cfg/macro/import/archive receipts; no Rust source depfile is published. Frontend evidence is separate from gateway dynamic counters."}


def verify_source_review(candidate, lock, rows, links, objects, inventory, data, document, tool):
    """Return blocked unless both approved review and complete actual chain agree."""
    result = {"status": "blocked", "scope": "reviewed source hash alignment, not candidate-only source replay or target execution"}
    try:
        review_bytes = REVIEW.read_bytes()
        review = read_json(REVIEW)
        result["inventory_sha256"] = file_digest(review_bytes)
        result["producer_revision"] = candidate["provenance"]["producer_revision"]
        _require(review["status"] == "reviewed" and review["producer_revision"] == result["producer_revision"], "independent review/final producer revision is not approved")
        route = candidate["route"]
        variant = "test" if candidate.get("companion", False) else "ordinary"
        # Admitted candidates retain the exact profile; callers cannot relabel cfg.
        _require(candidate["profile"]["id"].endswith("-test") == (variant == "test"), "companion/profile variant differs")
        record = _one([r for r in review["records"] if r["route"] == route and r["variant"] == variant], "reviewed route/variant")
        known = _refs(review["source_files"], "reviewed original")
        reviewed = {n: known[n] for n in record["original_inputs"]}
        reviewed.update(_refs(record["references"], "reviewed derived/generated"))
        locked = _refs(lock["inputs"], "locked input")
        for path in record["original_inputs"] + record["derived_inputs"]:
            _require(locked.get(path) == reviewed[path], "unreviewed or changed frozen source: " + path)
            if path in inventory:
                _require(file_digest(data(path)) == reviewed[path]["sha256"], "shipped source bytes differ: " + path)
        for path in record["generated_inputs"]:
            _require(inventory.get(path) == reviewed[path], "generated native input differs from reviewed bytes: " + path)
            data(path)
        if variant == "test":
            composition = document("generated/contract/composition.json")
            _require(composition["route"] == route and composition["variant"] == variant, "composition route/variant differs")
            for field in ("original_inputs", "derived_inputs"):
                refs = _refs(composition[field], "composition " + field)
                # Additional reviewed compiler/generator files live in madb.lock.
                expected = set(record[field]) if field == "derived_inputs" else set(record[field]) - {n for n in record[field] if n.startswith("adapters/") or n.startswith("sdk/rust/arkts-bridge/")}
                _require(expected <= set(refs) and all(v == locked.get(n) and v == reviewed.get(n) for n, v in refs.items()), "original/derived composition closure differs")
            for derivation in record["derivations"]:
                _require(all(p in locked for p in [derivation[k] for k in ("original", "patch", "baseline", "result")]) and
                         locked[derivation["original"]]["sha256"] == derivation["base_sha256"] and
                         locked[derivation["result"]]["sha256"] == derivation["result_sha256"], "reviewed original/patch/base/result relation differs")
        _identity(candidate, data, variant == "test")
        units = record["units"]
        _require(sum("-c" in r.get("arguments", []) for r in rows if r.get("tool") in ("clang", "clangxx")) == len(units), "unknown or duplicated actual native compile unit")
        _require(sorted(r["unit"] for r in rows if r.get("kind") == "actual-compiler-dependencies") == sorted(u["name"] for u in units), "actual dependency unit set differs")
        bound = [_compile(u, rows, locked, inventory, reviewed, tool) for u in units]
        for unit in bound:
            path = "objects/" + unit["unit"] + ".o"
            _require(path in objects, "reviewed unit lacks actual compiler object: " + path)
            unit["object"] = objects[path]
        if route == "rust":
            result["rust_frontend"] = _rust(record, candidate, locked, rows, links, objects, document, tool, review["rust_frontend_upstream"])
        else:
            link = _one([r for r in links if "-shared" in r.get("arguments", [])], "native link")
            linked = [a.split("/inputs/")[-1] for a in link["arguments"] if a.endswith(".o")]
            _require(sorted(linked) == sorted("objects/" + u["name"] + ".o" for u in units), "link must consume exactly reviewed objects")
        result.update(status="bound", route=route, variant=variant, units=bound,
                      original_inputs=[reviewed[n] for n in record["original_inputs"]],
                      derived_inputs=[reviewed[n] for n in record["derived_inputs"]],
                      derivations=record["derivations"], independent_patch_replay=False,
                      review_notes=review["review_notes"], limits=[review["replay_scope"], "Object hashes are build receipts; object bytes are not shipped. Target scenarios remain required."])
    except (CandidateError, OSError, KeyError, TypeError, ValueError, IndexError) as error:
        result["reason"] = str(error)
    return result
