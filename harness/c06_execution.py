"""Isolation and process evidence shared by the four actual C06 consumers."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil

from candidate import CandidateError, file_digest
from c06_contract import TARGET
from runners.first_route import ExecutionError, attachment, lab_source_identity, run


def require_host() -> str:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("C06 requires a real macOS Arm64 host; cross-compilation is not target-run evidence")
    return TARGET


def isolated_environment(temporary: Path) -> dict[str, str]:
    home = temporary / "home"
    home.mkdir()
    environment = {
        "HOME": str(home), "GRADLE_USER_HOME": str(temporary / "gradle-home"),
        "KONAN_DATA_DIR": str(temporary / "konan-data"),
        "CARGO_HOME": str(temporary / "cargo-home"),
        "CARGO_TARGET_DIR": str(temporary / "cargo-target"),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C", "LANG": "C",
        "TMPDIR": str(temporary), "MACOSX_DEPLOYMENT_TARGET": "14.0",
        "CLANG_MODULE_CACHE_PATH": str(temporary / "clang-module-cache"),
        "SWIFT_MODULECACHE_PATH": str(temporary / "swift-module-cache"),
    }
    for name in ("DEVELOPER_DIR",):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def install_candidate(candidate: dict, temporary: Path) -> Path:
    """Copy public bytes only. Never link back into producer or a development cache."""
    install = temporary / "installed-sdk"
    shutil.copytree(candidate["root"], install, symlinks=False)
    for item in candidate["manifest"]["files"]:
        path = install / item["path"]
        data = path.read_bytes()
        if path.is_symlink() or len(data) != item["size"] or file_digest(data) != item["sha256"]:
            raise CandidateError("ArtifactMismatch", "installed candidate no longer matches verified public bytes")
    return install


def precise_rejection(error: ExecutionError, log: dict, *, stage: str, markers: tuple[str, ...]) -> bool:
    """A timeout, signal or unrelated diagnostic cannot prove an expected negative."""
    return (not error.timeout and error.stage == stage and log.get("timeout") is False
            and type(log.get("exit_code")) is int and log["exit_code"] > 0
            and all(marker in log.get("stderr", "") + log.get("stdout", "") for marker in markers))
