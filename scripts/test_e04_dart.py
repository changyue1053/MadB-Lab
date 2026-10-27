"""Run E04 Lab model tests; no candidate execution is implied."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'harness'))
suite = unittest.defaultTestLoader.discover(str(ROOT / 'harness/tests'), pattern='test_e04_dart.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
