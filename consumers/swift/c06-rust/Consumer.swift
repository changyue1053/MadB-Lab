import Foundation
import Darwin

// All mutable Gate and Recorder fields are protected by their named lock. The
// unchecked conformance is limited to these test synchronization primitives.
final class Gate: @unchecked Sendable {
    private let condition = NSCondition()
    private var entered = false
    private var released = false
    func enterAndWait() {
        condition.lock(); defer { condition.unlock() }
        entered = true; condition.broadcast()
        let deadline = Date().addingTimeInterval(10)
        while !released { precondition(condition.wait(until: deadline), "callback release barrier timed out") }
    }
    func awaitEntered() {
        condition.lock(); defer { condition.unlock() }
        let deadline = Date().addingTimeInterval(10)
        while !entered { precondition(condition.wait(until: deadline), "callback entry barrier timed out") }
    }
    func release() { condition.lock(); released = true; condition.broadcast(); condition.unlock() }
}
final class Recorder: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [Value] = []
    func append(_ value: Value) -> Int { lock.withLock { storage.append(value); return storage.count } }
    var values: [Value] { lock.withLock { storage } }
}
final class CallbackHost: Host {
    let body: @Sendable (Value) throws -> Value
    init(_ body: @escaping @Sendable (Value) throws -> Value) { self.body = body }
    func transform(value: Value) throws -> Value { try body(value) }
}
final class RecordingSink: Sink {
    let recorder = Recorder()
    let gate: Gate?
    init(_ gate: Gate? = nil) { self.gate = gate }
    func onValue(value: Value) throws { if recorder.append(value) == 1 { gate?.enterAndWait() } }
}
actor Started {
    private var started = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    func signal() { started = true; let saved = waiters; waiters.removeAll(); for waiter in saved { waiter.resume() } }
    func wait() async { if !started { await withCheckedContinuation { waiters.append($0) } } }
}
func emit<T: Encodable>(_ name: String, _ value: T) {
    let encoder = JSONEncoder()
    let key = String(data: try! encoder.encode(name), encoding: .utf8)!
    let actual = String(data: try! encoder.encode(value), encoding: .utf8)!
    print("{\"check\":\(key),\"actual\":\(actual)}")
}
func must(_ condition: Bool, _ message: String) {
    if !condition { FileHandle.standardError.write(Data(("LAB assertion: " + message + "\n").utf8)); fatalError(message) }
}
func payload(_ sequence: Int64? = nil) -> Value {
    Value(id: "m1", sequence: sequence, text: "你好\0é", bytes: [0, 127, 128, 255], phase: .ready)
}
func emptyPayload(_ count: Int = 0) -> Value { Value(id: "", sequence: nil, text: "", bytes: Array(repeating: 0, count: count), phase: .ready) }
func errorName(_ error: any Error) -> String {
    guard let boundary = error as? BoundaryError else { return String(describing: type(of: error)) }
    switch boundary {
    case .InvalidArgument: return "InvalidArgument"
    case .Closing: return "Closing"
    case .Closed: return "Closed"
    case .Cancelled: return "Cancelled"
    case .ResourceExhausted: return "ResourceExhausted"
    case .ProfileMismatch: return "ProfileMismatch"
    case .CallbackFailure: return "CallbackFailure"
    case .WouldDeadlock: return "WouldDeadlock"
    case .AlreadyConsumed: return "AlreadyConsumed"
    }
}
func expectError(_ name: String, _ body: () throws -> Void) {
    do { try body() } catch { must(errorName(error) == name, "expected \(name), got \(error)"); return }
    preconditionFailure("expected \(name), but call succeeded")
}
func expectAsyncError(_ name: String, _ body: () async throws -> Void) async {
    do { try await body() } catch { must(errorName(error) == name, "expected \(name), got \(error)"); return }
    preconditionFailure("expected async \(name), but call succeeded")
}
func assertBaseline(_ engine: Engine) {
    let stats = engine.statistics()
    must(stats.queuedItems == 0 && stats.retainedBytes == 0 && stats.callbacksInFlight == 0 && stats.activeOperations == 0 && stats.activeSubscriptions == 0, "owner did not drain")
    must(stats.payloadsAdmitted == stats.payloadsReleased && stats.operationsCreated == stats.operationsReleased && stats.subscriptionsCreated == stats.subscriptionsReleased, "native ownership did not return to baseline")
    must(stats.workerExits == 1, "worker exit count differs")
}
func finish(_ engine: Engine, second: Bool = false, ownerName: String? = nil) async throws {
    engine.requestClose(); try await engine.awaitClosed(); assertBaseline(engine)
    emit(ownerName.map { "cleanup.\($0)-owner" } ?? (second ? "cleanup.second-owner" : "cleanup.owned-work"), 0)
}
func dataCase(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected)
    let value = try engine.roundtrip(value: payload())
    must(value == payload(), "record roundtrip differs")
    emit("data.id", value.id); emit("data.text", value.text); emit("data.null", value.sequence)
    emit("data.bytes", value.bytes)
    emit("data.minimum", String(try engine.roundtrip(value: payload(Int64.min)).sequence!))
    emit("data.maximum", String(try engine.roundtrip(value: payload(Int64.max)).sequence!))
    for phase: Phase in [.ready, .working, .done] { var item = payload(); item.phase = phase; must(try engine.roundtrip(value: item) == item, "phase differs") }
    emit("data.variants", 3); try await finish(engine)
}
func errorsCase(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected)
    expectError("ResourceExhausted") { _ = try engine.roundtrip(value: emptyPayload(1025)) }
    var operation: Operation? = try engine.startOperation(value: payload(), host: CallbackHost { _ in throw NSError(domain: "Lab", code: 17) })
    await expectAsyncError("CallbackFailure") { _ = try await operation!.result() }
    operation = nil
    engine.requestClose(); try await engine.awaitClosed()
    expectError("Closed") { _ = try engine.roundtrip(value: payload()) }
    emit("errors.callback", "CallbackFailure"); emit("errors.closed", "Closed"); emit("errors.payload", "ResourceExhausted")
    try await finish(engine)
}
func objectsCase(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected)
    var operation: Operation? = try engine.startOperation(value: payload(), host: CallbackHost { $0 })
    var alias = operation
    must(try await alias!.result() == payload(), "alias result differs")
    await expectAsyncError("AlreadyConsumed") { _ = try await operation!.result() }
    alias = nil; operation = nil
    must(engine.statistics().operationsReleased == 1, "aliases did not release exactly one native object")
    emit("objects.released", 1); emit("objects.second-result", "AlreadyConsumed"); try await finish(engine)
}
func asyncCase(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected)
    let caller = String(describing: pthread_self())
    let recorder = Recorder()
    var operation: Operation? = try engine.startOperation(value: payload(), host: CallbackHost { value in
        must(String(describing: pthread_self()) != caller, "callback did not use owner worker")
        must(try engine.roundtrip(value: value) == value, "reentrant query failed")
        var result = value; result.text += ":host"; _ = recorder.append(result); return result
    })
    let result = try await operation!.result(); operation = nil
    emit("async.text", result.text); emit("async.worker-distinct", recorder.values.count == 1)
    try await finish(engine)
}
func cancelCase(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected)
    let gate = Gate()
    var operation: Operation? = try engine.startOperation(value: payload(), host: CallbackHost { value in gate.enterAndWait(); return value })
    gate.awaitEntered()
    let preCancelled = Task { [operation] in
        withUnsafeCurrentTask { $0?.cancel() }
        return try await operation!.result()
    }
    do { _ = try await preCancelled.value; preconditionFailure("pre-cancelled waiter succeeded") }
    catch { must(error is CancellationError, "pre-cancelled waiter did not preserve Swift cancellation") }
    let started = Started()
    // Task owns its handle until cancellation has completed; it is not detached.
    let waiter = Task { [operation] in await started.signal(); return try await operation!.result() }
    await started.wait(); waiter.cancel()
    do { _ = try await waiter.value; preconditionFailure("cancelled waiter succeeded") } catch { must(error is CancellationError, "waiter cancellation did not stay a Swift cancellation") }
    must(!operation!.isCancelRequested(), "wait cancellation cancelled native work")
    emit("cancel.wait-is-not-work", true)
    gate.release(); must(try await operation!.result() == payload(), "native work did not survive waiter cancellation")
    operation = nil
    // The waiter variable remains in scope, so ARC may retain the task capture until this helper returns.
    try await cancelQueuedAndRunning(engine)
    engine.requestClose(); try await engine.awaitClosed()
    // Explicitly end this Task's capture scope before ownership assertions.
    try await finishAfterWaiterScope(engine, waiter: waiter)
}
func cancelQueuedAndRunning(_ engine: Engine) async throws {
    let gate = Gate(); let invoked = Recorder()
    var running: Operation? = try engine.startOperation(value: payload(), host: CallbackHost { value in gate.enterAndWait(); return value })
    gate.awaitEntered()
    var queued: Operation? = try engine.startOperation(value: payload(), host: CallbackHost { value in _ = invoked.append(value); return value })
    running!.requestCancel(); queued!.requestCancel(); gate.release()
    await expectAsyncError("Cancelled") { _ = try await running!.result() }
    await expectAsyncError("Cancelled") { _ = try await queued!.result() }
    must(invoked.values.isEmpty, "queued cancelled callback ran")
    running = nil; queued = nil
    emit("cancel.queued-callbacks", 0); emit("cancel.late-result", "Cancelled")
}
func finishAfterWaiterScope(_ engine: Engine, waiter: Task<Value, any Error>) async throws {
    // Completion clears Swift Task execution captures; this checks the actual resulting native count.
    _ = try? await waiter.value
    try await finish(engine)
}
func lateCallbackCase(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected); let gate = Gate(); let sink = RecordingSink(gate)
    var subscription: Subscription? = try engine.observeEvents(sink: sink)
    try engine.tryPublishEvent(value: payload(1)); gate.awaitEntered()
    must(engine.statistics().callbacksInFlight == 1, "source lease not held during callback")
    try engine.tryPublishEvent(value: payload(2)); subscription!.requestStop(); try engine.tryPublishEvent(value: payload(3))
    gate.release(); try await subscription!.awaitStopped()
    must(sink.recorder.values.map(\.sequence) == [1], "late callback entered stopped consumer")
    emit("late-callback.sequences", [1]); subscription = nil; try await finish(engine)

    let stateEngine = try openEngine(expectedProfile: expected); let workerGate = Gate()
    var held: Operation? = try stateEngine.startOperation(value: emptyPayload(), host: CallbackHost { value in workerGate.enterAndWait(); return value })
    workerGate.awaitEntered(); let stateGate = Gate(); let stateSink = RecordingSink(stateGate)
    var state: Subscription? = try stateEngine.observeState(sink: stateSink)
    for sequence in 1...3 { try stateEngine.publishState(value: Value(id: "", sequence: Int64(sequence), text: "x", bytes: [], phase: .ready)) }
    must(stateEngine.statistics().queuedItems == 1 && stateEngine.statistics().retainedBytes == 1, "state coalescing retained superseded payloads")
    workerGate.release(); _ = try await held!.result(); held = nil; stateGate.awaitEntered()
    state!.requestStop(); stateGate.release(); try await state!.awaitStopped()
    must(stateSink.recorder.values.map(\.sequence) == [3], "state did not deliver latest value")
    emit("state.latest-sequence", 3); state = nil; try await finish(stateEngine, second: true)
}
func capacityCase(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected); let gate = Gate()
    var held: Operation? = try engine.startOperation(value: emptyPayload(), host: CallbackHost { value in gate.enterAndWait(); return value }); gate.awaitEntered()
    let sink = RecordingSink(); var subscription: Subscription? = try engine.observeEvents(sink: sink)
    for _ in 0..<8 { try engine.tryPublishEvent(value: emptyPayload(1)) }
    let admitted = engine.statistics().payloadsAdmitted
    expectError("ResourceExhausted") { try engine.tryPublishEvent(value: emptyPayload(1)) }
    must(engine.statistics().queuedItems == 8 && engine.statistics().payloadsAdmitted == admitted, "item overflow transferred ownership")
    emit("capacity.items", 8); engine.requestClose(); gate.release(); try await engine.awaitClosed()
    await expectAsyncError("Cancelled") { _ = try await held!.result() }; held = nil
    try await subscription!.awaitStopped(); subscription = nil
    must(sink.recorder.values.isEmpty, "full queue shutdown delivered new callbacks"); try await finish(engine)

    let bytesEngine = try openEngine(expectedProfile: expected); let bytesGate = Gate()
    var bytesHeld: Operation? = try bytesEngine.startOperation(value: emptyPayload(1024), host: CallbackHost { value in bytesGate.enterAndWait(); return value }); bytesGate.awaitEntered()
    var bytesSub: Subscription? = try bytesEngine.observeEvents(sink: RecordingSink())
    for _ in 0..<3 { try bytesEngine.tryPublishEvent(value: emptyPayload(1024)) }
    expectError("ResourceExhausted") { try bytesEngine.tryPublishEvent(value: emptyPayload(1)) }
    expectError("ResourceExhausted") { try bytesEngine.tryPublishEvent(value: emptyPayload(1025)) }
    must(bytesEngine.statistics().retainedBytes == 4096, "byte budget omitted in-flight payload")
    emit("capacity.bytes", 4096); bytesEngine.requestClose(); bytesGate.release(); try await bytesEngine.awaitClosed()
    await expectAsyncError("Cancelled") { _ = try await bytesHeld!.result() }; bytesHeld = nil
    try await bytesSub!.awaitStopped(); bytesSub = nil; try await finish(bytesEngine, second: true)
    try await handleBudgets(expected)
    try await waiterBudget(expected)
}
func handleBudgets(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected); let gate = Gate()
    var operations = [try engine.startOperation(value: emptyPayload(), host: CallbackHost { value in gate.enterAndWait(); return value })]
    gate.awaitEntered()
    for _ in 0..<7 { operations.append(try engine.startOperation(value: emptyPayload(), host: CallbackHost { $0 })) }
    expectError("ResourceExhausted") { _ = try engine.startOperation(value: emptyPayload(), host: CallbackHost { $0 }) }
    var subscriptions = try (0..<8).map { _ in try engine.observeEvents(sink: RecordingSink()) }
    expectError("ResourceExhausted") { _ = try engine.observeEvents(sink: RecordingSink()) }
    emit("capacity.operations", 8); emit("capacity.subscriptions", 8)
    engine.requestClose(); gate.release(); try await engine.awaitClosed()
    for operation in operations { await expectAsyncError("Cancelled") { _ = try await operation.result() } }
    operations.removeAll()
    for subscription in subscriptions { try await subscription.awaitStopped() }
    subscriptions.removeAll()
    try await finish(engine, ownerName: "handles")
}
func waiterBudget(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected); let rejected = Started(); let failures = Recorder()
    let waiters = (0..<33).map { _ in Task {
        do { try await engine.awaitClosed(); preconditionFailure("open engine unexpectedly closed") }
        catch is CancellationError { }
        catch { must(errorName(error) == "ResourceExhausted", "wrong waiter admission error")
            _ = failures.append(payload()); await rejected.signal()
        }
    } }
    await rejected.wait()
    for waiter in waiters { waiter.cancel() }
    for waiter in waiters { await waiter.value }
    must(failures.values.count == 1, "waiter budget did not admit exactly 32 pending waits")
    emit("capacity.waiters", 32); emit("capacity.waiter-overflow", 1)
    try await finish(engine, ownerName: "waiter")
}
func shutdownCase(_ expected: String) async throws {
    let engine = try openEngine(expectedProfile: expected); let gate = Gate()
    var operation: Operation? = try engine.startOperation(value: payload(), host: CallbackHost { value in gate.enterAndWait(); return value }); gate.awaitEntered()
    engine.requestClose(); engine.requestClose()
    expectError("Closing") { _ = try engine.startOperation(value: payload(), host: CallbackHost { $0 }) }
    must(engine.statistics().callbacksInFlight == 1 && engine.statistics().workerExits == 0, "owner exited before callback drain")
    emit("shutdown.waited-for-callback", true); gate.release(); try await engine.awaitClosed()
    await expectAsyncError("Cancelled") { _ = try await operation!.result() }; operation = nil; try await finish(engine)
    let callbackEngine = try openEngine(expectedProfile: expected); let calls = Recorder()
    var callbackOperation: Operation? = try callbackEngine.startOperation(value: payload(), host: CallbackHost { value in
        _ = calls.append(value); callbackEngine.requestClose(); return value
    })
    await expectAsyncError("Cancelled") { _ = try await callbackOperation!.result() }; callbackOperation = nil
    try await callbackEngine.awaitClosed(); must(calls.values.count == 1, "callback close request did not run")
    emit("shutdown.callback-request", true); try await finish(callbackEngine, second: true)
}
@main struct Consumer {
    static func main() async throws {
        let arguments = CommandLine.arguments; precondition(arguments.count == 3 || arguments.count == 4)
        let scenario = arguments[1], expected = arguments[2]
        switch scenario {
        case "data": try await dataCase(expected)
        case "errors": try await errorsCase(expected)
        case "objects": try await objectsCase(expected)
        case "async": try await asyncCase(expected)
        case "cancel": try await cancelCase(expected)
        case "late-callback": try await lateCallbackCase(expected)
        case "capacity": try await capacityCase(expected)
        case "shutdown": try await shutdownCase(expected)
        case "identity":
            must(profileIdentity() == expected, "loaded profile differs"); emit("identity.profile", profileIdentity())
            try await finish(openEngine(expectedProfile: expected))
        case "distribution":
            must(profileIdentity() == expected, "loaded profile differs"); emit("identity.profile", profileIdentity())
            var info = Dl_info()
            let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "ffi_madb_boundary_uniffi_uniffi_contract_version")
            must(symbol != nil && dladdr(symbol, &info) != 0, "cannot identify actual loaded provider")
            let loaded = URL(fileURLWithPath: String(cString: info.dli_fname)).resolvingSymlinksInPath().path
            let installed = URL(fileURLWithPath: arguments[3]).resolvingSymlinksInPath().path
            emit("distribution.loaded-copy", loaded == installed)
            try await finish(openEngine(expectedProfile: expected))
        case "wrong-abi":
            do { _ = try openEngine(expectedProfile: expected); preconditionFailure("incompatible ABI was admitted") }
            catch MadbAbiMismatch.apiChecksum { emit("rejection.code", "AbiMismatch") }
        case "wrong-profile": expectError("ProfileMismatch") { _ = try openEngine(expectedProfile: expected) }; emit("rejection.code", "ProfileMismatch")
        default: preconditionFailure("unknown independent scenario")
        }
        print("{\"result\":\"passed\"}")
    }
}
