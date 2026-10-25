"""Independent terminal/unclaimed capacity and stream-isolation predicates; no producer implementation.

The parent companion oracle validates the supplied 178/15/10-field contracts,
current-run identity, illegal NAPI counters and actual final Runtime teardown.
This slice proves the additional terminal-eight requirement, not a full profile.
"""

SCENARIO = "operations-terminal-capacity"
SCENARIOS = {
    SCENARIO: {
        **{
            "terminal-capacity-" + label: "native"
            for label in (
                "before",
                "unclaimed",
                "denied",
                "one-released",
                "reused",
                "drained",
                *("consumed-" + str(i) for i in range(1, 8)),
            )
        },
        **{"terminal-capacity-operation-" + str(i): "operation" for i in range(8)},
        "terminal-capacity-recovery-operation": "operation",
        "terminal-capacity-facade-before": "facade",
        "terminal-capacity-facade-unclaimed": "facade",
        "terminal-capacity-ninth-rejected": "one",
        "terminal-capacity-values": "vector",
    }
}
SCENARIOS["stream-isolation"] = {
    "isolation-before": "native",
    "isolation-native-1": "native",
    "isolation-native-2": "native",
    "isolation-drained": "native",
    "isolation-state-1": "vector",
    "isolation-state-2": "vector",
    "isolation-event-1": "vector",
    "isolation-event-2": "vector",
    "isolation-late-empty": "vector",
    "isolation-late-next": "vector",
    "isolation-late-registered": "native",
}
GATED = set()


