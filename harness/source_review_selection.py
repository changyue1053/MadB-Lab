"""Explicit Lab-maintained review selection; never read a candidate-chosen path."""
from pathlib import Path
from candidate import CandidateError

_RECEIPT = Path(__file__).resolve().parents[1] / "expected/c09_receipt_window"
_FILES = {"native": "route-ownership-review.json", "kotlin": "kotlin-source-review.json"}


def select_source_review(review_id, kind, legacy):
    if kind not in _FILES:
        raise CandidateError("ArtifactMismatch", "unknown source review kind")
    if review_id == "c07":
        return legacy
    if review_id == "c09-receipt-window":
        return _RECEIPT / _FILES[kind]
    raise CandidateError("ArtifactMismatch", "unknown independently maintained source review")
