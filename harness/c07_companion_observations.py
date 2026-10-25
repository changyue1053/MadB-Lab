"""Lab-owned C07 controlled-log oracle over explicitly supplied public layouts.

One successful scenario is not a matrix group or full-profile certification.
Kotlin requires its own layout and is deliberately unsupported here.
"""
import json
import re
from c07_completion_observations import SCENARIOS as COMPLETION_SCENARIOS, GATED as COMPLETION_GATED, predicates as completion_predicates

from c07_admission_observations import SCENARIOS as ADMISSION_SCENARIOS, GATED as ADMISSION_GATED, TWO_GENERATIONS, predicates as admission_predicates, validate_contracts as admission_contracts
from c07_diagnostic_observations import SCENARIOS as DIAGNOSTIC_SCENARIOS, GATED as DIAGNOSTIC_GATED, predicates as diagnostic_predicates

from c07_identity_observations import SCENARIOS as IDENTITY_SCENARIOS
from c07_listener_lifetime_observations import SCENARIOS as LISTENER_SCENARIOS, predicates as listener_predicates

from c07_memory_observations import SCENARIOS as MEMORY_SCENARIOS, GATED as MEMORY_GATED, predicates as memory_predicates, validate_contracts as memory_contracts

from c07_capacity_stream_observations import SCENARIOS as CAPACITY_STREAM_SCENARIOS, predicates as capacity_stream_predicates

MAX_SAFE = 2**53 - 1
RUNTIME_FIELDS = """Format Phase BusinessEntries ScratchLive Operations Subscriptions
EventTickets StateTickets Sources Entered Bytes Waiters Admissions Work Executors
CoreClosing CoreClosed WorkerJoined JoinJobLive WaiterIndices ExplicitRefLive
TsfnOwnerLive WakeLive InDispatch HookLive ContextLive ResidualErrors EnvExit
ProviderContextLive CallbackContextsLive RuntimeCloseRequested MechanismTeardownStarted
ReceiptConsumed ProviderAllocations ProviderReleases ProviderModelsLive ProviderWorkCalls
WakeFailures WakeCreated WakeReleased ContextCreated ContextDestroyed RefCreated RefDeleted
TsfnCreated TsfnFinalized HookAdded HookRetired JoinQueued JoinCompleted EnginesCreated
EnginesDestroyed ScratchAcquired ScratchReleased""".split()
TEST_FIELDS = """TestFormat ReadMode GatePhase GateArmed GateArrived GateReleased GateResumed
GateSequence WorkerTid OwnerTid CleanupTid WorkerStarted WorkerLoopExited WorkerTlsExited
JoinStarted JoinReturned ExecutorReleased StartedSequence LoopExitedSequence TlsExitedSequence
JoinStartedSequence JoinReturnedSequence ExecutorReleasedSequence SourceHeld SourceAcquired
SourceCommitted SourceAbandoned CloneNth CloneCallsSinceArm CloneFaultHits CompletionStage
CompletionFaultHits ClaimRollbackHits BeforeGuardHits AfterGuardHits PartialOpenArmed
PartialOpenHits AsyncCleanupEntered AsyncCleanupReturned AsyncHookRemoved TsfnFinalizeEntered
FinalContextDestroyed GateWorkInput ScratchPeak DispatchEntered DispatchReturned DispatchThrows
LastEventSequence""".split()
LOCAL_FIELDS = """Format Attempts IllegalAttempts WrongThread WrongEnv InvalidOwner
NullWakeEntered NullWakeDestroyed NullFinalizerEntered CleanupRefDeleted CleanupTsfnReleased
CleanupHookRemoved""".split()
PROCESS_FIELDS = """GlobalAttempts GlobalIllegalAttempts GlobalUnscopedAttempts
GlobalModuleRegistrations GlobalRefCreated GlobalRefDeleted GlobalTsfnCreated
GlobalTsfnReleased GlobalHookAdded GlobalHookRemoved""".split()
FACADE_FIELDS = """Format WaiterMap SettlingWaiters SubscriptionsMap OperationsMap
ParentCloseControl TimerArmed TickInFlight Closing Closed Failed AcceptedResolveReturned
AcceptedRejectReturned SettlementProbeArmed SettlementFaultArmed""".split()
OPERATION_FIELDS = ["format=1", "winner", "operation_closed", "gate_matches_selected_operation",
                    "gate_phase", "gate_arrived", "gate_released", "gate_resumed", "core_waiters", "core_work"]

