"""Kotlin-only C07 coverage; normal main-env applicability stays explicit.

A mapped scenario is not a result. Gaps remain blocked until independently
implemented and executed with this exact public companion candidate.
"""
from c07_kotlin_observations import SCENARIOS

GROUPS = {
 'identity': {'scenarios':('kotlin-admission',), 'gaps':('Six exact wrong-identity bootstrap/provider library substitutions and real bootstrap resource deltas remain required.',)},
 'getters-and-reentry': {'scenarios':('kotlin-getters',), 'gaps':()},
 'worker-and-domain': {'scenarios':('kotlin-terminal-success','kotlin-terminal-domain'), 'gaps':('Actual live owner/business/cleanup thread witnesses and genuine Kotlin computation/free source binding remain required.',)},
 'terminal-winner': {'scenarios':('kotlin-terminal-cancel','kotlin-terminal-success','kotlin-terminal-domain'), 'gaps':('Actual cancel/completion race with one legal winner and one free remains required.',)},
 'single-claim': {'scenarios':('kotlin-terminal-cancel','kotlin-terminal-success','kotlin-terminal-domain','kotlin-claim-rollback'), 'gaps':()},
 'result-transfer-failures': {'scenarios':('kotlin-after-guard','kotlin-getters','kotlin-fanout-allocation'), 'gaps':('Before-guard residual plus normal failed-runtime cleanup and accepted-resolver failure observations remain required.',)},
 'dropped-promise': {'scenarios':('kotlin-dropped-promise',), 'gaps':()},
 'operations': {'scenarios':('kotlin-operations-capacity',), 'gaps':('Retain all eight operation handles after terminal/unclaimed result before rejecting ninth admission.',)},
 'subscriptions': {'scenarios':('kotlin-subscriptions-capacity','kotlin-source-stop','kotlin-listeners'), 'gaps':('Explicit retained-wrapper listener field observations across source/pending/entered and close remain required.',)},
 'state': {'scenarios':('kotlin-state',), 'gaps':()},
 'event-fifo-and-atomic': {'scenarios':('kotlin-event-fifo-and-atomic',), 'gaps':()},
 'fanout-allocation': {'scenarios':('kotlin-fanout-allocation',), 'gaps':()},
 'state-staging-bytes': {'scenarios':('kotlin-state-staging-bytes','kotlin-memory-state-staging'), 'gaps':()},
 'event-outstanding': {'scenarios':('kotlin-event-fifo-and-atomic','kotlin-source-stop'), 'gaps':()},
 'source-stop': {'scenarios':('kotlin-source-stop','kotlin-listeners'), 'gaps':()},
 'retained-bytes-and-scratch': {'scenarios':('kotlin-bytes-scratch','kotlin-operations-capacity','kotlin-memory-retained-scratch'), 'gaps':()},
 'shared-waiters': {'scenarios':('kotlin-shared-waiters',), 'gaps':('Pending Engine/Subscription variants and value-only already-Closed observations remain required.',)},
 'request-before-observer': {'scenarios':('kotlin-shared-waiters',), 'gaps':('First close denied at32 must gate genuinely pending distinct Operation/Subscription/Engine and permit retry after drain.',)},
 'settling-reentry': {'scenarios':('kotlin-settling-reentry',), 'gaps':()},
 'listener-throw-close': {'scenarios':('kotlin-listeners',), 'gaps':()},
 'request-only-retirement': {'scenarios':('kotlin-request-only',), 'gaps':('Engine request-only generation retirement and old Engine close after reconnect remain required.',)},
 'generation-and-handles': {'scenarios':('kotlin-admission',), 'gaps':('Same-runtime Engine generation and typed malformed handle0..5 observations remain required; main-only profile cannot fabricate a second live foreign owner.',)},
 'runtime-close-full': {'scenarios':('kotlin-shared-waiters',), 'gaps':()},
 'env-exit-full': {'scenarios':('kotlin-admission','kotlin-shared-waiters'), 'gaps':('Bind main-env-only profile responsibility and actual Node-API observer/static ownership evidence; ordinary close is not a system env hook.',)},
 'route-ownership': {'scenarios':('kotlin-terminal-success','kotlin-terminal-domain','kotlin-fanout-allocation','kotlin-admission','kotlin-copies'), 'gaps':('Genuine Kotlin source/destructor/free inventory and actual NAPI observer binding remain required.',)},
}


def scenario_plan():
    selected={name for group in GROUPS.values() for name in group['scenarios']}
    if selected-set(SCENARIOS):raise ValueError('unimplemented Kotlin companion scenario')
    return tuple(name for name in SCENARIOS if name in selected)
