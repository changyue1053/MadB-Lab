from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from candidate import CandidateError
from source_review_selection import select_source_review


class ReviewSelectionTests(unittest.TestCase):
    def test_legacy_preserved(self):
        legacy = Path("fixed/legacy.json")
        self.assertEqual(select_source_review("c07", "native", legacy), legacy)

    def test_receipt_does_not_use_supplied_legacy_path(self):
        for kind, name in (("native", "route-ownership-review.json"), ("kotlin", "kotlin-source-review.json")):
            actual = select_source_review("c09-receipt-window", kind, Path("untrusted/candidate.json"))
            self.assertEqual(actual, Path(__file__).resolve().parents[2] / "expected/c09_receipt_window" / name)

    def test_unknown_cannot_select_a_file(self):
        for identity in ("", "../review.json", "/tmp/review.json", "candidate", None):
            with self.assertRaises(CandidateError):
                select_source_review(identity, "native", Path("legacy.json"))
        with self.assertRaises(CandidateError):
            select_source_review("c09-receipt-window", "candidate", Path("legacy.json"))
