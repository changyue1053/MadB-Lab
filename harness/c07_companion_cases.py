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
        "scenarios": ("partial-open", "identity-positive", "identity-wrong-abi", "identity-wrong-profile", "identity-wrong-build"),
        "gaps": ("Matched ordinary HAR actual wrong-library rejection evidence remains required separately from companion owner counters.",),
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
    "operations": {"scenarios": ("operations-capacity", "operations-terminal-capacity"), "gaps": ()},
    "subscriptions": {
        "scenarios": ("subscriptions-capacity", "source-stop", "event-entered", "listener-lifetime"),
        "gaps": (),
    },
    "state": {
        "scenarios": ("state-entered", "delivery-and-handle-admission", "stream-isolation"),
        "gaps": (),
    },
    "event-fifo-and-atomic": {"scenarios": ("event-atomic", "state-entered", "stream-isolation"), "gaps": ()},
    "fanout-allocation": {"scenarios": ("fanout-state", "fanout-events"), "gaps": ()},
    "state-staging-bytes": {
        "scenarios": ("state-staging", "memory-state-staging"),
        "gaps": (),
    },
    "event-outstanding": {"scenarios": ("event-entered", "source-stop"), "gaps": ()},
    "source-stop": {
        "scenarios": ('source-stop', 'listener-stop-throw'),
        "gaps": (),
    },
    "retained-bytes-and-scratch": {
        "scenarios": ("bytes-scratch", "operations-capacity", "memory-full-scratch"),
        "gaps": (),
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


def assess_group(matrix_id, *, route, candidate_digest, run_id, observations, route_ownership=None, related_ordinary=None):
    """Assess controller-owned current-run observations, never a saved report.

    Each scenario envelope is {candidate_digest, run_id, observation}, where
    observation is the complete parse_controlled return value. The controller
    supplies fresh run_id and per-scenario nonce/PID bindings after real execution.
    An optional ordinary-baseline observation is preserved elsewhere and cannot
    silently fulfill a controlled requirement through this function.
    """
    if route == "kotlin":
        from c07_kotlin_cases import GROUPS as KOTLIN_GROUPS
        groups, supported = KOTLIN_GROUPS, ("kotlin",)
    else:
        groups, supported = GROUPS, SUPPORTED_ROUTES
    if matrix_id not in groups:
        raise ValueError("unknown C07 companion matrix group: " + matrix_id)
    group = groups[matrix_id]
    if route in SUPPORTED_ROUTES and matrix_id in ("worker-and-domain", "route-ownership"):
        envelope = route_ownership if isinstance(route_ownership, dict) else {}
        evidence = envelope.get("observation", {})
        review = evidence.get("source_review", {})
        source_bound = (envelope.get("candidate_digest") == candidate_digest and envelope.get("run_id") == run_id
            and evidence.get("candidate_digest") == candidate_digest and evidence.get("route") == route
            and evidence.get("status") == "bound" and review.get("status") == "bound"
            and review.get("route") == route and review.get("variant") == "test"
            and isinstance(evidence.get("producer_revision"), str) and bool(evidence["producer_revision"])
            and review.get("producer_revision") == evidence["producer_revision"]
            and isinstance(review.get("inventory_sha256"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", review["inventory_sha256"]) is not None)
        if source_bound:group = dict(group, gaps=())
    if route == "kotlin" and matrix_id in ("worker-and-domain", "route-ownership", "generation-and-handles", "env-exit-full"):
        envelope = route_ownership if isinstance(route_ownership, dict) else {}
        evidence = envelope.get("observation", {})
        review = evidence.get("source_review", {})
        current = (envelope.get("candidate_digest") == candidate_digest and envelope.get("run_id") == run_id and
            evidence.get("candidate_digest") == candidate_digest and evidence.get("route") == route)
        source_bound = (current and evidence.get("status") == "bound" and review.get("status") == "bound" and
            review.get("variant") == "test" and isinstance(evidence.get("producer_revision"), str) and bool(evidence["producer_revision"]) and
            isinstance(evidence.get("inventory_sha256"), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", evidence["inventory_sha256"]) is not None)
        applicability = evidence.get("applicability", {})
        applicable = (current and applicability.get("status") == "bound" and applicability.get("execution_domain") == "main-env-only" and
            applicability.get("profile_id") == "c07-kotlin-arkts-aarch64-ohos23-test")
        if (matrix_id in ("worker-and-domain", "route-ownership") and source_bound or
            matrix_id == "generation-and-handles" and applicable or matrix_id == "env-exit-full" and applicable and source_bound):
            group = dict(group, gaps=())
    if matrix_id == "identity" and route in (*SUPPORTED_ROUTES, "kotlin"):
        envelope = related_ordinary if isinstance(related_ordinary, dict) else {}
        evidence = envelope.get("observation", {})
        pair = evidence.get("pair", {})
        if (envelope.get("candidate_digest") == candidate_digest and envelope.get("run_id") == run_id and
            evidence.get("status") == pair.get("status") == "bound" and evidence.get("route") == route and
            evidence.get("companion_candidate_digest") == pair.get("companion_candidate_digest") == candidate_digest and
            evidence.get("ordinary_candidate_digest") == pair.get("ordinary_candidate_digest") and
            isinstance(evidence.get("report"), dict) and re.fullmatch(r"sha256:[0-9a-f]{64}", evidence["report"].get("sha256", ""))):
            group = dict(group, gaps=())
    return assess_mapped_group(matrix_id, group, supported, route=route, candidate_digest=candidate_digest,
                              run_id=run_id, observations=observations)


def assess_mapped_group(matrix_id, group, supported, *, route, candidate_digest, run_id, observations):
    result = {"status": "blocked", "reason": "", "matrix_id": matrix_id,
              "scenarios": list(group["scenarios"]), "passed_scenarios": [],
              "missing_scenarios": [], "gaps": list(group["gaps"]), "problems": []}
    if route not in supported:
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
