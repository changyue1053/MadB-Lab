"""C07 public HAR admission using the existing public candidate verifier."""
from pathlib import Path
import json
import re
import tarfile
from candidate import CandidateError, file_digest, logical_path, read_json, verify_public_candidate
from c07_contract import ORDINARY_EXPORTS, ROUTES, TARGET, requirement
from c07_abi import verify_abi


def har_members(path):
    """Inspect bounded tar members without extracting or following links."""
    output = {}
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = str(logical_path(member.name.rstrip("/")))
            if member.isdir():
                continue
            if not member.isfile() or name in output or member.size > 64 * 1024 * 1024:
                raise CandidateError("ArtifactMismatch", "HAR has a link, duplicate, special or oversized member")
            total += member.size
            if total > 128 * 1024 * 1024 or len(output) >= 4096:
                raise CandidateError("ArtifactMismatch", "HAR exceeds bounded inspection budget")
            data = archive.extractfile(member).read()
            if len(data) != member.size:
                raise CandidateError("ArtifactMismatch", "truncated HAR member")
            output[name] = data
    return output



def native_inventory(files):
    """Catch renamed ELF and versioned libraries anywhere before basename mapping."""
    native = {}
    basenames = set()
    for name, data in files.items():
        if not (data.startswith((b"\x7fELF", b"!<arch>\n")) or re.search(r"\.so(?:\.|$)", Path(name).name)):
            continue
        basename = Path(name).name
        if basename in basenames:
            raise CandidateError("ArtifactMismatch", "duplicate native basename: " + basename)
        basenames.add(basename)
        native[name] = data
    return native


def ordinary_public_entry(members, package):
    """Accept only the closed compiler-emitted seven-name re-export grammar.

    This deliberately is not a general TypeScript parser. New public syntax must
    be reviewed, rather than silently ignoring another export or public subpath.
    """
    if "exports" in package or "typesVersions" in package:
        raise CandidateError("ArtifactMismatch", "unreviewed public HAR subpath or type mapping")
    try:
        text = members["package/Index.d.ets"].decode("utf-8")
    except (KeyError, UnicodeError) as error:
        raise CandidateError("ArtifactMismatch", "HAR lacks a UTF-8 public declaration entry") from error
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text).strip()
    match = re.fullmatch(r'export\s*\{\s*([A-Za-z0-9_,\s]+)\s*\}\s*from\s*["\'](\./[A-Za-z0-9_/-]+)["\']\s*;', text)
    if not match:
        raise CandidateError("ArtifactMismatch", "ordinary public entry is not a closed named re-export")
    names = [name.strip() for name in match[1].split(",")]
    if len(names) != len(ORDINARY_EXPORTS) or set(names) != ORDINARY_EXPORTS:
        raise CandidateError("ArtifactMismatch", "ordinary public exports differ from exactly seven declared names")
    target = str(logical_path(match[2][2:]))
    if "package/" + target + ".d.ets" not in members:
        raise CandidateError("ArtifactMismatch", "public entry target declaration is missing")
    return names


def identity_values(data, *, binary=False, allow_parser_prefix=False):
    """A narrow artifact-format consistency check, not machine-code semantics."""
    pattern = rb"madb-arkts/1:[0-9a-f]{64}:[0-9a-f]{64}:[0-9a-f]{64}"
    values = re.findall(pattern + (rb"(?=\x00)" if binary else rb"(?![0-9a-f])"), data)
    parser_prefixes = data.count(b"madb-arkts/1:\x00") if allow_parser_prefix else 0
    if data.count(b"madb-arkts/1:") != len(values) + parser_prefixes:
        raise CandidateError("ArtifactMismatch", "malformed embedded ArkTS identity")
    return set(values)


