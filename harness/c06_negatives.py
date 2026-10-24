"""Controlled public-SDK mismatches and source-owned backend regression fixtures."""
from __future__ import annotations

import ctypes
from pathlib import Path
import re
import shutil

from candidate import read_json
from c06_build import _library, compile_consumer
from c06_execution import ExecutionError, precise_rejection, run

ROOT = Path(__file__).resolve().parents[1]


def _run(command, expected, temporary, environment, log):
    return run(command + [expected], cwd=temporary, env=environment, log=log, timeout=35)


def _checksum_library(install, temporary, environment, log):
    """Override one checksum, forwarding the complete real ABI to its public library."""
    library = _library(install)
    headers = "\n".join(path.read_text() for path in (install / "include").rglob("*.h"))
    matches = set(re.findall(r"\b(uniffi_[A-Za-z0-9_]*checksum_func_profile_identity)\s*\(", headers))
    if len(matches) != 1:
        raise ValueError("candidate has no unique public profile checksum declaration")
    symbol = matches.pop()
    original = ctypes.CDLL(str(library))
    query = getattr(original, symbol); query.argtypes = []; query.restype = ctypes.c_uint16
    wrong = (query() + 1) & 65535
    backing = library.parent / "negative/c.dylib"
    backing.parent.mkdir()
    shutil.copyfile(library, backing)
    # Keep the replacement ID shorter than the genuine @rpath ID: a producer
    # need not reserve extra Mach-O header space for Lab's negative experiment.
    run(["install_name_tool", "-id", "@loader_path/negative/c.dylib", str(backing)], cwd=temporary, env=environment,
        log=log.with_name(log.stem + "-backing-id.json"), stage="link")
    run(["codesign", "--force", "--sign", "-", str(backing)], cwd=temporary, env=environment,
        log=log.with_name(log.stem + "-backing-sign.json"), stage="link")
    source = temporary / "wrong-checksum.c"
    source.write_text(f"#include <stdint.h>\nuint16_t {symbol}(void) {{ return {wrong}; }}\n")
    run(["xcrun", "clang", "-dynamiclib", str(source), "-Wl,-reexport_library," + str(backing),
         "-Wl,-install_name,@rpath/" + library.name, "-o", str(library)], cwd=temporary, env=environment,
        log=log.with_name(log.stem + "-shim.json"), stage="link")
    return library


def _replace_profile(group, candidate, candidates, install):
    if group == "swift-kotlin":
        target = install / "framework/MadBSkie.framework"
        source = install / "fixtures/wrong-profile/framework/MadBSkie.framework"
        if not source.is_dir(): raise ValueError("missing public wrong-profile SKIE fixture")
        shutil.rmtree(target); shutil.copytree(source, target)
        return
    target = _library(install)
    if group in {"swift-rust", "kotlin-jvm-rust"}:
        other = "kotlin-jvm-rust" if group == "swift-rust" else "swift-rust"
        source = _library(candidates[other]["root"])
    else:
        source = install / "fixtures/wrong-profile/lib" / target.name
    if not source.is_file(): raise ValueError("missing real wrong-profile provider")
    shutil.copyfile(source, target)


def _p04(name, install, temporary, environment, log):
    filename = "MissingCInteropOrigin.swift" if name == "missing-cinterop-origin" else "GenericLambda.swift"
    sources = ROOT / "consumers/swift/c06-skie/negative" / filename
    root = install / "fixtures/p04"
    command = ["xcrun", "swiftc", "-swift-version", "6", "-strict-concurrency=complete", "-warnings-as-errors",
               "-module-cache-path", str(temporary / "p04-modules"), "-target", "arm64-apple-macosx14.0",
               "-F", str(root), "-typecheck", str(sources)]
    markers = (("'acceptCustom(token:)' is unavailable", "Unknown Swift framework for type 'madb.custom.CustomToken'", "ClassInterop.CInteropFrameworkName")
               if name == "missing-cinterop-origin" else ("'lambdaBox()' is unavailable", "lambda type argument"))
    try:
        run(command, cwd=temporary, env=environment, log=log, timeout=60, stage="compile")
    except ExecutionError as error:
        if precise_rejection(error, read_json(log), stage="compile", markers=markers):
            return "", 0, {"code": "CapabilityUnsupported", "stage": "compile"}
        raise
    raise ValueError("unsupported SKIE declaration was incorrectly accepted")


