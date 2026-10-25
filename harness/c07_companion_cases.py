"""C07 companion group coverage over independently implemented Lab scenarios.

This is a finite execution map, not a relaxation of MATRIX.md. A group with any
listed gap remains blocked even when every available scenario passes. Results
must belong to this candidate and controller run; retained development reports
cannot satisfy this entry point.
"""
import re

from c07_companion_observations import SCENARIOS

SCENARIO_TIMEOUT_MS = 50000
SUPPORTED_ROUTES = ("c", "cpp", "rust")

# A scenario may contribute to several groups but runs only once per candidate.
# The expected behavior remains verbatim in the corresponding registered cases.
GROUPS = {
    "identity": {
        "scenarios": ("partial-open",),
        "gaps": ("Actual wrong-artifact, wrong-ABI and wrong-profile DSO replacements with exact bootstrap error/stage and unchanged pre-admission business/ref/TSFN/worker totals are not wired.",),
    },
    "getters-and-reentry": {
        "scenarios": ('getters-observed',),
        "gaps": (),
    },
    "worker-and-domain": {
        "scenarios": ("terminal-success", "terminal-domain", "live-cleanup-threads"),
        "gaps": ("Bind computation/free to the actual route implementation and record the required live cleanup-thread witness separately from historical thread IDs.",),
    },
    "terminal-winner": {
        "scenarios": ('terminal-cancel', 'terminal-success', 'terminal-domain', 'cancel-terminal-race'),
        "gaps": (),
    },
    "single-claim": {
        "scenarios": ("terminal-cancel", "terminal-success", "terminal-domain", "claim-rollback", "result-capacity-retry"),
        "gaps": (),
    },
    "result-transfer-failures": {
        "scenarios": ('fault-before-guard', 'after-guard', 'fault-after-accepted', 'nonnull-owned-error', 'getters-observed'),
        "gaps": (),
    },
    "dropped-promise": {"scenarios": ("dropped-promise",), "gaps": ()},
    "operations": {"scenarios": ("operations-capacity",), "gaps": ()},
    "subscriptions": {
        "scenarios": ("subscriptions-capacity", "source-stop", "event-entered"),
        "gaps": ("Explicit listener-reference lifetime observations across source-held, pending and entered phases, followed by explicit-close release, are not yet wired.",),
    },
    "state": {
        "scenarios": ("state-entered", "delivery-and-handle-admission"),
        "gaps": (),
    },
    "event-fifo-and-atomic": {"scenarios": ("event-atomic", "state-entered"), "gaps": ()},
    "fanout-allocation": {"scenarios": ("fanout-state", "fanout-events"), "gaps": ()},
    "state-staging-bytes": {
        "scenarios": ("state-staging",),
        "gaps": ("Record exact staging/retained peaks and route allocation observations separately; the existing pre/post 4096-byte checkpoint alone does not establish all peak measurements.",),
    },
    "event-outstanding": {"scenarios": ("event-entered", "source-stop"), "gaps": ()},
    "source-stop": {
        "scenarios": ('source-stop', 'listener-stop-throw'),
        "gaps": (),
    },
    "retained-bytes-and-scratch": {
        "scenarios": ("bytes-scratch", "operations-capacity"),
        "gaps": ("Record model/UTF-conversion overhead separately from the retained-byte ledger without treating scratch lease count as a byte peak.",),
    },
    "shared-waiters": {
        "scenarios": ("full-waiters", "mixed-waiters-engine-close", "pending-sub-close-denied", "result-capacity-retry"),
        "gaps": (),
    },
    "request-before-observer": {
        "scenarios": ('full-waiters', 'mixed-waiters-engine-close', 'pending-sub-close-denied', 'distinct-operation-denied'),
        "gaps": (),
    },
    "settling-reentry": {"scenarios": ("settling-reentry",), "gaps": ()},
    "listener-throw-close": {
        "scenarios": ('listener-stop-throw',),
        "gaps": (),
    },
    "request-only-retirement": {
        "scenarios": ("request-only-observed", "engine-generation"),
        "gaps": (),
    },
    "generation-and-handles": {
        "scenarios": ("delivery-and-handle-admission", "engine-generation"),
        "gaps": (),
    },
    "runtime-close-full": {"scenarios": ("full-waiters", "mixed-waiters-engine-close"), "gaps": ()},
    "env-exit-full": {"scenarios": ("worker-env-exit",), "gaps": ()},
    "route-ownership": {
        "scenarios": ("terminal-success", "terminal-domain", "operations-capacity", "subscriptions-capacity",
                      "nonnull-owned-error", "partial-open", "fault-before-guard", "fault-after-accepted", "worker-env-exit", "child-ownership-baseline"),
        "gaps": ("Bind the actual route implementation/destructor/free inventory, including Rust frontend evidence where applicable, and baseline-preserving child cleanup to the runtime-zero observations.",),
    },
}


