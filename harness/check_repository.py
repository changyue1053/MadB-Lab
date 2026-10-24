"""C01 repository independence and pinned documentation; no SDK certification."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_CRATES = {"madb-app", "madb-model", "madb-rules", "madb-plan", "madb-protocol", "madb-cli"}
IGNORED = {".git", ".venv", "__pycache__", "target", "reports"}


def snapshot_errors(root: Path) -> list[str]:
    reference = root / "docs" / "reference"
    errors = []
    revision = (reference / "REVISION").read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        errors.append("LAB001: specification revision must be a fixed Git commit")
    seen = set()
    for line in (reference / "SHA256SUMS").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        path = (reference / relative).resolve()
        if not path.is_relative_to(reference.resolve()) or relative in seen:
            errors.append(f"LAB002: invalid or duplicate reference path: {relative}")
            continue
        seen.add(relative)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append(f"LAB003: specification snapshot changed: {relative}")
    expected = {str(path.relative_to(reference)) for path in reference.rglob("*")
                if path.is_file() and path.name not in {"README.md", "SHA256SUMS", "REVISION"}}
    if seen != expected or not seen:
        errors.append("LAB004: reference checksum coverage is incomplete")
    return errors


def dependency_errors(root: Path) -> list[str]:
    """Inspect C01's Cargo dependency declarations, including conditional/alias entries.

    Platform-specific manifest checks are added with their actual consumers.
    This function does not claim to analyze arbitrary native code or Gradle scripts.
    """
    root = root.resolve()
    errors = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if set(relative.parts) & IGNORED:
            continue
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            errors.append(f"LAB005: external symlink: {relative}")
        if path.name != "Cargo.toml" or not path.is_file():
            continue
        manifest = tomllib.loads(path.read_text())
        def inspect_dependencies(dependencies):
            for alias, dependency in dependencies.items():
                package = dependency.get("package", alias) if isinstance(dependency, dict) else alias
                if package in PRIVATE_CRATES:
                    errors.append(f"LAB006: private MadB crate in {relative}: {package}")
                if isinstance(dependency, dict) and "path" in dependency:
                    resolved = (path.parent / dependency["path"]).resolve()
                    if not resolved.is_relative_to(root):
                        errors.append(f"LAB007: external path dependency in {relative}: {alias}")

        def inspect_tables(value):
            if not isinstance(value, dict):
                return
            for key, item in value.items():
                if key in {"dependencies", "build-dependencies", "dev-dependencies"} and isinstance(item, dict):
                    inspect_dependencies(item)
                elif key == "patch" and isinstance(item, dict):
                    for dependencies in item.values():
                        inspect_dependencies(dependencies)
                elif key == "replace" and isinstance(item, dict):
                    inspect_dependencies(item)
                inspect_tables(item)
        inspect_tables(manifest)
    return errors


def main() -> int:
    try:
        errors = snapshot_errors(ROOT) + dependency_errors(ROOT)
    except (OSError, ValueError) as error:
        print(f"LAB000: repository check could not complete: {error}", file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print("Lab repository independence and pinned specification passed; no SDK cases executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