def _skie_wrong_abi(install, temporary, args, environment, log):
    framework = install / "framework/MadBSkie.framework"
    headers = "\n".join(path.read_text() for path in (framework / "Headers").glob("*.h"))
    names = re.findall(r"@interface\s+(\w*BoundaryKt)\b", headers)
    if len(names) != 1: raise ValueError("public SKIE factory class is not uniquely declared")
    interfaces = "\n".join(path.read_text() for path in (framework / "Modules").rglob("*.swiftinterface"))
    if "public func openEngine(expectedProfile:" not in interfaces:
        raise ValueError("public Swift factory signature is absent from delivered module interfaces")
    source = temporary / "empty-provider.c"
    source.write_text("void madb_lab_wrong_provider(void) {}\n")
    object_file = temporary / "empty-provider.o"
    run(["xcrun", "clang", "-c", str(source), "-o", str(object_file)], cwd=temporary, env=environment,
        log=log.with_name("wrong-abi-stub.json"), stage="compile")
    binary = framework / "MadBSkie"
    binary.unlink()
    run(["xcrun", "ar", "rcs", str(binary), str(object_file)], cwd=temporary, env=environment,
        log=log.with_name("wrong-abi-archive.json"), stage="link")
    try:
        compile_consumer("swift-kotlin", install, temporary / "bad-link", args, environment, log.parent / "wrong-abi-compile")
    except ExecutionError as error:
        record = read_json(error.log)
        if (not error.timeout and type(record.get("exit_code")) is int and record["exit_code"] > 0
                and "Undefined symbols" in record.get("stderr", "")
                and "MadBSkie.openEngine(expectedProfile:" in record["stderr"]):
            shutil.copyfile(error.log, log)
            return "", 0, {"code": "AbiMismatch", "stage": "link"}
        raise
    raise ValueError("missing public SKIE binary unexpectedly linked")


def _p03(name, install, temporary, args, environment, log):
    root = install / "fixtures/p03"
    output = temporary / "p03"
    output.mkdir(exist_ok=True)
    binary = output / "consumer.kexe"
    if not (output / "compiled").is_file():
        common = sorted((root / "commonMain").rglob("*.kt")); native = sorted((root / "nativeMain").rglob("*.kt"))
        interop = sorted((root / "klib").glob("*.klib"))
        if not common or not native or not interop: raise ValueError("public P03 generated-source/interop closure missing")
        source = ROOT / "consumers/kotlin-native/c06/ForeignFuture.kt"
        command = [str(args.konan_home / "bin/konanc"), *map(str, common + native), str(source), "-entry", "madb.boundary.main",
                   "-target", "macos_arm64", "-opt", "-o", str(output / "consumer"),
                   "-Xmulti-platform", "-Xexpect-actual-classes", "-Xcommon-sources=" + ",".join(map(str, common)),
                   "-Xoverride-konan-properties=minVersion.macos=14.0;airplaneMode=true"]
        for library in interop + sorted((install / "dependencies").glob("*.klib")):
            command.extend(["-library", str(library)])
        library = _library(root)
        command.extend(["-linker-options", f"-L{library.parent} -l{library.stem[3:]} -rpath {library.parent} -liconv"])
        compile_env = dict(environment, JAVA_HOME=str(args.java_home), KONAN_DATA_DIR=str(args.managed_root / "konan"))
        run(command, cwd=output, env=compile_env, log=log.parent / "p03-compile.json", timeout=180, stage="compile")
        (output / "compiled").write_text("completed public-source compilation\n")
    result, duration = run([str(binary), name], cwd=output, env=environment, log=log, timeout=35)
    return result, duration, None


def execute_special(group, name, candidate, candidates, install, temporary, command, args, environment, log):
    if name in {"missing-cinterop-origin", "generic-lambda"}:
        return _p04(name, install, temporary, environment, log)
    if name in {"foreign-future-once", "callback-throw", "cancel-late-result"}:
        return _p03(name, install, temporary, args, environment, log)
    negative = temporary / name
    negative.mkdir()
    copied = negative / "installed-sdk"
    shutil.copytree(candidate["root"], copied)
    if name == "wrong-profile":
        _replace_profile(group, candidate, candidates, copied)
    elif group == "swift-kotlin":
        (negative / "bad-link").mkdir()
        return _skie_wrong_abi(copied, negative, args, environment, log)
    else:
        _checksum_library(copied, negative, environment, log)
    # A separate consumer binary binds its own fresh installation and cannot use
    # the normal candidate's rpath or a previously loaded JVM library instance.
    executable = compile_consumer(group, copied, negative, args, environment, log.parent / (name + "-compile"))
    output, duration = run(executable + [name, candidate["manifest"]["selector"]["profile_digest"]],
                           cwd=negative, env=environment, log=log, timeout=35)
    return output, duration, {"code": "ProfileMismatch" if name == "wrong-profile" else "AbiMismatch", "stage": "load"}