# Closed scenarios from the committed independent consumer. Values classify transport
# only; the predicates below are fixed Lab expectations, never producer calculations.
SCENARIOS = {
    "full-waiters": {"ordinary-full32": "native", "facade-full32": "facade",
                     "parent-close-while-full": "native", "parent-facade": "facade"},
    "settling-reentry": {"ordinary-full32": "native", "facade-full32": "facade",
                         "resolver-reentry-facade": "facade", "resolver-reentry-native": "native"},
    "terminal-cancel": {"terminal-after-cancel": "operation"},
    "terminal-success": {"terminal-after-cancel": "operation"},
    "terminal-domain": {"terminal-after-cancel": "operation"},
    "claim-rollback": {"claim-rollback": "native"},
    "bytes-scratch": {"bytes-full-scratch-returned": "native"},
    "source-stop": {"source-before-stop": "native", "source-after-stop": "native"},
    "state-entered": {"state-entered": "native", "state-observed-values": "vector"},
    "fanout-state": {"partial-fanout-before": "native", "partial-fanout-after": "native"},
    "fanout-events": {"partial-fanout-before": "native", "partial-fanout-after": "native"},
    "operations-capacity": {"operations-full8": "native"},
    "subscriptions-capacity": {"subscriptions-full8": "native"},
    "state-staging": {"state-staging-before": "native", "state-staging-after": "native"},
    "event-atomic": {"event-six-tickets": "native", "event-atomic-after": "native"},
    "event-entered": {"event-entered-full8": "native"},
    "nonnull-owned-error": {"owned-error-before": "native", "owned-error-after": "native"},
    "mixed-waiters-engine-close": {"mixed-full32": "native", "engine-request-effective": "native",
        "mixed-parent-close": "native", "mixed-parent-facade": "facade", "mixed-closed-retry": "one"},
    "pending-sub-close-denied": {"sub-stop-before-observer": "native", "sub-closed-retry": "one"},
    "result-capacity-retry": {"result-capacity-rejected": "native", "result-capacity-retry": "one"},
    "after-guard": {"after-guard-consumed": "native", "after-guard-facade": "facade"},
    "dropped-promise": {"dropped-waiter-held": "native"},
    "partial-open": {"partial-open-failed": "native", "partial-open-physical": "native"},
    "worker-env-exit": {"worker-gate-held": "native", "worker-exit-request": "native"},
    "fault-before-guard": {"fault-residual": "native", "fault-facade": "facade",
        "fault-settlement-counts": "vector", "fault-close-rejected": "one",
        "parent-fault-residual": "native", "worker-exit-request": "native"},
    "fault-after-accepted": {"fault-residual": "native", "fault-facade": "facade",
        "fault-settlement-counts": "vector", "fault-close-rejected": "one",
        "parent-fault-residual": "native", "worker-exit-request": "native"},
}
SCENARIOS.update(COMPLETION_SCENARIOS)
SCENARIOS.update(ADMISSION_SCENARIOS)
SCENARIOS.update(DIAGNOSTIC_SCENARIOS)
SCENARIOS.update(LISTENER_SCENARIOS)
SCENARIOS.update(MEMORY_SCENARIOS)
SCENARIOS.update(CAPACITY_STREAM_SCENARIOS)
SCENARIOS.update({name:{} for name in IDENTITY_SCENARIOS})
WORKER_CASES = {"worker-env-exit", "fault-before-guard", "fault-after-accepted"}
GATED_CASES = {"full-waiters", "settling-reentry", "terminal-cancel", "terminal-success",
    "terminal-domain", "claim-rollback", "bytes-scratch", "operations-capacity",
    "mixed-waiters-engine-close", "pending-sub-close-denied", "result-capacity-retry",
    "after-guard", "dropped-promise", "fault-before-guard", "fault-after-accepted"}
