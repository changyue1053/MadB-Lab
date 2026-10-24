"""Check Lab-owned definitions and source identity; never infer expected behavior."""
from pathlib import Path
import sys

from candidate import CandidateError, file_digest, logical_path, read_json

ROOT = Path(__file__).resolve().parents[1]


def errors(root=ROOT):
    findings, identifiers = [], set()
    for path in sorted((root / "cases").rglob("*.json")):
        case = read_json(path)
        if case.get("schema") != "madb.case/1" or case.get("kind") != "template" or case.get("selector") is not None:
            findings.append(f"LAB101: {path.name}: expected public case template")
        if case["id"] in identifiers:
            findings.append(f"LAB102: duplicate case ID: {case['id']}")
        identifiers.add(case["id"])
        fixture = case["fixture"]
        source = root / str(logical_path(fixture["path"]))
        if not source.is_file() or source.is_symlink():
            findings.append(f"LAB103: missing/local-only fixture source: {fixture['path']}")
        else:
            data = source.read_bytes()
            if fixture["sha256"] != file_digest(data) or fixture["size"] != len(data):
                findings.append(f"LAB104: changed case fixture identity: {case['id']}")
        if not case.get("steps") or not case.get("assertions") or not case.get("cleanup"):
            findings.append(f"LAB105: incomplete independent expectation/cleanup: {case['id']}")
        if case.get("timeout_policy", {}).get("on_timeout") != "error":
            findings.append(f"LAB106: timeout cannot become passed/skipped: {case['id']}")
    if not identifiers:
        findings.append("LAB107: no C05 case definitions")
    return findings


if __name__ == "__main__":
    try:
        findings = errors()
    except (CandidateError, OSError, KeyError, TypeError) as error:
        findings = [f"LAB100: case check could not complete: {error}"]
    for finding in findings:
        print(finding, file=sys.stderr)
    if findings:
        raise SystemExit(1)
    print("Independent case definitions and fixture identities passed; no SDK run claimed.")
