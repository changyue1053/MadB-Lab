"""Independent, nonce/PID-bound ordinary observations. JSON is diagnostic transport."""
import json

EXPECTED = {
    "values-and-negative-inputs": [16, 1, 1, 2, 1, 0, 2],
    "ordinary-api-and-request-only-retirement": [1],
    "ordinary-runtime-close-returned": [1],
    "ordinary-runtime-reopened": [1, 42, 51, 3],
}


def parse_ordinary(raw, *, nonce, pid):
    lines = [line for line in raw.splitlines() if nonce in line]
    problems, frames = [], {}
    if not isinstance(pid, str) or not pid.isdigit() or int(pid) <= 0:
        problems.append("probe process absent or non-unique")
    elif any(len(line.split()) < 3 or line.split()[2] != pid for line in lines):
        problems.append("nonce/PID binding mismatch")
    failures = [line for line in lines if "PROBE_FAILED " + nonce in line]
    prefix = "ORDINARY_CASE " + nonce + " "
    for line in lines:
        if prefix not in line:
            continue
        try:
            label, encoded = line.split(prefix, 1)[1].split(" ", 1)
            values = json.loads(encoded)
            if label in frames or not isinstance(values, list) or any(type(value) is not int for value in values):
                problems.append("duplicate or malformed observation")
            frames[label] = values
        except (ValueError, TypeError):
            problems.append("malformed observation transport")
    complete = sum("ORDINARY_COMPLETE " + nonce in line for line in lines)
    if complete > 1:
        problems.append("duplicate completion")
    if complete:
        if frames != EXPECTED or list(frames) != list(EXPECTED):
            problems.append("ordinary labels or independently expected values differ")
        for marker in ("PROBE_STARTED", "PROBE_PAGE_READY", "PROBE_FINISHED"):
            if sum(marker + " " + nonce in line for line in lines) != 1:
                problems.append("missing/duplicate " + marker)
    return {"status": "failed" if failures or problems else "passed" if complete else "incomplete",
            "nonce": nonce, "pid": int(pid) if isinstance(pid, str) and pid.isdigit() and int(pid) > 0 else None, "frames": frames,
            "failures": failures, "problems": problems, "lines": lines}
