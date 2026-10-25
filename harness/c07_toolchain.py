"""Independent inventories for the public C07 CLI/JBR snapshot definitions."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import stat
import time
from candidate import CandidateError


def inventory_digest(entries):
    # Both public definitions use Python compact sort_keys JSON, ensure_ascii=True.
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inventory(root: Path, *, cli: bool, timeout=120):
    root = root.resolve(strict=True)
    start = time.monotonic()
    paths = sorted(root.rglob("*"))
    if len(paths) > 200000:
        raise CandidateError("ArtifactMismatch", "tool tree exceeds bounded entry budget")
    rows, total = [], 0
    for path in ([root] + paths if cli else paths):
        if time.monotonic() - start > timeout:
            raise RuntimeError("tool inventory watchdog expired")
        relative = "." if path == root else path.relative_to(root).as_posix()
        if path.is_symlink():
            if not path.resolve(strict=True).is_relative_to(root):
                raise CandidateError("ArtifactMismatch", "tool symlink escapes selected tree: " + relative)
            target = str(path.readlink())
            rows.append({"path": relative, "kind": "symlink", "target": target} if cli else {"path": relative, "symlink": target})
        elif path.is_dir():
            if cli:
                rows.append({"path": relative, "kind": "directory", "mode": stat.S_IMODE(path.stat().st_mode)})
        elif path.is_file():
            before = path.stat()
            digest, size = hashlib.sha256(), 0
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
                    size += len(block)
            after = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode) or size != after.st_size:
                raise CandidateError("ArtifactMismatch", "tool input changed while hashing: " + relative)
            total += size
            if total > 20 * 1024 * 1024 * 1024:
                raise CandidateError("ArtifactMismatch", "tool tree exceeds bounded byte budget")
            if cli:
                rows.append({"path": relative, "kind": "file", "mode": stat.S_IMODE(after.st_mode), "sha256": digest.hexdigest(), "size": size})
            else:
                rows.append({"path": relative, "sha256": "sha256:" + digest.hexdigest(), "size": size, "executable": bool(after.st_mode & 0o111)})
        else:
            raise CandidateError("ArtifactMismatch", "special file in selected tool tree")
    if paths != sorted(root.rglob("*")):
        raise CandidateError("ArtifactMismatch", "tool tree membership changed while hashing")
    if cli:
        rows.sort(key=lambda row: row["path"])
    return {"entries": rows, "count": len(rows), "size": total, "sha256": inventory_digest(rows)}


def verify_tool_closure(toolkit, jdk, declared):
    cli = inventory(toolkit, cli=True)
    if cli["sha256"] != declared["cli_entries_sha256"]:
        raise CandidateError("ArtifactMismatch", "complete CLI/SDK/plugin inventory differs")
    expected = [item for item in declared["runtime_trees"] if item["name"] == "host-jbr"]
    if len(expected) != 1:
        raise CandidateError("ArtifactMismatch", "candidate lacks one exact JBR tree")
    jbr = inventory(jdk, cli=False)
    if ("sha256:" + jbr["sha256"], jbr["count"], jbr["size"]) != (expected[0]["sha256"], expected[0]["entries"], expected[0]["size"]):
        raise CandidateError("ArtifactMismatch", "complete JBR implementation tree differs")
    return cli, jbr
