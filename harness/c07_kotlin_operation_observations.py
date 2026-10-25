"""Independent terminal-capacity and unsynchronized cancellation stress oracle.

No producer implementation imports. In-flight samples are facts, not mandatory
instantaneous-overlap proof. A finite run must contain actual native work.
"""

ATTEMPTS = 64
NATIVE_FORMAT = 70501
MAX_SAFE = 2**53 - 1
SCENARIOS = {
    "kotlin-terminal-capacity": {
        **{
            name: "native"
            for name in (
                "kn-op-capacity-before",
                "kn-op-capacity-terminal",
                "kn-op-capacity-denied",
                "kn-op-capacity-recovered",
            )
        },
        **{"kn-op-capacity-consumed-" + str(i): "native" for i in range(8)},
        "kn-op-capacity-values": "vector",
        "kn-op-capacity-recovery-value": "vector",
        "kn-op-capacity-settlement-before": "settling",
        "kn-op-capacity-settlement-unclaimed": "settling",
        "kn-op-capacity-control-before": "control",
        "kn-op-capacity-control-after": "control",
    },
    "kotlin-cancel-race": {
        "kn-op-race-control-before": "control",
        "kn-op-race-control-after": "control",
        "kn-op-race-summary": "vector",
    },
}
for index in range(ATTEMPTS):
    prefix = "kn-op-race-" + str(index) + "-"
    SCENARIOS["kotlin-cancel-race"].update(
        {
            prefix + name: "native"
            for name in ("before", "before-cancel", "closed", "late")
        }
    )
    SCENARIOS["kotlin-cancel-race"].update(
        {
            prefix + "settlement-" + name: "settling"
            for name in ("before", "hook", "result", "closed", "late")
        }
    )
    SCENARIOS["kotlin-cancel-race"][prefix + "outcome"] = "vector"


