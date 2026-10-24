"""Compile Lab sources using only the installed public SDK and explicit tools."""
from __future__ import annotations

from pathlib import Path
import shutil

from c06_execution import run

ROOT = Path(__file__).resolve().parents[1]


def _library(install: Path) -> Path:
    libraries = sorted((install / "lib").glob("*.dylib"))
    if len(libraries) != 1:
        raise ValueError("C06 candidate must select exactly one provider dylib")
    return libraries[0]


def _sources(group: str) -> list[Path]:
    if group in {"kotlin-jvm-rust", "kotlin-native-rust"}:
        platform = "kotlin-jvm" if group == "kotlin-jvm-rust" else "kotlin-native"
        return [ROOT / "consumers/kotlin-common/c06/Consumer.kt", ROOT / f"consumers/{platform}/c06/Platform.kt"]
    folder = "c06-rust" if group == "swift-rust" else "c06-skie"
    return sorted((ROOT / "consumers/swift" / folder).glob("*.swift"))


def copy_sources(group: str, temporary: Path) -> list[Path]:
    output = temporary / "consumer-source"
    output.mkdir()
    copied = []
    for path in _sources(group):
        target = output / path.name
        if target.exists():
            raise ValueError("consumer source basenames collide")
        shutil.copyfile(path, target); copied.append(target)
    if not copied:
        raise ValueError("missing independent C06 consumer sources")
    return copied


def compile_consumer(group, install, temporary, args, environment, logs):
    sources = copy_sources(group, temporary)
    if group == "kotlin-jvm-rust":
        if args.kotlin_home is None or args.java_home is None:
            raise RuntimeError("Kotlin 2.4.20 and pinned JDK homes are required for the real JVM consumer")
        jars = sorted((install / "sdk").glob("*.jar")) + sorted((install / "dependencies").glob("*.jar"))
        if not jars:
            raise ValueError("public JVM SDK/dependency jars are missing")
        classpath = ":".join(map(str, jars))
        binary = temporary / "consumer.jar"
        compile_env = dict(environment, JAVA_HOME=str(args.java_home))
        run([str(args.kotlin_home / "bin/kotlinc"), "-jvm-target", "21", "-classpath", classpath,
             *map(str, sources), "-d", str(binary)], cwd=temporary, env=compile_env,
            log=logs / "compile.json", timeout=120, stage="compile")
        return [str(args.java_home / "bin/java"), "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
                f"-Djna.library.path={install / 'lib'}", "-cp",
                str(binary) + ":" + classpath, "lab.c06.ConsumerKt"]
    if group == "kotlin-native-rust":
        if args.konan_home is None:
            raise RuntimeError("Kotlin/Native 2.4.20 home is required for the real Native consumer")
        libraries = sorted((install / "klib").glob("*.klib")) + sorted((install / "dependencies").glob("*.klib"))
        if not libraries:
            raise ValueError("public Kotlin/Native SDK/dependency klibs are missing")
        binary = temporary / "consumer"
        command = [str(args.konan_home / "bin/konanc"), "-target", "macos_arm64", "-opt", "-produce", "program", "-entry", "lab.c06.main",
                   "-Xoverride-konan-properties=minVersion.macos=14.0;airplaneMode=true",
                   *map(str, sources), "-o", str(binary)]
        for library in libraries: command.extend(["-library", str(library)])
        native = _library(install)
        command.extend(["-linker-options", f"-L{install / 'lib'} -l{native.stem[3:]} -rpath {install / 'lib'} -liconv"])
        native_environment = dict(environment, JAVA_HOME=str(args.java_home), KONAN_DATA_DIR=str(args.managed_root / "konan"))
        run(command, cwd=temporary, env=native_environment, log=logs / "compile.json", timeout=180, stage="compile")
        return [str(binary.with_suffix(".kexe"))]
    binary = temporary / "consumer"
    command = ["xcrun", "swiftc", "-O", "-swift-version", "6", "-strict-concurrency=complete", "-warnings-as-errors",
               "-target", "arm64-apple-macosx14.0", "-module-cache-path", str(temporary / "swift-modules")]
    sdk_swift = sorted((install / "swift").glob("*.swift"))
    if group == "swift-rust":
        if not sdk_swift:
            raise ValueError("public generated Swift source is missing")
        maps = sorted((install / "include").glob("*.modulemap"))
        if len(maps) != 1:
            raise ValueError("public UniFFI module map is not uniquely selected")
        native = _library(install)
        command.extend(["-I", str(install / "include"), "-Xcc", "-fmodule-map-file=" + str(maps[0]),
                        "-L", str(install / "lib"), "-l" + native.stem[3:],
                        "-Xlinker", "-rpath", "-Xlinker", str(install / "lib")])
    else:
        framework = install / "framework/MadBSkie.framework"
        if not framework.is_dir() or not sdk_swift:
            raise ValueError("public SKIE framework or Swift concurrency facade is missing")
        command.extend(["-F", str(framework.parent), "-framework", "MadBSkie"])
    command.extend([*map(str, sdk_swift), *map(str, sources), "-o", str(binary)])
    run(command, cwd=temporary, env=environment, log=logs / "compile.json", timeout=180, stage="compile")
    return [str(binary)]
