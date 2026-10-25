"""Independent C07 scope; requirements are suite inputs, not producer status."""
from pathlib import Path
from candidate import CandidateError, read_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "consumers/arkts/c07"
ROUTES = {
    "c": {"route": "ARKTS-C-NAPI", "prefix": "arkts-c", "module": "madbc07sdkc"},
    "cpp": {"route": "ARKTS-CPP-NAPI", "prefix": "arkts-cpp", "module": "madbc07sdkcpp"},
    "rust": {"route": "ARKTS-RUST-NAPI", "prefix": "arkts-rust", "module": "madbc07sdkrust"},
    "kotlin": {"route": "KN-ARKTS-NAPI", "prefix": "kotlin-arkts", "module": "madbc07sdkkotlin"},
}
TARGET = "aarch64-linux-ohos"
ORDINARY_EXPORTS = {"BoundaryError", "Engine", "Operation", "Runtime", "Snapshot", "Subscription", "openRuntime"}


def requirement(profile_id):
    matches = [entry for entry in read_json(SOURCE / "requirements.json")["profiles"] if entry["profile_id"] == profile_id]
    if len(matches) != 1:
        raise CandidateError("ProfileMismatch", "profile is outside the independent C07 allocation")
    return matches[0]


def case_requirements(profile_id):
    scope = requirement(profile_id)
    cases = read_json(SOURCE / "requirements.json")["cases"]
    return [entry for entry in cases if entry["id"] in scope["required_cases"]]