def predicates(case, frames):
    from c07_kotlin_observations import parse_control_csv

    problems = []

    def need(value, message):
        if not value:
            problems.append(message)

    def native(name):
        value = frames[name]
        if not (
            isinstance(value, list)
            and len(value) == 110
            and value[0] == NATIVE_FORMAT
            and all(type(x) is int and 0 <= x <= MAX_SAFE for x in value)
        ):
            raise ValueError("invalid native110: " + name)
        need(
            all(value[i] == 0 for i in (8, 19, 41, 42, 43, 44)),
            name + ": errors or forbidden work/source gate",
        )
        need(
            value[12] == 1 and value[13] == 0 and value[39] == 1,
            name + ": live actual worker/engine required",
        )
        return value

    def settling(name):
        value = frames[name]
        if not (
            isinstance(value, list)
            and len(value) == 9
            and all(type(x) is int and 0 <= x <= MAX_SAFE for x in value)
        ):
            raise ValueError("invalid settlement9: " + name)
        need(
            value[7] in (0, 1) and value[8] in (0, 1),
            name + ": timer/tick are boolean observations",
        )
        return value

    def idle(value, name):
        need(
            all(value[i] == 0 for i in (11, 24, 26, 27)) and value[14] == value[15],
            name + ": unfinished model/slot/waiter/bytes/work",
        )

    def no_gate(name):
        value = parse_control_csv(frames[name])
        need(
            all(value[i] == 0 for i in (1, 2, 3, 7, 12, 23, 24, 25, 26, 27, 30)),
            name + ": controls/gates/faults must not serialize the test",
        )

    try:
        if case not in SCENARIOS:
            return ["unknown Kotlin operation case"]
        need(set(SCENARIOS[case]) <= set(frames), "missing operation scenario frames")
        if case == "kotlin-terminal-capacity":
            no_gate("kn-op-capacity-control-before")
            no_gate("kn-op-capacity-control-after")
            before = native("kn-op-capacity-before")
            idle(before, "capacity before")
            terminal = native("kn-op-capacity-terminal")
            denied = native("kn-op-capacity-denied")
            for name, value in (("terminal", terminal), ("denied", denied)):
                need(
                    value[14] - before[14] == 8 and value[15] - before[15] == 8,
                    name + ": eight actual work completions required",
                )
                need(
                    value[24] == 8
                    and value[11] == 8
                    and value[26] == 0
                    and value[27] == 64,
                    name
                    + ": eight unclaimed terminal results must retain handles/models/bytes",
                )
                need(
                    value[9] - before[9] == 8 and value[10] == before[10],
                    name + ": result storage was claimed or prematurely freed",
                )
            need(
                all(denied[i] == terminal[i] for i in (9, 10, 11, 14, 15, 24, 26, 27)),
                "ninth admission changed real resource ownership",
            )
            first = settling("kn-op-capacity-settlement-before")
            unclaimed = settling("kn-op-capacity-settlement-unclaimed")
            need(
                first[:7] == unclaimed[:7],
                "a result or close was claimed before terminal capacity check",
            )
            for index in range(8):
                row = native("kn-op-capacity-consumed-" + str(index))
                need(
                    row[24] == 7 - index
                    and row[11] == 7 - index
                    and row[26] == 0
                    and row[27] == 8 * (7 - index),
                    "consumption must release one model/slot and its exact bytes",
                )
                need(
                    row[9] - before[9] == 8 and row[10] - before[10] == index + 1,
                    "one terminal result must be paired with one actual release",
                )
                need(
                    row[14] - before[14] == 8 and row[15] - before[15] == 8,
                    "consuming a result must not rerun work",
                )
            need(
                frames["kn-op-capacity-values"] == list(range(1, 9)),
                "terminal results are not their unique real increment outputs",
            )
            recovered = native("kn-op-capacity-recovered")
            idle(recovered, "capacity recovered")
            need(
                all(recovered[i] - before[i] == 9 for i in (9, 10, 14, 15)),
                "capacity did not permit a ninth genuine complete operation after drain",
            )
            need(
                frames["kn-op-capacity-recovery-value"] == [42],
                "capacity recovery result differs",
            )
        else:
            no_gate("kn-op-race-control-before")
            no_gate("kn-op-race-control-after")
            active = successes = cancellations = work = 0
            previous_late = previous_settlement = None
            for index in range(ATTEMPTS):
                prefix = "kn-op-race-" + str(index) + "-"
                before = native(prefix + "before")
                sampled = native(prefix + "before-cancel")
                closed = native(prefix + "closed")
                late = native(prefix + "late")
                idle(before, prefix + "before")
                idle(closed, prefix + "closed")
                idle(late, prefix + "late")
                outcome = frames[prefix + "outcome"]
                need(
                    outcome in ([0, 1, 1, 1], [5, 1, 1, 1]),
                    prefix
                    + ": only Success/Cancelled, one handler/hook, duplicate claim rejected",
                )
                winner = outcome[0]
                successes += winner == 0
                cancellations += winner == 5
                active += sampled[14] > sampled[15]
                calls = closed[14] - before[14]
                work += calls
                need(
                    calls in (0, 1) and closed[15] - before[15] == calls,
                    prefix + ": actual work must exit exactly once if started",
                )
                if winner == 0:
                    need(calls == 1, prefix + ": Success without actual native work")
                need(
                    closed[9] - before[9] == 1 and closed[10] - before[10] == 1,
                    prefix + ": model must allocate and free exactly once",
                )
                need(
                    sampled[9] - before[9] == 1 and 0 <= sampled[10] - before[10] <= 1,
                    prefix + ": invalid pre-cancel resource activity",
                )
                need(
                    0 <= sampled[15] - before[15] <= sampled[14] - before[14] <= 1,
                    prefix + ": pre-cancel work counters differ",
                )
                need(
                    all(late[i] == closed[i] for i in (9, 10, 11, 14, 15, 24, 26, 27)),
                    prefix + ": late completion repeated work/free or revived ownership",
                )
                sb = settling(prefix + "settlement-before")
                sh = settling(prefix + "settlement-hook")
                sr = settling(prefix + "settlement-result")
                sc = settling(prefix + "settlement-closed")
                sl = settling(prefix + "settlement-late")
                for label, row in (("hook", sh), ("result", sr)):
                    need(
                        row[0] - sb[0] == 1 and row[1] - sb[1] == 1,
                        prefix + label + ": exactly one actual one-shot settlement hook",
                    )
                    need(
                        row[2] - sb[2] == (1 if winner == 0 else 0)
                        and row[3] - sb[3] == (1 if winner == 5 else 0),
                        prefix + label + ": multiple or conflicting result settlements",
                    )
                    need(row[4] == sb[4], prefix + label + ": settler threw")
                need(
                    sh[5] == 1 and sh[6] >= 1 and sr[5] == 0,
                    prefix + ": actual settling ownership not observed and retired",
                )
                need(
                    all(sc[i] >= sr[i] for i in (0, 1, 2, 3, 6))
                    and sc[4] == sr[4]
                    and sc[5] == 0,
                    prefix + ": close lost or leaked settlement state",
                )
                need(sc[:7] == sl[:7], prefix + ": late duplicate settlement")
                if previous_late is not None:
                    need(
                        all(
                            before[i] == previous_late[i]
                            for i in (9, 10, 11, 14, 15, 24, 26, 27)
                        ),
                        prefix + ": operation accounting reset or unobserved extra work",
                    )
                    need(
                        sb[:7] == previous_settlement[:7],
                        prefix + ": settlement counters reset between iterations",
                    )
                previous_late, previous_settlement = late, sl
            need(
                frames["kn-op-race-summary"]
                == [ATTEMPTS, active, successes, cancellations, work],
                "stress summary differs from actual per-attempt observations",
            )
            need(
                successes + cancellations == ATTEMPTS and work > 0,
                "stress did not contain actual native work or a complete legal winner set",
            )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        problems.append("missing/malformed Kotlin operation observation: " + str(error))
    return problems
