"""Run the independent C01 Lab repository checks."""
from pathlib import Path
import argparse
import os
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Repository gates and optional explicit C05 candidate verification")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--first-route", action="store_true")
    mode.add_argument("--c06", action="store_true")
    mode.add_argument("--c07", action="store_true")
    parser.add_argument("--route", choices=("c", "cpp", "rust", "kotlin"))
    parser.add_argument("--companion", action="store_true")
    parser.add_argument("--command-line-tools", type=Path)
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--target")
    parser.add_argument("--target-kind", choices=("emulator", "physical"))
    parser.add_argument("--community-debug-signing", action="store_true")
    parser.add_argument("--signing-config", type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--generation-only", action="store_true")
    parser.add_argument("--generator-cli", type=Path)
    parser.add_argument("--generation-fixtures", type=Path)
    parser.add_argument("--cli-inventory", type=Path)
    parser.add_argument("--cli-inventory-sha256")
    parser.add_argument("--madb-image", type=Path)
    parser.add_argument("--madb-sha256")
    parser.add_argument("--finalizer-image", type=Path)
    parser.add_argument("--finalizer-sha256")
    parser.add_argument("--rust-configuration", type=Path)
    parser.add_argument("--rust-configuration-sha256")
    parser.add_argument("--kotlin-configuration", type=Path)
    parser.add_argument("--kotlin-configuration-sha256")
    parser.add_argument("--identity-fixtures", type=Path)
    parser.add_argument("--identity-fixtures-sha256")
    parser.add_argument("--managed-root", type=Path)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args()
    if (arguments.first_route or arguments.c06 or arguments.c07) and arguments.candidates is None:
        parser.error("SDK verification requires --candidates; missing evidence is not a pass")
    if arguments.c06 and arguments.managed_root is None:
        parser.error("--c06 requires the candidate-bound --managed-root compiler installation")
    if arguments.c07:
        required = ("route", "command_line_tools", "java_home") + (() if arguments.generation_only else ("target", "target_kind"))
        for name in required:
            if not getattr(arguments, name):
                parser.error("--c07 requires --" + name.replace("_", "-"))
        if not arguments.generation_only and bool(arguments.community_debug_signing) == bool(arguments.signing_config):
            parser.error("--c07 requires exactly one explicit signing choice")
    arguments.output = arguments.output or ROOT / "reports" / ("c07" if arguments.c07 else "c06" if arguments.c06 else "c05")
    expected = (ROOT / ".python-version").read_text().strip()
    if platform.python_version() != expected:
        raise RuntimeError(f"Use Python {expected}; got {platform.python_version()}")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    for command in [
        [sys.executable, "harness/check_repository.py"],
        [sys.executable, "harness/check_cases.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "harness/tests"],
    ]:
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
    print("Lab repository and harness checks passed. These checks do not certify an SDK.")
    if arguments.c07:
        command = [sys.executable, "scripts/verify_c07.py", "--candidate", str(arguments.candidates),
                   "--route", arguments.route, "--command-line-tools", str(arguments.command_line_tools),
                   "--java-home", str(arguments.java_home), "--output", str(arguments.output)]
        for name in ("target", "target_kind", "generator_cli", "generation_fixtures", "cli_inventory", "cli_inventory_sha256",
                     "madb_image", "madb_sha256", "finalizer_image", "finalizer_sha256",
                     "rust_configuration", "rust_configuration_sha256", "kotlin_configuration", "kotlin_configuration_sha256", "identity_fixtures", "identity_fixtures_sha256"):
            if getattr(arguments, name) is not None:
                command.extend(["--" + name.replace("_", "-"), str(getattr(arguments, name))])
        if arguments.community_debug_signing:
            command.append("--community-debug-signing")
        elif arguments.signing_config:
            command.extend(["--signing-config", str(arguments.signing_config)])
        for name in ("companion", "allow_dirty", "generation_only"):
            if getattr(arguments, name):
                command.append("--" + name.replace("_", "-"))
        subprocess.run(command, cwd=ROOT, check=True)
    if arguments.c06:
        subprocess.run([sys.executable, "scripts/verify_c06.py", "--candidates", str(arguments.candidates),
                        "--managed-root", str(arguments.managed_root), "--output", str(arguments.output)], cwd=ROOT, check=True)
    if arguments.first_route:
        subprocess.run([sys.executable, "scripts/verify_first_route.py", "--candidates", str(arguments.candidates),
                        "--output", str(arguments.output)], cwd=ROOT, check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Lab checks failed: {error}", file=sys.stderr)
        raise SystemExit(1)