def scenario_plan(route):
    """Return only implemented scenarios, once each, in consumer-defined order."""
    if route not in SUPPORTED_ROUTES:
        return ()
    selected = {scenario for group in GROUPS.values() for scenario in group["scenarios"]}
    unknown = selected - set(SCENARIOS)
    if unknown:
        raise ValueError("unimplemented companion scenario in group map: " + ", ".join(sorted(unknown)))
    return tuple(scenario for scenario in SCENARIOS if scenario in selected)


def assess_group(matrix_id, *, route, candidate_digest, run_id, observations):
    """Assess controller-owned current-run observations, never a saved report.

    Each scenario envelope is {candidate_digest, run_id, observation}, where
    observation is the complete parse_controlled return value. The controller
    supplies fresh run_id and per-scenario nonce/PID bindings after real execution.
    An optional ordinary-baseline observation is preserved elsewhere and cannot
    silently fulfill a controlled requirement through this function.
    """
    if matrix_id not in GROUPS:
        raise ValueError("unknown C07 companion matrix group: " + matrix_id)
    group = GROUPS[matrix_id]
    result = {"status": "blocked", "reason": "", "matrix_id": matrix_id,
              "scenarios": list(group["scenarios"]), "passed_scenarios": [],
              "missing_scenarios": [], "gaps": list(group["gaps"]), "problems": []}
    if route not in SUPPORTED_ROUTES:
        result["reason"] = "route requires an independently implemented companion layout and controller"
        return result
    if not isinstance(candidate_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_digest) or not isinstance(run_id, str) or not run_id:
        result.update(status="error", reason="missing exact candidate/current-run binding")
        return result
    failed, unusable = [], []
    for scenario in group["scenarios"]:
        envelope = observations.get(scenario)
        if envelope is None:
            result["missing_scenarios"].append(scenario)
            continue
        if not isinstance(envelope, dict) or envelope.get("candidate_digest") != candidate_digest or envelope.get("run_id") != run_id:
            result["problems"].append(scenario + ": observation belongs to another candidate or controller run")
            continue
        observed = envelope.get("observation")
        if not isinstance(observed, dict) or observed.get("case") != scenario or observed.get("route") != route:
            result["problems"].append(scenario + ": wrong scenario or route observation")
            continue
        status = observed.get("status")
        if status == "passed":
            if (not isinstance(observed.get("nonce"), str) or not observed["nonce"] or
                    type(observed.get("pid")) is not int or observed["pid"] <= 0 or
                    not isinstance(observed.get("frames"), dict) or not observed["frames"] or
                    observed.get("problems") != [] or observed.get("failures") != [] or
                    observed.get("certifies_c07") is not False):
                result["problems"].append(scenario + ": malformed successful scenario observation")
            else:
                result["passed_scenarios"].append(scenario)
        elif status == "failed":
            failed.append(scenario)
        elif status == "unsupported":
            result["missing_scenarios"].append(scenario)
        else:
            unusable.append(scenario)  # Incomplete/timeout/error never becomes a legal winner.
    if result["problems"] or unusable:
        result.update(status="error", reason="invalid or incomplete current-run observations: " +
                      "; ".join(result["problems"] + unusable))
    elif failed:
        result.update(status="failed", reason="actual controlled assertions failed: " + ", ".join(failed))
    elif result["missing_scenarios"]:
        result["reason"] = "required controlled scenarios were not executed: " + ", ".join(result["missing_scenarios"])
    elif group["gaps"]:
        result["reason"] = "available current-run observations do not close this requirement: " + " ".join(group["gaps"])
    elif not group["scenarios"]:
        result["reason"] = "no implemented controlled scenarios for this requirement"
    else:
        result.update(status="passed", reason="all independently mapped scenarios passed for this exact candidate and controller run")
    return result
