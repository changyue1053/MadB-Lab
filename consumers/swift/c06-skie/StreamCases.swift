import Foundation
import MadBSkie

@MainActor
final class LabDeliveryGate {
    private var entered = false
    private var entrance: CheckedContinuation<Void, Never>?
    private var release: CheckedContinuation<Void, Never>?

    func hold() async {
        entered = true
        entrance?.resume()
        entrance = nil
        await withCheckedContinuation { release = $0 }
    }
    func waitUntilEntered() async {
        if entered { return }
        await withCheckedContinuation { entrance = $0 }
    }
    func resume() { release?.resume(); release = nil }
}

@MainActor
func lateCallbackCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    let observationHandle = try owner.subscribeEvents()
    let gate = LabDeliveryGate()
    var delivered: [String] = []
    var reentrantStop = "Missing"
    var reentrantClose = "Missing"
    var reentrantSubscriptions = -1
    var order: [String] = []
    let collector = Task { @MainActor in
        try await observationHandle.collect { @MainActor event in
            switch event {
            case .data(let data): delivered.append(data.id)
            case .failure(let code): delivered.append("failure:" + code)
            }
            reentrantSubscriptions = Int(engine.stats().activeSubscriptions)
            do { try await observationHandle.awaitStopped(); reentrantStop = "UnexpectedSuccess" }
            catch { reentrantStop = failureCode(error) }
            do { try await owner.awaitClosed(); reentrantClose = "UnexpectedSuccess" }
            catch { reentrantClose = failureCode(error) }
            order.append("callback-entered")
            await gate.hold()
            order.append("callback-left")
        }
    }
    try engine.publish(value: payload(1, id: "first"))
    await gate.waitUntilEntered()
    do { try await observationHandle.collect { _ in }; throw LabFailure(description: "duplicate collector was admitted") }
    catch { try emit("duplicate_collector", failureCode(error)) }
    try emit("duplicate_preserved_original", engine.stats().activeSubscriptions == 1)
    try engine.publish(value: payload(1, id: "late"))
    observationHandle.requestStop()
    var stopReturned = false
    var stopStarted = false
    let stopper = Task { @MainActor in
        stopStarted = true
        try await observationHandle.awaitStopped()
        stopReturned = true
        order.append("stop-returned")
    }
    while !stopStarted { await Task.yield() }
    try emit("stop_returned_before_release", stopReturned)
    gate.resume()
    try await collector.value
    try await stopper.value
    try emit("delivery_order", order)
    try emit("reentrant_stop", reentrantStop)
    try emit("reentrant_close", reentrantClose)
    try emit("reentrant_query", reentrantSubscriptions)
    try emit("delivered", delivered)
    try emit("queued_after_stop", Int(engine.stats().queuedItems))
    try emit("retained_after_stop", Int(engine.stats().retainedBytes))
    try await emptyAfterClose(engine, owner: owner)

    let secondOwner = try MadBEngineHandle(expectedProfile: profile)
    let secondEngine = secondOwner.native
    let stoppedHandle = try secondOwner.subscribeEvents()
    try secondEngine.publish(value: sample())
    stoppedHandle.requestStop()
    var lateEntries = 0
    try await stoppedHandle.collect { @MainActor _ in lateEntries += 1 }
    try emit("stopped_before_collect", lateEntries)
    try await emptyAfterClose(secondEngine, owner: secondOwner)
}

