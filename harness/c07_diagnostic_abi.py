"""Independent C07 diagnostic ABI reconstruction from public candidate files.

The finite selectors implement the published layout protocol. The producer's
precomputed descriptor is checked against the attachments, never used as oracle.
"""

from candidate import CandidateError, file_digest, read_json

TEST = "generated/contract/test/"
C_LAYOUTS = {
    "native_frame": ("generated/contract/frame-layout.json", ()),
    "test_frame": (
        TEST + "test-frame-layout.json",
        (
            "native_prefix_length",
            "test_length",
            "total_length",
            "fields",
            "operation_fields",
            "hook_entry_offset",
            "hook_entry_length",
        ),
    ),
    "observer": (
        TEST + "observer-layout.json",
        (
            "format",
            "length",
            "unchanged_prefix",
            "local_offset",
            "local",
            "process_offset",
            "process",
            "range",
        ),
    ),
    "frame_units": (TEST + "diagnostic-units-v1.json", ("version", "fields")),
    "facade": (TEST + "facade-frame-layout.json", ("format", "length", "fields")),
    "delivery": (
        TEST + "ports-layout.json",
        ("delivery.format", "delivery.length", "delivery.fields", "delivery.units"),
    ),
    "bootstrap": (
        TEST + "bootstrap-totals-layout.json",
        ("format", "length", "fields", "units"),
    ),
    "memory": (
        TEST + "memory-layout.json",
        ("format", "length", "fields", "units", "errors"),
    ),
    "subscription": (
        TEST + "subscription-state-layout.json",
        ("format", "length", "fields", "units", "errors"),
    ),
}
KOTLIN_LAYOUTS = {
    "admission": (
        TEST + "admission-frame.json",
        ("length", "wire", "numeric_domain", "fields"),
    ),
    "controls": (
        TEST + "controls-frame.json",
        ("format", "length", "wire", "frame.fields"),
    ),
    "memory": (
        TEST + "memory-frame.json",
        ("format", "length", "wire", "fields", "units"),
    ),
    "napi_observer": (
        TEST + "napi-observer-frame.json",
        (
            "format",
            "wire",
            "fixed_fields",
            "unknown",
            "capabilities",
            "categories",
            "roles",
        ),
    ),
    "settlement": (TEST + "settlement-frame.json", ("length", "wire", "fields")),
    "subscription": (
        TEST + "subscription-frame.json",
        ("format", "length", "wire", "fields"),
    ),
    "runtime": (
        "generated/contract/kotlin-frame-layout.json",
        ("format", "length", "fields", "zero_at_closed", "equal_at_closed"),
    ),
}
FIELD_SEMANTICS = frozenset(
    (
        "index",
        "name",
        "unit",
        "domain",
        "range",
        "group",
        "category",
        "return",
        "arguments",
        "function_type",
    )
)


def field_semantics(value):
    if isinstance(value, list):
        return [field_semantics(item) for item in value]
    if isinstance(value, dict):
        if "name" in value:
            return {key: item for key, item in value.items() if key in FIELD_SEMANTICS}
        return {key: field_semantics(item) for key, item in value.items()}
    return value


def layout_semantics(document, selectors):
    if not selectors:
        return {key: item for key, item in document.items() if key.isdecimal()}
    result = {}
    for selector in selectors:
        item = document
        for component in selector.split("."):
            item = item[component]
        if selector in ("fields", "frame.fields", "fixed_fields"):
            item = field_semantics(item)
        elif selector == "roles":
            item = [
                {
                    "role": row["role"],
                    "count": row["count"],
                    "per_api_fields": field_semantics(row["per_api_fields"]),
                }
                for row in item
            ]
        result[selector] = item
    return result


def reconstruct(candidate, route, declared):
    layouts = KOTLIN_LAYOUTS if route == "kotlin" else C_LAYOUTS
    if (
        not isinstance(declared, dict)
        or set(declared) != {"protocols", "sources"}
        or not isinstance(declared.get("protocols"), dict)
        or not isinstance(declared.get("sources"), dict)
        or set(declared["protocols"]) != set(layouts)
        or set(declared["sources"]) != set(layouts)
    ):
        raise CandidateError(
            "AbiMismatch", "diagnostic authorities differ from the selected route"
        )
    inventory = {item["path"]: item for item in candidate["manifest"]["files"]}
    lock = read_json(candidate["root"] / "madb.lock")
    locked = {item["path"]: item for item in lock["inputs"]}
    result = {}
    try:
        for identity, (path, selectors) in layouts.items():
            ref = declared["sources"][identity]
            if set(ref) != {"path", "sha256", "size"} or locked.get(ref["path"]) != ref:
                raise CandidateError(
                    "ArtifactMismatch",
                    "diagnostic source is not a locked input: " + identity,
                )
            if path not in inventory:
                raise CandidateError(
                    "ArtifactMismatch", "diagnostic attachment is absent: " + path
                )
            raw = (candidate["root"] / path).read_bytes()
            digest, size = file_digest(raw), len(raw)
            if inventory[path]["sha256"] != digest or inventory[path]["size"] != size:
                raise CandidateError(
                    "ArtifactMismatch", "diagnostic attachment bytes differ: " + path
                )
            # Kotlin's runtime layout is generated. Its source reference pins the
            # generator; the generated attachment is independently file-bound.
            if not (route == "kotlin" and identity == "runtime") and (
                ref["sha256"],
                ref["size"],
            ) != (digest, size):
                raise CandidateError(
                    "ArtifactMismatch",
                    "diagnostic attachment differs from its source: " + identity,
                )
            result[identity] = layout_semantics(
                read_json(candidate["root"] / path), selectors
            )
    except (KeyError, TypeError, OSError) as error:
        raise CandidateError(
            "FormatInvalid", "incomplete diagnostic layout authority"
        ) from error
    if result != declared["protocols"]:
        raise CandidateError(
            "AbiMismatch", "diagnostic descriptor differs from actual layout attachments"
        )
    return result
