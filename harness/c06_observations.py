"""Independent observations and exact-case coverage for C06 consumers.

Consumers emit observations obtained through public SDK calls. Test assertions
are owned by Lab, not loaded from a candidate, SDK profile or provider runtime.
"""
from __future__ import annotations

import json


def _same_value(actual, wanted):
    if type(actual) is not type(wanted):
        return False
    if isinstance(actual, dict):
        return actual.keys() == wanted.keys() and all(_same_value(actual[key], wanted[key]) for key in actual)
    if isinstance(actual, list):
        return len(actual) == len(wanted) and all(_same_value(a, b) for a, b in zip(actual, wanted))
    return actual == wanted


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON observation key")
        value[key] = item
    return value


def observations(output: str, *, expected: dict) -> dict:
    """Require every independent check once; diagnostic noise cannot claim a pass."""
    observed = {}
    completed = False
    for raw in output.splitlines():
        if not raw:
            continue
        try:
            record = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite observation")))
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("consumer emitted a malformed observation") from error
        if record == {"result": "passed"}:
            if completed:
                raise ValueError("duplicate consumer completion")
            completed = True
            continue
        if completed or not isinstance(record, dict) or set(record) != {"check", "actual"}:
            raise ValueError("invalid or late consumer observation")
        name = record["check"]
        if not isinstance(name, str) or name not in expected or name in observed:
            raise ValueError("unknown or duplicate independent check")
        actual, wanted = record["actual"], expected[name]
        # Python otherwise treats True == 1. Numeric/bool representation matters.
        if not _same_value(actual, wanted):
            raise ValueError(f"independent check differs: {name}: {actual!r} != {wanted!r}")
        observed[name] = actual
    if not completed or set(observed) != set(expected):
        raise ValueError("consumer omitted required checks or final completion")
    return observed


def resource_observations(observed: dict) -> list[dict]:
    """Optional per-counter release checks remain distinct from SDK stop success."""
    results = []
    for name, counts in observed.items():
        if not name.startswith("resource."):
            continue
        if (not isinstance(counts, dict) or set(counts) != {"before", "after", "created", "released"}
                or any(type(value) is not int or value < 0 for value in counts.values())):
            raise ValueError("invalid resource observation")
        if counts["before"] != counts["after"] or counts["created"] != counts["released"]:
            raise ValueError("consumer did not restore its resource baseline")
        results.append(dict(name=name[9:], **counts))
    return results