GATED_CASES.update(COMPLETION_GATED)
GATED_CASES.update(ADMISSION_GATED)
GATED_CASES.update(DIAGNOSTIC_GATED)
GATED_CASES.update(MEMORY_GATED)
ZERO_OWNERS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 18, 19, 20, 21, 22,
               23, 24, 25, 26, 28, 29, 35, 37, 77)
PAIRS = (33, 38, 40, 42, 44, 46, 48, 50, 52)
OBSERVER_LABELS = {"observer-local": "local", "observer-process": "process",
                   "observer-process-repeat": "process"}


def _mapping(names, offset=0):
    return {str(index + offset): name for index, name in enumerate(names)}


def validate_contracts(contracts):
    """Require the public layouts this oracle actually understands; no disk imports."""
    try:
        runtime = contracts["runtime-frame-layout.json"]
        test = contracts["test-frame-layout.json"]
        observer = contracts["observer-layout.json"]
        facade = contracts["facade-frame-layout.json"]
        checks = [runtime == _mapping(RUNTIME_FIELDS), test["fields"] == _mapping(TEST_FIELDS, 54),
            test["native_prefix_length"] == 54, test["test_length"] == 48,
            test["total_length"] == 178, test["legacy_total_length"] == 156,
            test["hook_entry_offset"] == 102, test["hook_entry_length"] == 54,
            test["operation_fields"] == OPERATION_FIELDS,
            observer["format"] == 1, observer["length"] == 178,
            observer["unchanged_prefix"] == 156, observer["local_offset"] == 156,
            observer["process_offset"] == 168, observer["local"] == _mapping(LOCAL_FIELDS, 156),
            observer["process"] == _mapping(PROCESS_FIELDS, 168),
            facade["format"] == 1, facade["length"] == 15, facade["fields"] == FACADE_FIELDS]
        return [] if all(checks) else ["public companion layout differs from this independent oracle"]
    except (KeyError, TypeError):
        return ["missing or malformed explicit public companion layouts"]


def _labels(case):
    labels = {**SCENARIOS[case], "physical-closed": "native", "case-complete": "one"}
    if case in WORKER_CASES:
        labels.update({"worker-hook-entry": "hook", "worker-exit-code": "zero"})
    else:
        labels["facade-closed"] = "facade"
        if case != "partial-open":
            labels["open"] = "native"
    if case in GATED_CASES:
        labels.update({"work-held": "native", "operation-held": "operation"})
    return labels


def _frame_error(values, kind):
    if not isinstance(values, list) or any(type(v) is not int or abs(v) > MAX_SAFE for v in values):
        return "not a safe integer array"
    if kind == "vector":
        return None
    if kind in ("one", "zero"):
        return None if values == ([1] if kind == "one" else [0]) else "wrong scalar marker"
    length = {"native": 178, "facade": 15, "operation": 10, "hook": 54, "local": 12, "process": 10, "bootstrap": 16, "delivery": 8, "memory": 27}[kind]
    if len(values) != length or any(v < 0 for v in values) or kind != "process" and values[0] != 1:
        return "wrong length, format or negative counter"
    if kind == "native":
        if values[54] != 1 or values[156] != 1 or values[55] not in (0, 1, 2):
            return "unknown native/observer format or read mode"
        if any(values[i] != 0 for i in (158, 159, 160, 161, 169, 170)):
            return "instrumented gateway reported illegal or unscoped API attempts"
    if kind == "local" and any(values[i] != 0 for i in (2, 3, 4, 5)) or kind == "process" and any(values[i] != 0 for i in (1, 2)):
        return "observer segment reported illegal or unscoped API attempts"
    return None