def verify_embedded_identity(identity, route, module, facade, header, members):
    expected = identity["expected_identity"].encode("ascii")
    facade = re.sub(rb"//[^\n]*", b"", re.sub(rb"/\*.*?\*/", b"", facade, flags=re.S))
    if identity_values(facade) != {expected}:
        raise CandidateError("ArtifactMismatch", "generated facade identity differs from candidate")
    facade_values = re.findall(rb'const\s+EXPECTED_IDENTITY\s*:\s*string\s*=\s*"([^"\r\n]+)"\s*;', facade)
    if facade_values != [expected]:
        raise CandidateError("ArtifactMismatch", "generated facade lacks its unique declared identity constant")
    if route == "kotlin":
        # Kotlin emits a public binding document, not the C++ gateway header.
        try:
            binding = json.loads(header)
        except (UnicodeError, ValueError) as error:
            raise CandidateError("ArtifactMismatch", "invalid Kotlin binding identity document") from error
        if binding.get("authority") != "actual KSP facts and emitted declaration; bootstrap has separate authored ABI" or binding.get("identity") != identity:
            raise CandidateError("ArtifactMismatch", "generated Kotlin binding identity differs from candidate")
    else:
        header = re.sub(rb"//[^\n]*", b"", re.sub(rb"/\*.*?\*/", b"", header, flags=re.S))
        if identity_values(header) != {expected}:
            raise CandidateError("ArtifactMismatch", "generated header identity differs from candidate")
        constants = dict(re.findall(rb'inline\s+constexpr\s+const\s+char\*\s+(Gateway[A-Za-z]+)\s*=\s*"([^"\r\n]*)"\s*;', header))
        wanted = {b"GatewayIdentity": expected, b"GatewayRouteIdentity": route.encode() + b"/" + expected,
                  b"GatewayModuleName": module.encode(), b"GatewayAbi": identity["abi_digest"][7:].encode(),
                  b"GatewayProfile": identity["profile_digest"][7:].encode(), b"GatewayBuild": identity["build_id"][7:].encode()}
        for name, value in wanted.items():
            if constants.get(name) != value or len(re.findall(rb'\b' + name + rb'\s*=', header)) != 1:
                raise CandidateError("ArtifactMismatch", "generated header constant differs: " + name.decode())
    bytecode = {name: data for name, data in members.items() if name.endswith(".abc")}
    if set(bytecode) != {"package/ets/modules.abc"} or identity_values(bytecode["package/ets/modules.abc"], binary=True) != {expected}:
        raise CandidateError("ArtifactMismatch", "actual HAR bytecode identity is missing, ambiguous or differs")
    dsos = ["package/libs/arm64-v8a/lib" + module + ".so"]
    if route == "kotlin":
        dsos.append("package/libs/arm64-v8a/libmadb_kotlin_owned_runtime.so")
    for name in dsos:
        if identity_values(members[name], binary=True, allow_parser_prefix=True) != {expected}:
            raise CandidateError("ArtifactMismatch", "actual SDK DSO identity differs: " + name)
    expected_routes = set() if route == "kotlin" else {route.encode() + b"/" + expected}
    for name in dsos:
        routes = set(re.findall(rb"[A-Za-z0-9_-]+/madb-arkts/1:[0-9a-f]{64}:[0-9a-f]{64}:[0-9a-f]{64}(?=\x00)", members[name]))
        if routes != expected_routes:
            raise CandidateError("ProfileMismatch", "actual SDK DSO route identity differs: " + name)
    # Kn has no C-gateway route literal. Its independently checked profile digest,
    # formal module and both DSO identities bind this route instead.
    return {"expected_identity": identity["expected_identity"], "bytecode": list(bytecode), "sdk_dsos": dsos,
            "route_binding": "profile/module/two SDK DSOs" if route == "kotlin" else "profile/module/embedded route prefix",
            "scope": "three-way declared/embedded byte consistency; not arbitrary machine-code semantic proof"}