def predicates(case, frames):
    if case == "stream-isolation":
        return stream_predicates(frames)
    problems = []

    def need(ok, reason):
        if not ok:
            problems.append(reason)

    if case != SCENARIO:
        return ["unknown operation-capacity scenario"]
    expected = SCENARIOS[case]
    for name, kind in expected.items():
        value = frames.get(name)
        length = {"native": 178, "operation": 10, "facade": 15, "one": 1, "vector": 9}[
            kind
        ]
        need(
            isinstance(value, list)
            and len(value) == length
            and all(type(x) is int and 0 <= x <= 2**53 - 1 for x in value),
            name + ": missing or invalid public frame",
        )
    if problems:
        return problems
    f = lambda label: frames["terminal-capacity-" + label]
    before, full, denied = f("before"), f("unclaimed"), f("denied")
    ordered = [before, full, denied, f("one-released"), f("reused")]
    ordered += [f("consumed-" + str(i)) for i in range(1, 8)] + [f("drained")]
    for value in ordered:
        need(
            value[0] == value[54] == value[156] == 1 and value[55] == 1,
            "capacity observations must be live owner-env frames",
        )
        need(
            all(value[i] == 0 for i in (10, 11, 12, 13, 19)),
            "capacity checkpoint still contains bytes, work, admission or waiter pressure",
        )
        need(
            value[33] >= value[34] and value[33] - value[34] == value[35],
            "provider allocation/release/live-model ledger differs",
        )
        need(
            value[4] == value[35],
            "each unclaimed operation must still own its result model",
        )
    for a, b in zip(ordered, ordered[1:]):
        need(
            all(b[i] >= a[i] for i in (33, 34, 36)),
            "cumulative provider ledger regressed",
        )
    need(before[4] == before[35] == 0, "baseline is not empty")
    need(
        full[4] == full[35] == 8 and full[36] == before[36] + 8,
        "eight real completed operations with retained unclaimed models were not established",
    )
    need(full[33] >= before[33] + 8, "eight real model allocations are missing")
    for i in range(8):
        value = f("operation-" + str(i))
        need(
            value == [1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
            "operation "
            + str(i)
            + " was not successful, unclosed and ungated before claim",
        )
    initial, pending = f("facade-before"), f("facade-unclaimed")
    need(
        initial[0] == pending[0] == 1 and initial[4] == 0 and pending[4] == 8,
        "facade did not retain the eight operation wrappers",
    )
    need(
        all(initial[i] == pending[i] == 0 for i in (1, 2))
        and pending[11:13] == initial[11:13],
        "result settlement occurred before the ninth admission",
    )
    need(
        f("ninth-rejected") == [1],
        "ninth admission did not throw the required typed error",
    )
    need(
        all(denied[i] == full[i] for i in (4, 10, 11, 12, 13, 19, 33, 34, 35, 36)),
        "rejected ninth admission altered provider work/ownership",
    )
    released, reused = f("one-released"), f("reused")
    need(
        released[4] == released[35] == 7
        and released[33] == denied[33]
        and released[34] == denied[34] + 1
        and released[36] == denied[36],
        "claim plus close did not release exactly one owned model and operation slot",
    )
    need(
        reused[4] == reused[35] == 8
        and reused[36] == before[36] + 9
        and reused[33] > released[33],
        "returned slot did not admit real new provider work",
    )
    need(
        f("recovery-operation") == [1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
        "replacement operation is not a completed unclaimed success",
    )
    previous = reused
    for i in range(1, 8):
        current = f("consumed-" + str(i))
        need(
            current[4] == current[35] == 8 - i
            and current[33] == previous[33]
            and current[34] == previous[34] + 1
            and current[36] == reused[36],
            "old result " + str(i) + " was not released exactly once",
        )
        previous = current
    drained = f("drained")
    need(
        drained[4] == drained[35] == 0
        and drained[33] == previous[33]
        and drained[34] == previous[34] + 1
        and drained[36] == before[36] + 9
        and drained[33] - before[33] == drained[34] - before[34],
        "recovery result and all accepted models did not pair with real release",
    )
    need(
        f("values") == list(range(11, 19)) + [100],
        "claimed results differ or duplicate an old value",
    )
    return problems


def stream_predicates(frames):
    problems = []

    def need(ok, reason):
        if not ok:
            problems.append(reason)

    for name, kind in SCENARIOS["stream-isolation"].items():
        value = frames.get(name)
        length = (
            178
            if kind == "native"
            else (
                0
                if name == "isolation-late-empty"
                else 1 if name == "isolation-late-next" else int(name[-1])
            )
        )
        need(
            isinstance(value, list)
            and len(value) == length
            and all(type(x) is int and 0 <= x <= 2**53 - 1 for x in value),
            name + ": missing or invalid frame",
        )
    if problems:
        return problems
    ordered = [
        frames[name]
        for name in (
            "isolation-before",
            "isolation-native-1",
            "isolation-late-registered",
            "isolation-native-2",
            "isolation-drained",
        )
    ]
    for i, value in enumerate(ordered):
        need(
            value[0] == value[54] == value[55] == value[156] == 1,
            "stream observation is not a live owner-env frame",
        )
        need(
            value[5] == (2, 2, 3, 3, 0)[i],
            "both actual subscriptions were not retained until close",
        )
        need(
            all(value[j] == 0 for j in (4, 6, 7, 8, 9, 10, 11, 12, 13, 19, 35)),
            "delivered stream payload or child obligation remains",
        )
        need(value[33] == value[34], "stream provider clones did not pair with releases")
        need(
            value[36] == ordered[0][36], "stream test unexpectedly admitted business work"
        )
    for i in (1, 3):
        need(
            ordered[i][33] > ordered[i - 1][33] and ordered[i][34] > ordered[i - 1][34],
            "round did not allocate and release real payloads",
        )
    need(
        ordered[4][33:35] == ordered[3][33:35],
        "subscription close introduced unexpected model work",
    )
    need(
        frames["isolation-state-1"] == [11] and frames["isolation-state-2"] == [11, 12],
        "state stream was replaced, contaminated or duplicated by event publication",
    )
    need(
        frames["isolation-event-1"] == [21] and frames["isolation-event-2"] == [21, 22],
        "event stream was replaced, contaminated or duplicated by state publication",
    )
    need(
        ordered[2][33:35] == ordered[1][33:35],
        "late registration replayed or allocated a prior current value",
    )
    need(
        frames["isolation-late-empty"] == [] and frames["isolation-late-next"] == [12],
        "late subscriber received prior state or missed its next publication",
    )
    return problems