def _predicates(case, frames):
    problems = []
    def need(ok, reason):
        if not ok:
            problems.append(reason)
    def equal(label, expected):
        need(all(frames[label][i] == value for i, value in expected.items()), label + ": values differ")
    def delta(before, after, expected):
        need(all(frames[after][i] - frames[before][i] == value for i, value in expected.items()), after + ": ownership delta differs")

    final = frames["physical-closed"]
    equal("physical-closed", {1: 3, 16: 1, 17: 1, 40: 1, 41: 1, 44: 1, 45: 1, 55: 2,
                               **{i: 0 for i in ZERO_OWNERS}, **{i: (2 if case in TWO_GENERATIONS else 1) for i in range(65, 71)}})
    need(all(final[i] == final[i + 1] for i in PAIRS), "physical cumulative owners are unpaired")
    need(0 < final[71] < final[72] < final[73] < final[75] < final[76] and
         0 < final[74] < final[75], "physical join does not include TLS/executor completion")
    need(all(final[i] > 0 for i in (62, 63, 64, 157)), "missing actual thread/API witnesses")
    need(final[162] == final[163], "null-env wake owner is unpaired")
    if "observer-local" in frames:
        need(frames["observer-local"] == final[156:168], "observer local segment differs from stable physical receipt")
    # Process counters are live observations, not stable history or per-runtime totals.
    if case not in WORKER_CASES:
        equal("facade-closed", {9: 1, 10: 0, **{i: 0 for i in (1, 2, 3, 4, 5, 6, 7, 13, 14)}})
    else:
        equal("physical-closed", {27: 1, 58: 1, 59: 1, 60: 1, 91: 1, 92: 1, 93: 1, 166: 1, 167: 1})
        need(final[165] > 0, "actual async cleanup deleted no reference")
        need(frames["worker-hook-entry"] == final[102:156], "hook entry differs from actual archived hook snapshot")
        # Hook occupancy is recorded as observed; exit-request fullness is not imposed on it.

    gate_label = "worker-gate-held" if case == "worker-env-exit" else "work-held" if case in GATED_CASES else None
    if gate_label:
        gate = frames[gate_label]
        phase = 2 if case in ("terminal-success", "terminal-domain", "after-guard",
                              "fault-before-guard", "fault-after-accepted") else 1
        equal(gate_label, {14: 1, 17: 0, 55: 1, 56: phase, 57: 1, 58: 1, 59: 0, 60: 0, 65: 1, 69: 0})
        need(gate[13] >= 1 and gate[62] > 0 and gate[63] > 0 and gate[62] != gate[63], "held work lacks distinct live owner/business threads")
        if case in GATED_CASES:
            equal("operation-held", {3: 1, 4: phase, 5: 1, 6: 0})
    if case in ("full-waiters", "settling-reentry"):
        equal("ordinary-full32", {11: 32, 19: 32})
        equal("facade-full32", {1: 32, 2: 0})
    if case == "full-waiters":
        equal("parent-close-while-full", {11: 32, 14: 1, 17: 0})
        equal("parent-facade", {5: 1, 8: 1, 9: 0})
    elif case == "settling-reentry":
        equal("resolver-reentry-facade", {1: 32, 2: 1})
    elif case.startswith("terminal-"):
        equal("terminal-after-cancel", {1: {"terminal-cancel": 3, "terminal-success": 1, "terminal-domain": 2}[case]})
    elif case == "claim-rollback":
        equal("claim-rollback", {11: 0, 19: 0, 85: 1, 86: 1})
    elif case == "bytes-scratch":
        equal("bytes-full-scratch-returned", {3: 0, 4: 4, 10: 4096, 97: 1})
        need(frames["bytes-full-scratch-returned"][52] == frames["bytes-full-scratch-returned"][53], "scratch was not returned")
    elif case == "source-stop":
        equal("source-before-stop", {6: 1, 77: 1})
        need(frames["source-before-stop"][8] > 0, "missing acquired source")
        equal("source-after-stop", {6: 0, 8: 0, 77: 0})
        delta("source-before-stop", "source-after-stop", {80: 1})
    elif case == "state-entered":
        equal("state-entered", {7: 2, 9: 1})
        need(frames["state-observed-values"] == [2, 4], "state entered/latest sequence differs")
    elif case in ("fanout-state", "fanout-events"):
        delta("partial-fanout-before", "partial-fanout-after", {33: 1, 34: 1, 83: 1})
    elif case == "operations-capacity":
        equal("operations-full8", {4: 8, 10: 0})
    elif case == "subscriptions-capacity":
        equal("subscriptions-full8", {5: 8, 6: 0, 7: 0})
    elif case == "state-staging":
        for label in ("state-staging-before", "state-staging-after"):
            equal(label, {7: 4, 10: 4096})
        delta("state-staging-before", "state-staging-after", {33: 0, 34: 0})
    elif case == "event-atomic":
        equal("event-six-tickets", {6: 6})
        equal("event-atomic-after", {6: 6, 7: 0, 8: 0})
        delta("event-six-tickets", "event-atomic-after", {33: 0})
    elif case == "event-entered":
        equal("event-entered-full8", {6: 8, 9: 1})
    elif case == "nonnull-owned-error":
        delta("owned-error-before", "owned-error-after", {33: 1, 34: 1, 35: 0, 83: 1})
    elif case == "mixed-waiters-engine-close":
        equal("mixed-full32", {11: 32, 19: 32, 13: 1, 77: 1})
        equal("mixed-parent-close", {11: 32, 13: 1, 77: 1})
        equal("mixed-parent-facade", {5: 1, 9: 0})
    elif case == "pending-sub-close-denied":
        equal("sub-stop-before-observer", {11: 32, 77: 1})
    elif case == "result-capacity-retry":
        equal("result-capacity-rejected", {11: 32, 19: 32})
    elif case == "after-guard":
        equal("after-guard-consumed", {11: 0, 19: 0, 85: 1, 87: 0, 88: 1})
        equal("after-guard-facade", {10: 0})
    elif case == "dropped-promise":
        equal("dropped-waiter-held", {11: 1, 19: 1, 13: 1})
    elif case == "partial-open":
        equal("partial-open-failed", {44: 1, 46: 0, 50: 0, 90: 1})
        equal("partial-open-physical", {1: 3, 20: 0, 21: 0, 24: 0, 25: 0, 26: 0,
            40: 1, 41: 1, 42: 1, 43: 1, 44: 1, 45: 1, 46: 0, 47: 0, 50: 0, 55: 2, 65: 0})
    elif case == "worker-env-exit":
        equal("worker-exit-request", {4: 8, 5: 3, 6: 8, 7: 1, 10: 4096, 11: 32, 19: 32, 77: 1})
        need(frames["worker-exit-request"][8] > 0, "exit request lacks real source")
    elif case in ("fault-before-guard", "fault-after-accepted"):
        before = case == "fault-before-guard"
        equal("fault-residual", {11: int(before), 13: 1, 14: 1, 17: 0, 19: int(before),
            58: 1, 59: 0, 60: 0, 85: int(before), 87: int(before), 88: 0})
        equal("fault-facade", {1: 0, 2: 0, 6: 0, 7: 0, 9: 0, 10: 1, 11: int(not before), 12: 0, 13: 0, 14: 0})
        equal("parent-fault-residual", {13: 1, 14: 1, 55: 0})
        need(frames["parent-fault-residual"][1] != 3, "fault residual misreported as closed")
        need(frames["fault-settlement-counts"] == ([0, 1] if before else [1, 0]), "fault settled incorrectly or more than once")
    if case in COMPLETION_SCENARIOS:
        problems.extend(completion_predicates(case, frames))
    problems.extend(admission_predicates(case, frames))
    problems.extend(diagnostic_predicates(case, frames))
    if case in LISTENER_SCENARIOS:problems.extend(listener_predicates(frames))
    if case in CAPACITY_STREAM_SCENARIOS:problems.extend(capacity_stream_predicates(case, frames))
    if case in MEMORY_SCENARIOS:memory_predicates(case,frames,need,equal,delta)
    return problems


