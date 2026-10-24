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
    parser.add_argument("--first-route", action="store_true")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "c05")
    arguments = parser.parse_args()
    if arguments.first_route and arguments.candidates is None:
        parser.error("--first-route requires --candidates; missing SDK evidence is not a pass")
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
    if arguments.first_route:
        subprocess.run([sys.executable, "scripts/verify_first_route.py", "--candidates", str(arguments.candidates),
                        "--output", str(arguments.output)], cwd=ROOT, check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Lab checks failed: {error}", file=sys.stderr)
        raise SystemExit(1)
