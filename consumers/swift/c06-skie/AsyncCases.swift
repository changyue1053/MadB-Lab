import Foundation
import MadBSkie

@MainActor
func asyncCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    let host = BarrierHost(replacement: true)
    let operation = try engine.startOperation(value: sample(), host: host)
    let result = try await MadBOperationHandle(operation).result()
    try emit("reverse_id", result.id)
    try emit("reverse_sequence", String(result.sequence!))
    try emit("reverse_bytes", result.bytes.map(Int.init))
    try emit("host_calls", host.observation().calls)
    try emit("host_on_main", host.observation().onMain)
    try emit("repeat_run", await operationFailure(operation))
    let invalid = try engine.startOperation(value: sample(), host: BarrierHost(invalidResult: true))
    try emit("async_error", await operationFailure(invalid))
    try await emptyAfterClose(engine, owner: owner)
    try emit("completed", Int(engine.stats().completedOperations))
}

@MainActor
func operationFailure(_ operation: MadBSkie.Operation) async -> String {
    do { _ = try await MadBOperationHandle(operation).result(); return "UnexpectedSuccess" }
    catch { return failureCode(error) }
}

@MainActor
func cancelCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    let neverCalled = BarrierHost()
    let queued = try engine.startOperation(value: sample(), host: neverCalled)
    queued.requestCancel()
    queued.requestCancel()
    try emit("before_start", await operationFailure(queued))
    try emit("before_start_calls", neverCalled.observation().calls)

    let waitingHost = BarrierHost(blocking: true)
    let waitingOperation = try engine.startOperation(value: sample(), host: waitingHost)
    var waitingResult = "Pending"
    let waiting = Task { @MainActor in
        do { _ = try await MadBOperationHandle(waitingOperation).result(); waitingResult = "Success" }
        catch { waitingResult = failureCode(error) }
    }
    await waitingHost.waitUntilEntered()
    waiting.cancel()
    await waiting.value
    try emit("cancel_wait", waitingResult)
    try emit("work_retained_after_wait_cancel", Int(engine.stats().activeOperations))
    waitingHost.releaseCallback()
    // Completion is a semantic condition. The runner watchdog reports a hang;
    // no elapsed duration is interpreted as proof that work completed.
    while engine.stats().activeOperations != 0 { await Task.yield() }
    try emit("work_completed_after_wait_cancel", Int(engine.stats().completedOperations))

    let host = BarrierHost(blocking: true)
    let running = try engine.startOperation(value: sample(), host: host)
    var runningResult = "Pending"
    let waiter = Task { @MainActor in
        do { _ = try await MadBOperationHandle(running).result(); runningResult = "Success" }
        catch { runningResult = failureCode(error) }
    }
    await host.waitUntilEntered()
    running.requestCancel()
    try emit("running_callback_retained", Int(engine.stats().activeOperations))
    host.releaseCallback()
    await waiter.value
    try emit("cancel_work", runningResult)
    try await emptyAfterClose(engine, owner: owner)
    try emit("cancelled", Int(engine.stats().cancelledOperations))
    try emit("active_after_cancel", Int(engine.stats().activeOperations))
    try await cancelBeforeAcknowledgementCase(profile)
}

