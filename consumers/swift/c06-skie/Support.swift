import Foundation
import MadBSkie

struct LabFailure: Error, CustomStringConvertible {
    let description: String
}

@MainActor
func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw LabFailure(description: message) }
}

@MainActor
func emit(_ check: String, _ actual: Any) throws {
    let bytes = try JSONSerialization.data(withJSONObject: ["check": check, "actual": actual], options: [.sortedKeys])
    print(String(decoding: bytes, as: UTF8.self))
}

func failureCode(_ error: Error) -> String {
    if error is CancellationError { return "Cancelled" }
    if let failure = error as? MadBSkieRuntimeError {
        switch failure {
        case .wouldDeadlock: return "WouldDeadlock"
        case .closing: return "Closing"
        case .resourceExhausted: return "ResourceExhausted"
        case .alreadyCollected: return "AlreadyCollected"
        }
    }
    if let failure = (error as NSError).kotlinException as? BoundaryFailure { return failure.code }
    return "Unclassified:\(type(of: error))"
}

func bytes(_ values: [UInt8]) -> KotlinByteArray {
    let output = KotlinByteArray(size: Int32(values.count))
    for (index, value) in values.enumerated() { output.set(index: Int32(index), value: Int8(bitPattern: value)) }
    return output
}

func octets(_ input: KotlinByteArray) -> [Int] {
    (0..<input.size).map { Int(UInt8(bitPattern: input.get(index: $0))) }
}

func sample(sequence: Int64? = nil, text: String = "你好\0é") -> Value {
    Value(id: "m1", sequence: sequence.map { KotlinLong(longLong: $0) }, text: text,
          bytes: bytes([0, 127, 128, 255]), phase: .open)
}

func payload(_ count: Int, id: String = "") -> Value {
    Value(id: id, sequence: nil, text: "", bytes: bytes(Array(repeating: 0x5a, count: count)), phase: .open)
}

/// The condition protects every mutable field. Only the SDK owner worker waits;
/// the MainActor waits through a continuation and never blocks the native callback.
final class BarrierHost: NSObject, MadBSkie.Host {
    private let condition = NSCondition()
    private var entered = false
    private var released: Bool
    private var enteredWaiter: CheckedContinuation<Void, Never>?
    private var calls = 0
    private var wasMain = false
    private let replacement: Bool
    private let invalidResult: Bool

    init(blocking: Bool = false, replacement: Bool = false, invalidResult: Bool = false) {
        released = !blocking
        self.replacement = replacement
        self.invalidResult = invalidResult
    }

    func transform(value: Value) -> Value {
        condition.lock()
        calls += 1
        wasMain = wasMain || Thread.isMainThread
        entered = true
        let waiter = enteredWaiter
        enteredWaiter = nil
        condition.unlock()
        waiter?.resume()
        condition.lock()
        while !released { condition.wait() }
        condition.unlock()
        if invalidResult { return payload(1025) }
        if replacement {
            return Value(id: "host-m1", sequence: KotlinLong(longLong: 42), text: "host-result",
                         bytes: bytes([255, 0]), phase: .open)
        }
        return value
    }

    @MainActor
    func waitUntilEntered() async {
        await withCheckedContinuation { continuation in
            condition.lock()
            if entered {
                condition.unlock()
                continuation.resume()
            } else {
                precondition(enteredWaiter == nil)
                enteredWaiter = continuation
                condition.unlock()
            }
        }
    }

    func releaseCallback() {
        condition.lock()
        released = true
        condition.broadcast()
        condition.unlock()
    }

    func observation() -> (calls: Int, onMain: Bool) {
        condition.lock()
        defer { condition.unlock() }
        return (calls, wasMain)
    }
}

@MainActor
func emptyAfterClose(_ engine: Engine, owner: MadBEngineHandle) async throws {
    owner.requestClose()
    try await owner.awaitClosed()
    let stats = engine.stats()
    try require(stats.closed, "close must finish")
    try require(stats.activeOperations == 0, "operation remains after close")
    try require(stats.activeSubscriptions == 0, "subscription remains after close")
    try require(stats.queuedItems == 0, "queued item remains after close")
    try require(stats.retainedBytes == 0, "retained payload remains after close")
}

@MainActor
func caught(_ action: () throws -> Void) throws -> String {
    do {
        try action()
        throw LabFailure(description: "expected a typed boundary failure")
    } catch let failure as LabFailure { throw failure }
    catch { return failureCode(error) }
}
