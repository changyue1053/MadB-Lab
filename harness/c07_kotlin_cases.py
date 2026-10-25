"""Kotlin-only C07 coverage; normal main-env applicability stays explicit.

A mapped scenario is not a result. Gaps remain blocked until independently
implemented and executed with this exact public companion candidate.
"""
from c07_kotlin_observations import SCENARIOS as NORMAL_SCENARIOS
from c07_kotlin_identity_observations import SCENARIOS as IDENTITY_SCENARIOS
SCENARIOS=tuple(NORMAL_SCENARIOS)+tuple(IDENTITY_SCENARIOS)

GROUPS = {
 'identity': {'scenarios':('kotlin-admission',)+tuple(IDENTITY_SCENARIOS), 'gaps':('Matched ordinary HAR six actual wrong-library rejection observations remain required separately from test admission/observer deltas.',)},
 'getters-and-reentry': {'scenarios':('kotlin-getters',), 'gaps':()},
 'worker-and-domain': {'scenarios':('kotlin-terminal-success','kotlin-terminal-domain','kotlin-live-threads'), 'gaps':('Actual live owner/business/cleanup thread witnesses and genuine Kotlin computation/free source binding remain required.',)},
 'terminal-winner': {'scenarios':('kotlin-terminal-cancel','kotlin-terminal-success','kotlin-terminal-domain','kotlin-cancel-race'), 'gaps':()},
 'single-claim': {'scenarios':('kotlin-terminal-cancel','kotlin-terminal-success','kotlin-terminal-domain','kotlin-claim-rollback','kotlin-cancel-race'), 'gaps':()},
 'result-transfer-failures': {'scenarios':('kotlin-after-guard','kotlin-getters','kotlin-fanout-allocation','kotlin-fault-before-guard','kotlin-fault-after-accepted'), 'gaps':()},
 'dropped-promise': {'scenarios':('kotlin-dropped-promise',), 'gaps':()},
 'operations': {'scenarios':('kotlin-operations-capacity','kotlin-terminal-capacity'), 'gaps':()},
 'subscriptions': {'scenarios':('kotlin-subscriptions-capacity','kotlin-source-stop','kotlin-listeners','kotlin-listener-lifetime'), 'gaps':()},
 'state': {'scenarios':('kotlin-state',), 'gaps':()},
 'event-fifo-and-atomic': {'scenarios':('kotlin-event-fifo-and-atomic',), 'gaps':()},
 'fanout-allocation': {'scenarios':('kotlin-fanout-allocation',), 'gaps':()},
 'state-staging-bytes': {'scenarios':('kotlin-state-staging-bytes','kotlin-memory-state-staging'), 'gaps':()},
 'event-outstanding': {'scenarios':('kotlin-event-fifo-and-atomic','kotlin-source-stop'), 'gaps':()},
 'source-stop': {'scenarios':('kotlin-source-stop','kotlin-listeners'), 'gaps':()},
 'retained-bytes-and-scratch': {'scenarios':('kotlin-bytes-scratch','kotlin-operations-capacity','kotlin-memory-retained-scratch'), 'gaps':()},
 'shared-waiters': {'scenarios':('kotlin-shared-waiters','kotlin-mixed-waiters','kotlin-distinct-close-denied'), 'gaps':()},
 'request-before-observer': {'scenarios':('kotlin-distinct-close-denied',), 'gaps':()},
 'settling-reentry': {'scenarios':('kotlin-settling-reentry',), 'gaps':()},
 'listener-throw-close': {'scenarios':('kotlin-listeners',), 'gaps':()},
 'request-only-retirement': {'scenarios':('kotlin-request-only','kotlin-generation-handles'), 'gaps':()},
 'generation-and-handles': {'scenarios':('kotlin-admission','kotlin-generation-handles'), 'gaps':('Bind explicit main-env-only applicability and Worker-first recoverable refusal; do not invent a live foreign managed owner.',)},
 'runtime-close-full': {'scenarios':('kotlin-shared-waiters','kotlin-mixed-waiters'), 'gaps':()},
 'env-exit-full': {'scenarios':('kotlin-admission','kotlin-shared-waiters'), 'gaps':('Bind main-env-only profile responsibility and actual Node-API observer/static ownership evidence; ordinary close is not a system env hook.',)},
 'route-ownership': {'scenarios':('kotlin-terminal-success','kotlin-terminal-domain','kotlin-fanout-allocation','kotlin-admission','kotlin-copies'), 'gaps':('Genuine Kotlin source/destructor/free inventory and actual NAPI observer binding remain required.',)},
}


def scenario_plan():
    selected={name for group in GROUPS.values() for name in group['scenarios']}
    if selected-set(SCENARIOS):raise ValueError('unimplemented Kotlin companion scenario')
    return tuple(name for name in SCENARIOS if name in selected)
