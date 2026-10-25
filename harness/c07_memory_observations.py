"""Independent C/C++/Rust memory-domain predicates; no producer code imports.

Integer byte observations are requested/capacity/object storage, not RSS, malloc
usable-size, GC heaps, or physical stack measurement. Stable held gates and real
final cleanup are required by the surrounding existing controlled-run oracle.
"""

FIELDS = """Format CoreRetainedCurrent CoreRetainedPeak PublicationStagingCurrent PublicationStagingPeak
ProviderObjectCurrent ProviderObjectPeak ProviderTextCurrent ProviderTextPeak ProviderStoragePeak
ProviderStorageAcquired ProviderStorageReleased Utf8BackingCurrent Utf8BackingPeak Utf8BackingAcquired
Utf8BackingReleased InputObjectCurrent InputObjectPeak Utf16ArrayCurrent Utf16ArrayPeak InputScopesEntered
InputScopesExited Utf16ScopesEntered Utf16ScopesExited ModelObjectSize InputObjectSize Utf16ArraySize""".split()
SCENARIOS = {
    "memory-state-staging": {
        **{
            name: "memory"
            for name in (
                "memory-state-pending",
                "memory-state-staged",
                "memory-state-replaced",
                "memory-state-entered",
                "memory-state-drained",
                "memory-final",
            )
        },
        "memory-state-gate": "delivery",
        "memory-state-values": "vector",
        **{
            name: "native"
            for name in (
                "memory-state-staged-native",
                "memory-state-replaced-native",
                "memory-state-entered-native",
            )
        },
    },
    "memory-full-scratch": {
        **{
            name: "memory"
            for name in (
                "memory-full-before-copy",
                "memory-full-after-copy",
                "memory-full-rejected",
                "memory-final",
            )
        },
        **{
            name: "native"
            for name in (
                "memory-full-native",
                "memory-full-after-copy-native",
                "memory-full-rejected-native",
            )
        },
        "memory-copy-result": "vector",
    },
}
GATED = {"memory-full-scratch"}
UNITS = {
    "bytes": "all fields except Format and scope-event counts20..23; peak is simultaneous per-domain accounting maximum",
    "scope_counts": "20..23 cumulative lexical-object scope events",
    "object_layout": "24..26 actual compiler sizeof, not allocator usable-size or measured physical stack frames",
}


def validate_contracts(contracts):
    layout = contracts["memory-layout.json"]
    if (layout.get("format"), layout.get("length"), layout.get("native_ordinal")) != (
        1,
        27,
        31,
    ):
        raise ValueError("unsupported memory diagnostics format/length/ordinal")
    if layout.get("fields") != {str(i): name for i, name in enumerate(FIELDS)}:
        raise ValueError("memory field order/name differs")
    if layout.get("units") != UNITS:
        raise ValueError("memory byte/scope/layout units differ")
    if (
        layout.get("native_signature") != "testMemory(runtime:string):number[]"
        or layout.get("public_signature") != "testMemory(runtime:Runtime):number[]"
    ):
        raise ValueError("memory observation port differs")