def verify_candidate(root: Path, route: str, *, companion=False):
    if route not in ROUTES:
        raise CandidateError("ProfileMismatch", "unknown C07 route")
    policy = ROUTES[route]
    candidate = verify_public_candidate(root, allowed_routes={policy["route"]}, identity_format="arkts")
    abi_binding = verify_abi(candidate, route, companion=companion)
    profile, manifest = candidate["profile"], candidate["manifest"]
    profile_id = f"c07-{route}-arkts-aarch64-ohos23" + ("-test" if companion else "")
    scope = requirement(profile_id)
    if profile["id"] != profile_id or manifest["selector"]["target"] != TARGET:
        raise CandidateError("ProfileMismatch", "C07 profile/target differs from independent scope")
    if profile["consumer"] != {"language": "arkts", "runtime": "harmonyos"} or profile["provider"]["language"] != route:
        raise CandidateError("ProfileMismatch", "C07 direct consumer/provider language differs")
    if profile["artifact_kind"] != "har" or profile["deployment_target"] != "API23":
        raise CandidateError("ProfileMismatch", "C07 requires the declared API23 HAR profile")
    if set(manifest["required_cases"]) != set(scope["required_cases"]):
        raise CandidateError("ArtifactMismatch", "candidate required cases differ from independent ordinary/companion allocation")
    inventory = {item["path"]: item for collection in ("files", "dependencies", "build_evidence")
                 for item in manifest[collection]}
    archives = [name for name in inventory if name.endswith(".har")]
    if len(archives) != 1:
        raise CandidateError("ArtifactMismatch", "candidate must contain exactly one public HAR")
    members = har_members(candidate["root"] / archives[0])
    package = json.loads(members["package/oh-package.json5"])
    module = package.get("name")
    if not isinstance(module, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", module):
        raise CandidateError("ArtifactMismatch", "unsafe or absent public HAR module name")
    if package.get("scripts"):
        raise CandidateError("ArtifactMismatch", "HAR install scripts are not permitted")
    expected_module = policy["module"] + ("test" if companion else "")
    if module != expected_module:
        raise CandidateError("ProfileMismatch", "public module does not match its selected direct route")
    for name, target in package.get("dependencies", {}).items():
        if not name.endswith(".so") or not isinstance(target, str) or not target.startswith("file:./"):
            raise CandidateError("ArtifactMismatch", "HAR dependency is not an internal native type package")
        relative = str(logical_path(target.removeprefix("file:./")))
        manifest_path = "package/" + relative + "/oh-package.json5"
        if manifest_path not in members:
            raise CandidateError("ArtifactMismatch", "HAR internal native type package is missing")
        internal = json.loads(members[manifest_path])
        if internal.get("name") != name or internal.get("scripts") or internal.get("dependencies"):
            raise CandidateError("ArtifactMismatch", "HAR native type package is not closed")
        types = str(logical_path(internal.get("types", "").removeprefix("./")))
        if "package/" + relative + "/" + types not in members:
            raise CandidateError("ArtifactMismatch", "HAR native type declaration is missing")
    native = native_inventory(members)
    candidate_native = native_inventory({name: (candidate["root"] / name).read_bytes() for name in inventory})
    if any(name != "native/" + Path(name).name or not name.endswith(".so") for name in candidate_native):
        raise CandidateError("ArtifactMismatch", "native object is outside its closed native inventory")
    expected = {"package/libs/arm64-v8a/" + Path(name).name: data for name, data in candidate_native.items()}
    if not expected or native != expected or "package/libs/arm64-v8a/libc++_shared.so" not in native:
        raise CandidateError("ArtifactMismatch", "HAR native members differ from exact public native inventory")
    if any(not data.startswith(b"\x7fELF") or data[4:6] != b"\x02\x01" or int.from_bytes(data[18:20], "little") != 183 for data in native.values()):
        raise CandidateError("AbiMismatch", "HAR native member is not ELF64 little-endian AArch64")
    expected_libraries = {"package/libs/arm64-v8a/lib" + module + ".so", "package/libs/arm64-v8a/libc++_shared.so"}
    if route == "kotlin":
        expected_libraries.add("package/libs/arm64-v8a/libmadb_kotlin_owned_runtime.so")
    if set(native) != expected_libraries:
        raise CandidateError("ArtifactMismatch", "HAR has an undeclared route runtime or misses its exact native module")
    if package.get("types") != "Index.d.ets" or package.get("artifactType") != "obfuscation" or package.get("obfuscated") is not True or package.get("compatibleSdkVersion") != 23 or package.get("metadata", {}).get("byteCodeHar") is not True or package.get("metadata", {}).get("debug") is not False:
        raise CandidateError("ProfileMismatch", "HAR is not the declared Release/obfuscated/API23 public package")
    declarations = [data for name, data in members.items() if name.endswith((".d.ets", ".d.ts"))]
    if not declarations or "package/Index.d.ets" not in members:
        raise CandidateError("ArtifactMismatch", "HAR lacks compiler-emitted public declarations")
    if not companion:
        ordinary_public_entry(members, package)
    identity_binding = verify_embedded_identity(candidate["identity"], route, module,
        (candidate["root"] / "generated/facade/Boundary.ets").read_bytes(),
        (candidate["root"] / ("generated/contract/kotlin-binding.json" if route == "kotlin"
                               else "generated/native/identity.generated.hpp")).read_bytes(), members)
    # Metadata claims never replace actual member hashing or target behavior.
    toolchain = read_json(candidate["root"] / "toolchain.json")
    sdk = profile.get("sdk", {})
    expected_sdk = dict(inventory.get("toolchain.json", {}), schema="madb.native-toolchain/1")
    if sdk != expected_sdk:
        raise CandidateError("ArtifactMismatch", "profile SDK reference does not bind the public toolchain bytes")
    if toolchain.get("schema") != "madb.native-toolchain/1":
        raise CandidateError("FormatInvalid", "missing C07 toolchain identity")
    candidate.update(route=route, companion=companion, scope=scope, module=module,
                     har=archives[0], har_members=members, native_members=native, toolchain=toolchain,
                     identity_binding=identity_binding, abi_binding=abi_binding)
    return candidate