def parse_controlled(raw, *, nonce, pid, case, route, contracts):
    """Validate one scenario's captured log; this function never runs device commands."""
    result = {"status": "unsupported", "case": case, "route": route, "nonce": nonce,
              "pid": int(pid) if isinstance(pid, str) and pid.isdigit() else None,
              "frames": {}, "failures": [], "problems": [], "lines": [], "certifies_c07": False,
              "scope": "one independently asserted controlled scenario; no matrix-group inference"}
    if route not in ("c", "cpp", "rust") or case not in SCENARIOS or case in IDENTITY_SCENARIOS:
        result["problems"] = ["unsupported route layout or unimplemented controlled scenario"]
        return result
    problems = result["problems"]
    problems.extend(validate_contracts(contracts))
    if case in ADMISSION_SCENARIOS:
        problems.extend(admission_contracts(contracts))
    if case in MEMORY_SCENARIOS:
        try:memory_contracts(contracts)
        except (KeyError,TypeError,ValueError) as error:problems.append("memory contract: "+str(error))
    if case in LISTENER_SCENARIOS:
        layout=contracts.get("subscription-state-layout.json",{})
        if layout.get("format")!=1 or layout.get("length")!=4 or layout.get("fields")!={"0":"Format","1":"Closing","2":"Closed","3":"ListenerRetained"}:
            problems.append("missing/incompatible actual subscription-record contract")
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", nonce):
        problems.append("invalid explicit nonce")
    if result["pid"] is None or result["pid"] <= 0:
        problems.append("probe process absent or non-unique")
    if problems:
        result["status"] = "failed"
        return result
    required = _labels(case)
    expected = {**required, **OBSERVER_LABELS}
    lines = [line for line in raw.splitlines() if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(nonce) + r"(?![A-Za-z0-9_-])", line)]
    result["lines"] = lines
    if any(len(line.split()) < 3 or line.split()[2] != pid for line in lines):
        problems.append("nonce/PID binding mismatch")
    frames = result["frames"]
    begins, ends = [], []
    for line in lines:
        if "PROBE_FAILED " + nonce + " " in line:
            result["failures"].append(line)
        for marker, target in (("CONTROLLED_BEGIN", begins), ("CONTROLLED_COMPLETE", ends)):
            prefix = marker + " " + nonce + " "
            if prefix in line:
                target.append(line.split(prefix, 1)[1].strip())
        prefix = "CONTROLLED_CASE " + nonce + " "
        if prefix not in line:
            continue
        try:
            label, encoded = line.split(prefix, 1)[1].split(" ", 1)
            values = json.loads(encoded)
            if label not in expected or label in frames:
                problems.append("unknown or duplicate observation: " + label)
                continue
            error = _frame_error(values, expected[label])
            if error:
                problems.append(label + ": " + error)
            frames[label] = values
        except (ValueError, TypeError):
            problems.append("malformed or truncated observation transport")
    if len(begins) > 1 or begins and begins != [case] or len(ends) > 1 or ends and ends != [case]:
        problems.append("case begin/end mismatch")
    if ends:
        if begins != [case]:
            problems.append("missing exact case begin")
        for marker in ("PROBE_STARTED", "PROBE_PAGE_READY", "PROBE_FINISHED"):
            if sum(re.search(re.escape(marker + " " + nonce) + r"(?:\s|$)", line) is not None for line in lines) != 1:
                problems.append("missing/duplicate " + marker)
        if not set(required).issubset(frames):
            problems.append("missing scenario observations: " + ", ".join(sorted(set(required) - set(frames))))
        if not problems:
            problems.extend(_predicates(case, frames))
    result["status"] = "failed" if problems or result["failures"] else "passed" if ends else "incomplete"
    if result["status"] == "passed":
        final = frames["physical-closed"]
        result["napi"] = {"scope": "instrumented composed gateway; Rust macro/import evidence is separate",
            "null_wake": "observed-and-paired" if final[162] > 0 else "unobserved",
            "null_finalizer": "observed" if final[164] > 0 else "unobserved",
            "stable_local": final[156:168], "live_process": final[168:178]}
    return result