def predicates(case, frames, need, equal, delta):
    labels = [name for name, kind in SCENARIOS[case].items() if kind == "memory"]
    for name in labels:
        value = frames[name]
        need(
            len(value) == 27
            and value[0] == 1
            and all(type(x) is int and 0 <= x <= 2**53 - 1 for x in value),
            name + ": memory format/range",
        )
        if len(value) != 27:
            return
        need(
            value[1] <= value[2] <= 4096 and value[3] <= value[4] <= 4096,
            name + ": canonical/staging budget or peak",
        )
        need(value[3] <= value[1], name + ": staging is not charged as retained")
        need(
            value[10] >= value[11] and value[10] - value[11] == value[5] + value[7],
            name + ": provider storage accounting",
        )
        need(
            value[14] >= value[15] and value[14] - value[15] == value[12],
            name + ": UTF-8 backing accounting",
        )
        need(
            value[20] >= value[21] and value[22] >= value[23],
            name + ": lexical scope underflow",
        )
        need(
            value[16] == (value[20] - value[21]) * value[25]
            and value[18] == (value[22] - value[23]) * value[26],
            name + ": active scope storage",
        )
        need(
            value[6] >= value[5]
            and value[8] >= value[7]
            and value[9] >= value[5] + value[7]
            and max(value[6], value[8]) <= value[9] <= value[6] + value[8],
            name + ": simultaneous provider peak",
        )
        need(
            value[13] >= value[12] and value[17] >= value[16] and value[19] >= value[18],
            name + ": conversion peaks",
        )
        need(
            value[24] >= 4
            and value[25] > 0
            and value[26] >= 2
            and value[13] >= 1025
            and value[17] >= value[25]
            and value[19] >= value[26],
            name + ": missing observed model/input/UTF16/UTF8 storage domains",
        )
        # Each observation occurs after input decoding returned or in a delivery
        # callback, not during an input scope. This is a consumer-controlled point.
        equal(name, {12: 0, 16: 0, 18: 0})
    layout = tuple(frames[labels[0]][24:27])
    for name in labels:
        need(tuple(frames[name][24:27]) == layout, name + ": object layout changed")
    for before, after in zip(labels, labels[1:]):
        for field in (2, 4, 6, 8, 9, 10, 11, 13, 14, 15, 17, 19, 20, 21, 22, 23):
            need(
                frames[after][field] >= frames[before][field],
                after + ": cumulative metric regressed",
            )
    final = frames["memory-final"]
    equal("memory-final", {1: 0, 3: 0, 5: 0, 7: 0, 12: 0, 16: 0, 18: 0})
    need(
        final[10] == final[11]
        and final[14] == final[15]
        and final[20] == final[21]
        and final[22] == final[23],
        "final actual storage/scopes did not balance",
    )
    size = layout[0]
    if case == "memory-state-staging":
        equal("memory-state-gate", {1: 0, 2: 1, 3: 0, 5: 1, 6: 0})
        equal("memory-state-pending", {1: 1024, 2: 1024, 3: 0, 5: size})
        equal("memory-state-staged", {1: 2048, 2: 2048, 3: 1024, 4: 1024, 5: 2 * size})
        equal("memory-state-staged-native", {7: 1, 9: 0, 10: 2048, 77: 1})
        equal("memory-state-replaced", {1: 1024, 2: 2048, 3: 0, 4: 1024, 5: size})
        equal("memory-state-replaced-native", {7: 1, 9: 0, 10: 1024, 77: 0})
        equal("memory-state-entered", {1: 1024, 3: 0, 5: size})
        equal("memory-state-entered-native", {7: 1, 9: 1, 10: 1024})
        equal("memory-state-drained", {1: 0, 3: 0, 5: 0, 7: 0})
        need(frames["memory-state-values"] == [2], "old/preentry state was delivered")
        staged = frames["memory-state-staged"]
        need(
            staged[7] >= 2048 and staged[9] >= 2 * size + 2048,
            "two real staged/pending model allocations were not observed",
        )
        need(
            frames["memory-state-replaced"][11] > staged[11],
            "old pending model was not actually released at replacement",
        )
    else:
        for name in (
            "memory-full-before-copy",
            "memory-full-after-copy",
            "memory-full-rejected",
        ):
            equal(name, {1: 4096, 2: 4096, 3: 0, 4: 0, 5: 4 * size})
            need(frames[name][7] >= 4096, name + ": missing four retained provider texts")
        for name in (
            "memory-full-native",
            "memory-full-after-copy-native",
            "memory-full-rejected-native",
        ):
            equal(name, {3: 0, 4: 4, 10: 4096, 13: 1})
        copied = frames["memory-full-after-copy"]
        before = frames["memory-full-before-copy"]
        need(
            copied[6] >= 5 * size and copied[8] >= 5120 and copied[9] >= 5 * size + 5120,
            "simultaneous retained-plus-scratch provider peak was not measured",
        )
        need(
            copied[10] > before[10]
            and copied[11] > before[11]
            and copied[14] > before[14]
            and copied[15] > before[15]
            and copied[20] > before[20]
            and copied[22] > before[22],
            "scratch copy did not acquire/release actual storage and conversion scopes",
        )
        delta(
            "memory-full-after-copy", "memory-full-rejected", {5: 0, 7: 0, 10: 0, 11: 0}
        )
        need(
            frames["memory-copy-result"] == [1, 1024, 512],
            "full retained budget did not permit a real 1024-byte scratch roundtrip",
        )
