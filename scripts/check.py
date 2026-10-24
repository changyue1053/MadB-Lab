"""Run the independent C01 Lab repository checks."""
from pathlib import Path
import os
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    expected = (ROOT / ".python-version").read_text().strip()
    if platform.python_version() != expected:
        raise RuntimeError(f"Use Python {expected}; got {platform.python_version()}")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    for command in [
        [sys.executable, "harness/check_repository.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "harness/tests"],
    ]:
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
    print("C01 Lab local baseline passed. No candidate or cross-language test is claimed.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Lab checks failed: {error}", file=sys.stderr)
        raise SystemExit(1)
