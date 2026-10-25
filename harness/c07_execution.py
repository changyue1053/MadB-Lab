"""Bounded HAR-to-HAP execution. All SDK and device inputs are explicit."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import uuid
import zipfile
from candidate import CandidateError, file_digest, read_json
from c07_candidate import native_inventory
from c07_contract import SOURCE
from c07_toolchain import verify_tool_closure

BUNDLE = "com.madb.c07probe"


def inherited_environment(environment):
    """Keep host connection/home settings, never ambient executable injection."""
    allowed = {"HOME", "USER", "LOGNAME", "PATH", "SHELL", "TMPDIR", "TMP", "TEMP",
               "LANG", "LC_ALL", "LC_CTYPE", "TZ", "__CF_USER_TEXT_ENCODING",
               "HDC_SERVER_PORT", "HDC_SERVER_ADDRESS", "HDC_SERVER_IP", "HDC_LOG_LEVEL"}
    return {key: value for key, value in environment.items() if key in allowed}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def ref(path, root):
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": file_digest(data), "size": len(data)}


class ExecutionError(RuntimeError):
    pass


class Session:
    def __init__(self, args, candidate):
        self.args, self.candidate = args, candidate
        self.root = args.output / "consumer"
        self.root.mkdir()
        self.logs = args.output / "commands"
        self.logs.mkdir()
        self.nonce = "c07-" + uuid.uuid4().hex
        self.toolkit = args.command_line_tools.resolve(strict=True)
        self.jdk = args.java_home.resolve(strict=True)
        self.sdk = self.toolkit / "sdk/default"
        self.hdc_path = self.sdk / "openharmony/toolchains/hdc"
        self.node = self.toolkit / "tool/node/bin/node"
        self.hvigor = self.toolkit / "hvigor/hvigor/bin/hvigor.js"
        self.ohpm = self.toolkit / "ohpm/bin/ohpm"
        self.environment = inherited_environment(os.environ)
        self.environment.update(HVIGOR_USER_HOME=str(self.root / "hvigor-home"),
            DEVECO_SDK_HOME=str(self.toolkit / "sdk"), NODE_HOME=str(self.toolkit / "tool/node"),
            JAVA_HOME=str(self.jdk), TMPDIR=str(self.root / "tmp"),
            NODE_PATH=str(self.root / "tool-node-modules"), npm_config_cache=str(self.root / "npm-cache"),
            PATH=os.pathsep.join(map(str, (self.toolkit / "tool/node/bin", self.toolkit / "ohpm/bin", self.jdk / "bin"))) + ":/usr/bin:/bin:/usr/sbin:/sbin",
            LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
        for name in ("hvigor-home", "tmp", "ohpm-cache"):
            (self.root / name).mkdir()
        self.command_index = 0
        self.stopped = False

    def run(self, label, command, timeout=30, *, device=False, expected=0, extra_env=None, inherit_env=False):
        self.command_index += 1
        log = self.logs / f"{self.command_index:03}-{label}.json"
        environment = inherited_environment(os.environ) if device or inherit_env else dict(self.environment)
        if extra_env:
            environment.update(extra_env)
        arguments = list(map(str, command))
        start = time.monotonic()
        process = subprocess.Popen(arguments, cwd=self.root, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # This kills only this command's group, never the shared hdc server.
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=10)
        result = {"command": arguments, "exit_code": process.returncode, "timeout": timed_out,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "stdout": stdout.decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace")}
        write_json(log, result)
        print(f"{label}: exit={process.returncode}, timeout={timed_out}, log={log}", flush=True)
        if timed_out or (expected is not None and process.returncode != expected):
            raise ExecutionError(f"{label} failed; raw output: {log}")
        if device and any(marker in (result["stdout"] + result["stderr"]).lower() for marker in
            ("connect server failed", "target not found", "no connected devices", "device not found")):
            raise ExecutionError(f"{label}: transport failure even though command may exit zero; see {log}")
        return result

    def hdc(self, label, *args, timeout=20, expected=0):
        return self.run(label, [self.hdc_path, "-p", "-t", self.args.target, *args], timeout,
                        device=True, expected=expected)

    def verify_closure(self, phase):
        cli, jbr = verify_tool_closure(self.toolkit, self.jdk, self.candidate["toolchain"])
        refs = []
        for name, snapshot in (("cli", cli), ("jbr", jbr)):
            path = self.args.output / (phase + "-" + name + "-inventory.json")
            write_json(path, snapshot)
            refs.append(ref(path, self.args.output))
        return refs

    def verify_tools(self, *, include_device=True):
        closure = self.verify_closure("before")
        metadata = self.candidate["toolchain"]["metadata"]
        product = read_json(self.sdk / "sdk-pkg.json")["data"]
        wanted = metadata["sdk"]["product"]
        fields = ("version", "apiVersion", "releaseType", "platformVersion")
        if any(str(product.get(k)) != str(wanted[k]) for k in fields) or product.get("releaseType") != "Release":
            raise CandidateError("ProfileMismatch", "selected SDK product differs from candidate Release SDK")
        inputs = [self.sdk / "sdk-pkg.json"]
        for component in ("ets", "native", "toolchains"):
            path = self.sdk / "openharmony" / component / "oh-uni-package.json"
            value = read_json(path)
            declared = metadata["sdk"]["components"][component]
            if any(str(value.get(k)) != str(declared[k]) or str(value.get(k)) != str(product.get(k)) for k in fields):
                raise CandidateError("ProfileMismatch", "SDK component identity differs: " + component)
            inputs.append(path)
        tools = {item["id"]: item for item in self.candidate["toolchain"]["tools"]}
        used = {"c07-node": self.node, "c07-hvigor": self.hvigor,
                "c07-ohpm": self.ohpm, "c07-java": self.jdk / "bin/java",
                "c07-readelf": self.sdk / "openharmony/native/llvm/bin/llvm-readelf"}
        for name, path in used.items():
            data = path.read_bytes()
            if file_digest(data) != tools[name]["sha256"] or len(data) != tools[name]["size"]:
                raise CandidateError("ArtifactMismatch", "selected tool bytes differ: " + name)
            inputs.append(path)
        versions = {}
        for name, command in {"node": [self.node, "--version"], "hvigor": [self.node, self.hvigor, "--version"],
                              "ohpm": [self.ohpm, "--version"], "java": [self.jdk / "bin/java", "-version"]}.items():
            value = self.run("version-" + name, command)
            versions[name] = value["stdout"] + value["stderr"]
            if not versions[name].strip():
                raise ExecutionError("tool version exited zero with empty output: " + name)
        if include_device:
            versions["hdc"] = self.hdc("version-hdc", "-v")["stdout"]
            if not versions["hdc"].strip():
                raise ExecutionError("hdc version is empty")
        inputs.extend([self.hvigor, self.hdc_path, self.toolkit / "hvigor/hvigor-ohos-plugin/package.json"])
        write_json(self.args.output / "tools.json", {"versions": versions, "inputs": [
            {"path": str(p), "sha256": file_digest(p.read_bytes()), "size": p.stat().st_size} for p in inputs],
            "closure": closure, "scope": "complete selected CLI/SDK/plugin and JBR trees match candidate; target SDK certification is separate"})

    def verify_target(self):
        values = {}
        for name, parameter in {"api": "const.ohos.apiversion", "version": "const.ohos.fullname",
                                "abi": "const.product.cpu.abilist", "device_type": "const.product.devicetype",
                                "release_type": "const.ohos.releasetype"}.items():
            values[name] = self.hdc("target-" + name, "shell", "param", "get", parameter)["stdout"].strip()
            if not values[name]:
                raise ExecutionError("empty target identity: " + name)
        if values["api"] != "23" or "arm64-v8a" not in values["abi"] or values["release_type"] != "Release":
            raise CandidateError("ProfileMismatch", "target must actually report API23 Release arm64-v8a")
        values.update(target=self.args.target, target_kind=self.args.target_kind)
        write_json(self.args.output / "target.json", values)
        return values

    def prepare(self):
        shutil.copytree(SOURCE / "hap-template", self.root, dirs_exist_ok=True)
        for package in ("hvigor", "hvigor-ohos-plugin"):
            destination = self.root / "tool-node-modules/@ohos" / package
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.symlink_to(self.toolkit / "hvigor" / package, target_is_directory=True)
        (self.root / "local.properties").write_text("sdk.dir=" + str(self.sdk) + "\n")
        dependency_record = read_json(self.candidate["root"] / "native-dependencies.json")
        if dependency_record.get("schema") != "madb.native-dependencies/1":
            raise CandidateError("FormatInvalid", "native dependency record is missing")
        expected_needed = dependency_record.get("needed", {})
        actual_needed = {}
        native_dir = self.root / "native-inspection"
        native_dir.mkdir()
        for member, data in self.candidate["native_members"].items():
            path = native_dir / Path(member).name
            path.write_bytes(data)
            result = self.run("readelf-" + path.name, [self.sdk / "openharmony/native/llvm/bin/llvm-readelf", "--dynamic", path])
            actual_needed[path.name] = sorted(re.findall(r"\(NEEDED\).*?\[([^]]+)\]", result["stdout"]))
        if actual_needed != expected_needed:
            raise CandidateError("ArtifactMismatch", "actual ELF DT_NEEDED differs from candidate dependency record")
        system = {"libace_napi.z.so", "libc.so", "libdl.so", "libm.so", "libuv.so"}
        if any(name not in system | set(actual_needed) for values in actual_needed.values() for name in values):
            raise CandidateError("ArtifactMismatch", "native dependency has no explicit runtime owner")
        write_json(self.args.output / "native-inspection.json", {"needed": actual_needed, "system_libraries": sorted(system)})
        module = self.candidate["module"]
        target = self.root / "entry/src/main/ets"
        for name in ("Assertions.ets.in", "OrdinaryCases.ets.in", "NegativeInputs.d.ts.in", "NegativeInputs.js"):
            text = (SOURCE / name).read_text().replace("@MADB_PUBLIC_MODULE@", json.dumps(module))
            (target / name.removesuffix(".in")).write_text(text)
        (target / "pages").mkdir(exist_ok=True)
        (target / "pages/Index.ets").write_text((SOURCE / "OrdinaryPage.ets.in").read_text().replace("@MADB_PUBLIC_MODULE@", json.dumps(module)))
        (target / "ProbeConfig.ets").write_text("export const PROBE_NONCE: string = " + json.dumps(self.nonce) + ";\n")
        (self.root / "vendor").mkdir()
        archive = self.root / "vendor" / (module + ".har")
        shutil.copyfile(self.candidate["root"] / self.candidate["har"], archive)
        write_json(self.root / "entry/oh-package.json5", {"name": "entry", "version": "1.0.0", "dependencies": {module: "file:../vendor/" + archive.name}})
        self.namecache = self.args.output / (self.nonce + "-namecache.json")
        (self.root / "entry/obfuscation-rules.txt").write_text((SOURCE / "obfuscation-rules.txt.in").read_text().replace("@NAMECACHE@", str(self.namecache)))
        if self.args.signing_config:
            self.environment["MADB_SIGN_CONFIG"] = str(self.args.signing_config.resolve(strict=True))
        else:
            script = SOURCE / "prepare_debug_signing.sh"
            self.run("community-debug-signing", ["/bin/bash", "-c", 'set -euo pipefail; source "$1"; ohos_sign_material "$2" "$3" ""',
                "c07-sign", script, self.root / ".signing", BUNDLE], 90, extra_env={
                    "SIGN_LIB": str(self.sdk / "openharmony/toolchains/lib"), "JAVA_BIN": str(self.jdk / "bin"),
                    "NODE": str(self.node), "MADB_LAB_PYTHON": sys.executable, "DECIPHER": str(self.toolkit / "hvigor/hvigor-ohos-plugin/src/utils/decipher-util.js")})
        self.run("dependencies", [self.ohpm, "install", "--all", "--cache", self.root / "ohpm-cache"], 120)
        installed = self.root / "entry/oh_modules" / module
        for member, data in self.candidate["har_members"].items():
            path = installed / member.removeprefix("package/")
            if path.read_bytes() != data:
                raise CandidateError("ArtifactMismatch", "installed public HAR member changed: " + member)

    def build(self):
        sources = [p for base in ("AppScope", "hvigor", "entry/src") for p in (self.root / base).rglob("*") if p.is_file()]
        sources += [self.root / name for name in ("build-profile.json5", "oh-package.json5", "hvigorfile.ts", "entry/build-profile.json5", "entry/oh-package.json5", "entry/oh-package-lock.json5", "entry/hvigorfile.ts", "entry/obfuscation-rules.txt")]
        sources = sorted(set(sources))
        with tarfile.open(self.args.output / (self.nonce + "-sources.tar"), "x") as archive:
            for path in sources:
                archive.add(path, arcname=path.relative_to(self.root), recursive=False)
        source_refs = [ref(path, self.root) for path in sources]
        self.run("assemble-release-hap", [self.node, self.hvigor, "assembleHap", "--mode", "module",
            "-p", "product=default", "-p", "buildMode=release", "--no-daemon"], 180)
        signed = self.root / "entry/build/default/outputs/default/entry-default-signed.hap"
        self.hap = self.args.output / (self.nonce + ".hap")
        with self.hap.open("xb") as stream:
            stream.write(signed.read_bytes())
        with zipfile.ZipFile(self.hap) as package:
            names = package.namelist()
            if len(names) != len(set(names)):
                raise CandidateError("ArtifactMismatch", "duplicate HAP member")
            members = {name: package.read(name) for name in names if not name.endswith("/")}
        app = json.loads(members["module.json"])["app"]
        expected = {"compileSdkVersion": "26.0.0.105", "minAPIVersion": 60100023,
                    "targetAPIVersion": 260000026, "apiReleaseType": "Release", "buildMode": "release", "bundleName": BUNDLE}
        if any(app.get(key) != value for key, value in expected.items()):
            raise CandidateError("ProfileMismatch", "actual HAP metadata differs from fixed Release/API23 profile")
        native = native_inventory(members)
        expected_native = {name.removeprefix("package/"): data for name, data in self.candidate["native_members"].items()}
        if native != expected_native:
            raise CandidateError("ArtifactMismatch", "final HAP native closure differs from admitted HAR")
        if not self.namecache.is_file() or not self.namecache.stat().st_size:
            raise ExecutionError("obfuscator produced no archived namecache")
        write_json(self.args.output / (self.nonce + "-build.json"), {
            "nonce": self.nonce, "candidate_digest": self.candidate["manifest"]["candidate_digest"],
            "hap": ref(self.hap, self.args.output), "source_archive": ref(self.args.output / (self.nonce + "-sources.tar"), self.args.output),
            "source_inputs": source_refs, "namecache": ref(self.namecache, self.args.output), "app": app,
            "members": [{"path": name, "size": len(data), "sha256": file_digest(data)} for name, data in sorted(members.items())],
            "signing": "explicit user config" if self.args.signing_config else "SDK public community debug; not production signing"})

    def execute(self):
        self.hdc("install", "install", "-r", self.hap, timeout=90)
        self.hdc("stop-old-probe", "shell", "aa", "force-stop", BUNDLE, expected=None)
        self.hdc("start", "shell", "aa", "start", "-a", "EntryAbility", "-b", BUNDLE)
        from c07_observations import parse_ordinary
        deadline = time.monotonic() + 50
        def remaining():
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise ExecutionError("consumer watchdog expired; cleanup not proved")
            return min(20, budget)

        while True:
            pid = self.hdc("probe-pid", "shell", "pidof", BUNDLE, expected=None, timeout=remaining())["stdout"].strip()
            raw = self.hdc("probe-hilog", "shell", "hilog", "-x", "-T", "MadBC07Probe", timeout=remaining())["stdout"]
            remaining()  # A late complete log cannot turn an expired run into a pass.
            observation = parse_ordinary(raw, nonce=self.nonce, pid=pid)
            write_json(self.args.output / f"{self.nonce}-observation-{time.time_ns()}.json", observation)
            if observation["status"] == "failed":
                raise ExecutionError("consumer assertions failed; raw logs and nonce observation preserved")
            if observation["status"] == "passed":
                return observation
            if time.monotonic() >= deadline:
                raise ExecutionError("consumer watchdog expired; cleanup not proved")
            time.sleep(min(0.4, remaining()))

    def stop(self):
        self.hdc("stop-probe", "shell", "aa", "force-stop", BUNDLE)
        pid = self.hdc("pid-after-stop", "shell", "pidof", BUNDLE, expected=None)["stdout"].strip()
        if pid:
            raise ExecutionError("probe process remains after test recovery stop")
        self.stopped = True
