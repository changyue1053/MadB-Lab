import Foundation
import MadBSkie

@MainActor
func dataCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    let input = sample()
    let output = try engine.roundtrip(value: input)
    try emit("id", output.id)
    try emit("nullable", output.sequence == nil)
    try emit("text", output.text)
    try emit("bytes", octets(output.bytes))
    try emit("int64_min", try engine.roundtrip(value: sample(sequence: Int64.min)).sequence!.stringValue)
    try emit("int64_max", try engine.roundtrip(value: sample(sequence: Int64.max)).sequence!.stringValue)
    input.bytes.set(index: 0, value: 7)
    try emit("independent_snapshot", Int(output.bytes.get(index: 0)))
    try await emptyAfterClose(engine, owner: owner)
}

@MainActor
func errorsCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    try emit("oversize", try caught { _ = try engine.roundtrip(value: payload(1025)) })
    owner.requestClose()
    try emit("closing", try caught { _ = try engine.roundtrip(value: sample()) })
    try await emptyAfterClose(engine, owner: owner)
    try emit("closed", try caught { _ = try engine.roundtrip(value: sample()) })
}

@MainActor
func objectsCase(_ profile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    // The ordinary generated synchronous API still exposes native object identity.
    let firstRaw = try engine.subscribeEvents()
    let secondRaw = try engine.subscribeEvents()
    try emit("distinct_subscriptions", firstRaw !== secondRaw)
    firstRaw.requestStop(); secondRaw.requestStop()
    let firstHandle = try owner.subscribeEvents()
    let secondHandle = try owner.subscribeEvents()
    try emit("active_before_stop", Int(engine.stats().activeSubscriptions))
    firstHandle.requestStop()
    try await firstHandle.awaitStopped()
    try emit("active_after_first_stop", Int(engine.stats().activeSubscriptions))
    try engine.publish(value: sample())
    try emit("remaining_observer_queued", Int(engine.stats().queuedItems))
    secondHandle.requestStop()
    try await secondHandle.awaitStopped()
    try await emptyAfterClose(engine, owner: owner)
    try emit("active_after_close", Int(engine.stats().activeSubscriptions))

    // The weak reference is independent evidence of ARC/GC handoff. Explicit
    // close is tested above; test-only GC is never used as the close mechanism.
    let foreignOwner = try MadBEngineHandle(expectedProfile: profile)
    let foreignEngine = foreignOwner.native
    weak var foreignHost: BarrierHost?
    var operation: MadBSkie.Operation?
    try autoreleasepool {
        let host = BarrierHost()
        foreignHost = host
        operation = try foreignEngine.startOperation(value: sample(), host: host)
    }
    try emit("foreign_host_retained", foreignHost != nil)
    _ = try await MadBOperationHandle(operation!).result()
    operation = nil
    try await emptyAfterClose(foreignEngine, owner: foreignOwner)
    repeat {
        TestSupport.shared.collectGarbage()
        await Task.yield()
    } while foreignHost != nil
    try emit("foreign_host_released", foreignHost == nil)
}

@MainActor
func identityCase(_ profile: String) async throws {
    try require(profileIdentity() == profile, "loaded profile differs from independent selected candidate")
    try emit("profile_matches", profileIdentity() == profile)
    try emit("bootstrap", Int(bootstrapVersion()))
    try emit("native_abi", Int(nativeAbiVersion()))
    let owner = try MadBEngineHandle(expectedProfile: profile)
    let engine = owner.native
    try emit("first_call", try engine.roundtrip(value: sample()).id)
    try await emptyAfterClose(engine, owner: owner)
}

@MainActor
func wrongProfileCase(_ expectedProfile: String) throws {
    try emit("rejection", try caught { _ = try openEngine(expectedProfile: expectedProfile) })
}
