"""Independently verify installed compiler closure against candidate-bound receipt."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from candidate import CandidateError, file_digest, logical_path


def _stream_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024): digest.update(block)
    return "sha256:" + digest.hexdigest()


def verify_installation(root: Path, requirement: dict) -> dict:
    root = root.resolve(strict=True)
    receipt_path = root / "receipt.json"
    if receipt_path.is_symlink() or receipt_path.stat().st_size > 32 * 1024 * 1024:
        raise CandidateError("ArtifactMismatch", "managed receipt is a link or exceeds its bounded format")
    data = receipt_path.read_bytes()
    if file_digest(data) != requirement["receipt_sha256"]:
        raise CandidateError("ArtifactMismatch", "installed compiler receipt differs from public candidate")
    receipt = json.loads(data)
    if receipt.get("schema") != "madb.managed-installation/1" or receipt.get("recipe_sha256") != requirement["recipe_sha256"]:
        raise CandidateError("ArtifactMismatch", "managed installation recipe differs")
    names = requirement["components"]
    if not names or len(names) != len(set(names)) or any(name not in receipt["components"] for name in names):
        raise CandidateError("ArtifactMismatch", "required compiler components are incomplete or duplicated")
    for name in names:
        component = receipt["components"][name]
        component_root = root / str(logical_path(component["source"]["path"]))
        if not component_root.resolve().is_relative_to(root) or component_root.is_symlink():
            raise CandidateError("ArtifactMismatch", "compiler component escapes its installation")
        expected = set()
        for item in component["files"]:
            relative = str(logical_path(item["path"]))
            if relative in expected:
                raise CandidateError("ArtifactMismatch", "duplicate compiler inventory entry")
            expected.add(relative); path = component_root / relative
            if "symlink" in item:
                if (not path.is_symlink() or os.readlink(path) != item["symlink"]
                        or not path.resolve().is_relative_to(component_root.resolve())):
                    raise CandidateError("ArtifactMismatch", "compiler symlink changed or escaped its component")
            elif (not path.is_file() or path.is_symlink() or path.stat().st_size != item["size"]
                  or _stream_digest(path) != item["sha256"]
                  or bool(path.stat().st_mode & 0o111) != item["executable"]):
                raise CandidateError("ArtifactMismatch", f"installed compiler file changed: {name}/{relative}")
        actual = {path.relative_to(component_root).as_posix() for path in component_root.rglob("*")
                  if path.is_file() or path.is_symlink()}
        if actual != expected:
            raise CandidateError("ArtifactMismatch", "installed compiler inventory differs from its receipt")
    native = sorted(component["source"]["archive_root"] for component in receipt["components"].values()
                    if component["source"]["path"].startswith("konan/dependencies/"))
    if any(name in names for name in ("kotlin-native", "llvm", "libffi", "lldb")):
        if (root / "konan/dependencies/.extracted").read_text() != "\n".join(native) + "\n":
            raise CandidateError("ArtifactMismatch", "Native tool extraction registry differs from fixed sources")
        konan = root / "konan"
        dependencies = konan / "dependencies"
        if {path.name for path in konan.iterdir()} != {"dependencies"}:
            raise CandidateError("ArtifactMismatch", "unverified Native data/cache outside compiler dependencies")
        allowed = set(native) | {".extracted", "cache"}
        if {path.name for path in dependencies.iterdir()} - allowed:
            raise CandidateError("ArtifactMismatch", "unverified Native dependency/cache entry")
        cache = dependencies / "cache"
        if cache.exists():
            if cache.is_symlink() or not cache.is_dir():
                raise CandidateError("ArtifactMismatch", "Native dependency lock directory changed")
            for entry in cache.iterdir():
                if entry.name != ".lock" or entry.is_symlink() or not entry.is_file() or entry.stat().st_size != 0:
                    raise CandidateError("ArtifactMismatch", "Native dependency download cache contains unverified data")
    return receipt


def tree_identity(root: Path) -> dict:
    """Public tool-tree commitment: sorted relative file/link records, compact JSON."""
    root = root.resolve(strict=True)
    records = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                raise CandidateError("ArtifactMismatch", "Apple tool tree symlink escapes its root")
            records.append({"path": relative, "symlink": os.readlink(path)})
        elif path.is_file():
            records.append({"path": relative, "sha256": _stream_digest(path), "size": path.stat().st_size,
                            "executable": bool(path.stat().st_mode & 0o111)})
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": file_digest(encoded), "entries": len(records), "size": sum(item.get("size", 0) for item in records)}


def verify_apple(toolchain: dict) -> list[dict]:
    """Verify actual consumer compiler and SDK bytes, not their printed names alone."""
    def query(*command):
        return subprocess.check_output(command, text=True, timeout=30).strip()
    apple = toolchain["xcode"]
    if query("/usr/bin/xcodebuild", "-version") != "Xcode " + apple["version"] + "\nBuild version " + apple["build"]:
        raise CandidateError("ProfileMismatch", "consumer Xcode differs from locked profile")
    if (query("/usr/bin/xcrun", "--show-sdk-version") != apple["sdk_version"]
            or query("/usr/bin/xcrun", "--show-sdk-build-version") != apple["sdk_build"]):
        raise CandidateError("ProfileMismatch", "consumer Apple SDK differs from locked profile")
    expected = {item["id"]: item for item in toolchain["tools"]}
    if len(expected) != len(toolchain["tools"]):
        raise CandidateError("ArtifactMismatch", "duplicate public compiler image identity")
    found = {}
    for name in ("swiftc", "swift-frontend", "clang", "ar", "ld"):
        path = Path(query("/usr/bin/xcrun", "--find", name))
        identity = expected.get("c06-" + name)
        if identity is None or identity["sha256"] != _stream_digest(path) or identity["size"] != path.stat().st_size:
            raise CandidateError("ProfileMismatch", "consumer compiler image differs: " + name)
        found[name] = path
    trees = {item["name"]: item for item in toolchain["trees"]}
    for name, path in (("apple-sdk", Path(query("/usr/bin/xcrun", "--show-sdk-path"))),
                       ("apple-toolchain-libraries", found["swiftc"].parent.parent / "lib")):
        actual = tree_identity(path)
        if trees.get(name) != dict(name=name, **actual):
            raise CandidateError("ProfileMismatch", "consumer SDK/tool library tree differs: " + name)
    return [{"id": name, "version": query(str(found[name]), "--version").splitlines()[0][:128],
             "sha256": _stream_digest(found[name]), "host": "aarch64-apple-darwin", "target": "aarch64-apple-darwin",
             "source": str(found[name]), "arguments": []} for name in ("swiftc", "clang")]
