"""Independent observations for actual Delivery leases and generation admission."""
BOOTSTRAP_FIELDS = """Format OpenAttempts IdentityMatched AbiRejected ProfileRejected ArtifactRejected
Reservations ContextsCreated EnginesCreated WorkerStarted RefCreated RefDeleted TsfnCreated
TsfnReleaseAccepted HookAdded HookRemoved""".split()
DELIVERY_FIELDS = "Format Armed Held Entered Released Takes Invokes Discards".split()
SCENARIOS = {
    "delivery-and-handle-admission": {
        "bootstrap-before": "bootstrap", "bootstrap-open": "bootstrap", "bootstrap-final": "bootstrap",
        "delivery-before-assert": "delivery", "core-before-assert": "native",
        "callback-count-before-assert": "vector", "delivery-held": "delivery",
        "state-replaced": "native", "delivery-invoked": "delivery", "state-values": "vector",
        "stop-delivery-held": "delivery", "stop-release-return": "delivery", "stop-preentry": "vector",
        "after-engine-close": "native", "after-engine-close-facade": "facade",
        "handle-baseline": "native", "handle-after": "native", "handle-rejections": "vector",
        "foreign-handle": "one"},
    "engine-generation": {"generation-close-requested": "native", "generation-close-facade": "facade",
        "generation-settling": "facade", "generation-settling-native": "native",
        "generation-reopened": "native", "generation-old-close": "native"},
}
GATED = {"engine-generation"}
TWO_GENERATIONS = set(SCENARIOS)


def validate_contracts(contracts):
    try:
        bootstrap = contracts["bootstrap-totals-layout.json"]
        delivery = contracts["ports-layout.json"]["delivery"]
        valid = (bootstrap["format"] == 1 and bootstrap["length"] == 16 and
            bootstrap["fields"] == {str(i): v for i, v in enumerate(BOOTSTRAP_FIELDS)} and
            delivery["format"] == 1 and delivery["length"] == 8 and
            delivery["fields"] == {str(i): v for i, v in enumerate(DELIVERY_FIELDS)})
        return [] if valid else ["public admission layout differs from independent oracle"]
    except (KeyError, TypeError):
        return ["missing explicit public bootstrap and Delivery layouts"]


def predicates(case, frames):
    problems = []
    def need(ok, reason):
        if not ok:
            problems.append(reason)
    def eq(label, expected):
        need(all(frames[label][i] == value for i, value in expected.items()), label + ": values differ")
    if case == "delivery-and-handle-admission":
        before, opened, final = (frames[k] for k in ("bootstrap-before", "bootstrap-open", "bootstrap-final"))
        delta = [opened[i] - before[i] for i in range(16)]
        need(all(delta[i] == 1 for i in (1, 2, 6, 7, 8, 9, 10, 12, 14)) and
             all(delta[i] == 0 for i in (0, 3, 4, 5, 11, 13, 15)), "actual bootstrap creation delta differs")
        need([final[i] - before[i] for i in range(16)] == [0,2,2,0,0,0,2,2,2,2,2,2,2,2,2,2],
             "two runtimes/two Engine generations did not pair real bootstrap events")
        for label in ("delivery-before-assert", "delivery-held"):
            need(frames[label] == [1,0,1,0,0,1,0,0], label + ": not one actual pre-entry lease")
        for label in ("core-before-assert", "state-replaced"):
            eq(label, {7:1, 9:0})
        need(frames["callback-count-before-assert"] == [0] and frames["state-values"] == [2],
             "held state was entered early or failed to retain only latest")
        need(frames["delivery-invoked"] == [1,0,0,0,1,1,1,0], "real Delivery was not invoked once")
        need(frames["stop-delivery-held"] == [1,0,1,0,0,2,1,0] and
             frames["stop-release-return"] == [1,0,1,0,1,2,1,0] and
             frames["stop-preentry"] == [1,0], "stop bypassed held lease or entered callback")
        eq("after-engine-close", {16:1,17:1,18:0,48:1,49:1,50:1,51:1,69:1,70:1})
        a,b = frames["handle-baseline"], frames["handle-after"]
        need(all(a[i] == b[i] for i in (*range(4,15),33,36)), "handle negatives admitted Core/provider work")
        need(frames["handle-rejections"] == [1,1,1,1,1], "missing exact five typed rejection results")
        eq("handle-baseline", {50:2,51:1,69:1,70:1})
    elif case == "engine-generation":
        eq("generation-close-requested", {13:1,14:1,17:0})
        eq("generation-settling", {2:1})
        eq("generation-reopened", {50:2,51:1,69:1,70:1})
        eq("generation-old-close", {11:0,19:0})
    return problems
