"""Explicit C05 entry: missing candidates or required tools are failures."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "harness/runners/first_route.py"), run_name="__main__")