@MainActor
func shutdownCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    let host = BarrierHost(blocking: true)
    let operation = try engine.startOperation(value: sample(), host: host)
    var operationResult = "Pending"
    let waiter = Task { @MainActor in
        do { _ = try await MadBOperationHandle(operation).result(); operationResult = "Success" }
        catch { operationResult = failureCode(error) }
    }
    await host.waitUntilEntered()
    let eventsHandle = try owner.subscribeEvents()
    for _ in 0..<8 { try engine.publish(value: payload(1)) }
    owner.requestClose()
    try emit("reject_after_close_request", try caught { _ = try engine.roundtrip(value: sample()) })
    try emit("closed_before_callback_returns", engine.stats().closed)
    try emit("callback_lease_before_return", Int(engine.stats().activeOperations))
    try emit("queued_after_close_request", Int(engine.stats().queuedItems))
    host.releaseCallback()
    await waiter.value
    try emit("late_result", operationResult)
    try await eventsHandle.awaitStopped()
    try await emptyAfterClose(engine, owner: owner)
    try await emptyAfterClose(engine, owner: owner)
    try emit("closed_after_drain", engine.stats().closed)
    try emit("retained_after_drain", Int(engine.stats().retainedBytes))

    let callbackOwner = try MadBEngineHandle(expectedProfile: profile)
    let callbackEngine = callbackOwner.native
    let callbackSubscription = try callbackOwner.subscribeEvents()
    let body = LabDeliveryGate()
    var closeOrder: [String] = []
    let collector = Task { @MainActor in
        try await callbackSubscription.collect { @MainActor _ in
            closeOrder.append("callback-entered")
            await body.hold()
            closeOrder.append("callback-left")
        }
    }
    try callbackEngine.publish(value: sample())
    await body.waitUntilEntered()
    callbackOwner.requestClose()
    var closeStarted = false
    var closeReturned = false
    let closer = Task { @MainActor in
        closeStarted = true
        try await callbackOwner.awaitClosed()
        closeReturned = true
        closeOrder.append("close-returned")
    }
    while !closeStarted { await Task.yield() }
    try emit("close_returned_before_body_release", closeReturned)
    body.resume()
    try await collector.value
    try await closer.value
    try await emptyAfterClose(callbackEngine, owner: callbackOwner)
    try emit("callback_close_order", closeOrder)
    try await cleanupAcknowledgementCase(profile, beforeAcknowledgement: false)
    try await cleanupAcknowledgementCase(profile, beforeAcknowledgement: true)
}

// This conformance-only gate pauses a real native completion handler. It never
// performs cleanup; the ordinary owner protocol must still drain the handler.
@MainActor
func cleanupAcknowledgementCase(_ profile: String, beforeAcknowledgement: Bool) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    if beforeAcknowledgement { try TestSupport.shared.armCompletionAcknowledgement(engine: engine) }
    else { try TestSupport.shared.armCompletionCleanup(engine: engine) }
    let operation = try engine.startOperation(value: payload(1), host: BarrierHost())
    var result = "Pending"
    let waiter = Task { @MainActor in
        do { _ = try await MadBOperationHandle(operation).result(); result = "Success" }
        catch { result = failureCode(error) }
    }
    while !TestSupport.shared.completionCleanupEntered(engine: engine) { await Task.yield() }
    try require(engine.stats().activeOperations == 1, "completion handler lost operation ownership before cleanup ACK")
    let prefix = beforeAcknowledgement ? "ack" : "cleanup"
    owner.requestClose()
    var closeReturned = false
    let closer = Task { @MainActor in try await owner.awaitClosed(); closeReturned = true }
    while engine.stats().activeWaiters < 2 && !closeReturned { await Task.yield() }
    try emit(prefix + "_close_before_release", closeReturned)
    try emit(prefix + "_operation_before_release", Int(engine.stats().activeOperations))
    TestSupport.shared.releaseCompletionCleanup(engine: engine)
    await waiter.value
    try await closer.value
    try emit(prefix + "_result", result)
    try await emptyAfterClose(engine, owner: owner)
    try emit(prefix + "_retained_after_drain", Int(engine.stats().retainedBytes))
}

@MainActor
func cancelBeforeAcknowledgementCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    try TestSupport.shared.armCompletionAcknowledgement(engine: engine)
    let operation = try engine.startOperation(value: payload(1), host: BarrierHost())
    var result = "Pending"
    let waiter = Task { @MainActor in
        do { _ = try await MadBOperationHandle(operation).result(); result = "Success" }
        catch { result = failureCode(error) }
    }
    while !TestSupport.shared.completionCleanupEntered(engine: engine) { await Task.yield() }
    waiter.cancel()
    await waiter.value
    try emit("ack_wait_cancel", result)
    try emit("ack_work_before_release", Int(engine.stats().activeOperations))
    TestSupport.shared.releaseCompletionCleanup(engine: engine)
    while engine.stats().activeOperations != 0 { await Task.yield() }
    try emit("ack_work_completed", Int(engine.stats().completedOperations))
    try emit("ack_work_cancelled", Int(engine.stats().cancelledOperations))
    try emit("ack_wait_retained", Int(engine.stats().retainedBytes))
    try await emptyAfterClose(engine, owner: owner)
}
