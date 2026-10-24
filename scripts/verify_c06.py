"""Run independent real C06 consumers against public candidates."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parents[1] / "harness/runners/c06.py"), run_name="__main__")