@MainActor
func capacityCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    let eventsHandle = try owner.subscribeEvents()
    for _ in 0..<8 { try engine.publish(value: payload(1)) }
    try emit("event_items", Int(engine.stats().queuedItems))
    try emit("event_overflow", try caught { try engine.publish(value: payload(1)) })
    try emit("event_items_after_rejection", Int(engine.stats().queuedItems))
    eventsHandle.requestStop()
    try await eventsHandle.awaitStopped()

    let bytesObserverHandle = try owner.subscribeEvents()
    for _ in 0..<4 { try engine.publish(value: payload(1024)) }
    try emit("byte_limit", Int(engine.stats().retainedBytes))
    try emit("byte_overflow", try caught { try engine.publish(value: payload(1)) })
    try emit("bytes_after_rejection", Int(engine.stats().retainedBytes))
    bytesObserverHandle.requestStop()
    try await bytesObserverHandle.awaitStopped()

    let fanoutA = try owner.subscribeEvents()
    let fanoutB = try owner.subscribeEvents()
    for _ in 0..<4 { try engine.publish(value: payload(1)) }
    try emit("fanout_event_items", Int(engine.stats().queuedItems))
    try emit("fanout_event_overflow", try caught { try engine.publish(value: payload(1)) })
    try emit("fanout_items_after_rejection", Int(engine.stats().queuedItems))
    try await fanoutA.awaitStopped()
    try await fanoutB.awaitStopped()

    let host = BarrierHost(blocking: true)
    let operation = try engine.startOperation(value: payload(1024), host: host)
    let worker = Task { @MainActor in _ = try await MadBOperationHandle(operation).result() }
    await host.waitUntilEntered()
    let combinedHandle = try owner.subscribeEvents()
    for _ in 0..<3 { try engine.publish(value: payload(1024)) }
    try emit("combined_limit", Int(engine.stats().retainedBytes))
    try emit("combined_overflow", try caught { try engine.publish(value: payload(1)) })
    combinedHandle.requestStop()
    try await combinedHandle.awaitStopped()
    host.releaseCallback()
    try await worker.value

    let stateHandle = try owner.subscribeState()
    try engine.publish(value: payload(1, id: "old"))
    try engine.publish(value: payload(1, id: "latest"))
    try emit("state_slots", Int(engine.stats().queuedItems))
    var latest = "Missing"
        try await stateHandle.collect { @MainActor event in
        switch event {
        case .data(let data): latest = data.id
        case .failure(let code): latest = "failure:" + code
        }
        stateHandle.requestStop()
    }
    try await stateHandle.awaitStopped()
    try emit("state_latest", latest)

    let unusedHost = BarrierHost()
    var queuedOperations: [MadBSkie.Operation] = []
    for _ in 0..<8 { queuedOperations.append(try engine.startOperation(value: payload(1), host: unusedHost)) }
    try emit("operation_items", Int(engine.stats().activeOperations))
    try emit("operation_overflow", try caught { _ = try engine.startOperation(value: payload(1), host: unusedHost) })
    queuedOperations.forEach { $0.requestCancel() }
    try emit("unstarted_host_calls", unusedHost.observation().calls)
    var observers: [MadBSubscriptionHandle] = []
    for _ in 0..<8 { observers.append(try owner.subscribeEvents()) }
    try emit("observer_items", Int(engine.stats().activeSubscriptions))
    try emit("observer_overflow", try caught { _ = try owner.subscribeState() })
    for observer in observers { try await observer.awaitStopped() }
    try await emptyAfterClose(engine, owner: owner)
    try emit("bytes_after_close", Int(engine.stats().retainedBytes))
    try await waiterCapacityCase(profile)
}

@MainActor
func waiterCapacityCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    let host = BarrierHost(blocking: true)
    let operation = try engine.startOperation(value: payload(1), host: host)
    let workerWait = Task { @MainActor in _ = try await MadBOperationHandle(operation).result() }
    await host.waitUntilEntered()
    workerWait.cancel()
    do { try await workerWait.value; throw LabFailure(description: "cancelled operation waiter returned success") }
    catch { try require(failureCode(error) == "Cancelled", "unexpected operation waiter cancellation") }
    var rejected = 0
    var cancelled = 0
    var unexpected: [String] = []
    let waiters = (0..<33).map { _ in Task { @MainActor in
        do { try await owner.awaitClosed(); unexpected.append("premature-close") }
        catch {
            switch failureCode(error) {
            case "ResourceExhausted": rejected += 1
            case "Cancelled": cancelled += 1
            default: unexpected.append(failureCode(error))
            }
        }
    } }
    while rejected == 0 && unexpected.isEmpty { await Task.yield() }
    for waiter in waiters { waiter.cancel() }
    for waiter in waiters { await waiter.value }
    try require(unexpected.isEmpty, "waiter budget raised unexpected failure: \(unexpected)")
    try emit("waiter_items", 32)
    try emit("waiter_overflow", rejected)
    try emit("waiter_cancelled", cancelled)
    try emit("waiter_after_cancel", Int(engine.stats().activeWaiters))
    host.releaseCallback()
    try await emptyAfterClose(engine, owner: owner)
}

@MainActor
func enhancedAPICase(_ profile: String) async throws {
    // Exhaustive switches intentionally have no default. This must compile with
    // SKIE's actual native enum and sealed enum enhancements.
    let phases = Phase.allCases.map { phase in
        switch phase {
        case .open: "open"
        case .closing: "closing"
        case .closed: "closed"
        }
    }
    try emit("enum_cases", phases)
    switch onEnum(of: failureEvent(code: "BusinessRejected")) {
    case .data: throw LabFailure(description: "wrong sealed variant")
    case .failure(let failure): try emit("sealed_failure", failure.code)
    }
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    let observation = try engine.subscribeEvents()
    for sequence in 0..<3 { try engine.publish(value: sample(sequence: Int64(sequence))) }
    var observed = "Missing"
    var sequences: [String] = []
    for await event in observation.events {
        switch onEnum(of: event) {
        case .data(let data):
            observed = data.value.id
            sequences.append(data.value.sequence!.stringValue)
        case .failure(let failure): observed = "failure:" + failure.code
        }
        if sequences.count == 3 { observation.requestStop() }
    }
    try emit("flow_data", observed)
    try emit("flow_order", sequences)
    try await emptyAfterClose(engine, owner: owner)
}
