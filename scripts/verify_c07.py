"""Explicit real ArkTS candidate consumer; never launched by default checks."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1] / "harness/runners/c07.py"), run_name="__main__")
