package lab.c06

import kotlinx.coroutines.*
import madb.boundary.*

// The oracle is authored in Lab. No producer state machine, constants or helpers are imported.
interface Gate {
    fun enterAndWait()
    fun awaitEntered()
    fun release()
}
fun quote(value: String): String = buildString {
    append('"')
    for (char in value) when (char) {
        '"' -> append("\\\""); '\\' -> append("\\\\"); '\n' -> append("\\n"); '\r' -> append("\\r"); '\t' -> append("\\t")
        else -> if (char.code < 32) append("\\u" + char.code.toString(16).padStart(4, '0')) else append(char)
    }
    append('"')
}
fun observed(name: String, value: String) = println("{\"check\":${quote(name)},\"actual\":$value}")
fun observedText(name: String, value: String) = observed(name, quote(value))
fun must(value: Boolean, reason: String) { check(value) { reason } }
fun payload(sequence: Long? = null, text: String = "你好\u0000é", id: String = "m1", bytes: List<UByte> = listOf(0u, 127u, 128u, 255u)) =
    Value(id, sequence, text, bytes, Phase.READY)
fun emptyPayload(size: Int = 0) = Value("", null, "", List(size) { 0u.toUByte() }, Phase.READY)
fun assertValue(actual: Value, expected: Value) {
    must(actual.id == expected.id && actual.sequence == expected.sequence && actual.text == expected.text &&
        actual.bytes == expected.bytes && actual.phase == expected.phase, "public record fields did not roundtrip")
}
fun errorName(error: Throwable) = error::class.simpleName ?: "unknown"
fun expectError(name: String, block: () -> Unit) {
    var caught: Throwable? = null
    try { block() } catch (error: Throwable) { caught = error }
    must(caught != null && errorName(caught) == name, "expected $name, got ${caught?.let(::errorName)}")
}
suspend fun expectAsyncError(name: String, block: suspend () -> Unit) {
    var caught: Throwable? = null
    try { block() } catch (error: Throwable) { caught = error }
    must(caught != null && errorName(caught) == name, "expected async $name, got ${caught?.let(::errorName)}")
}
class IdentityHost : Host { override fun transform(value: Value) = value }
class BlockingHost(val gate: Gate) : Host {
    var callbackThread: String = ""
    override fun transform(value: Value): Value { callbackThread = threadIdentity(); gate.enterAndWait(); return value }
}
class RecordingSink(val gate: Gate? = null) : Sink {
    val values = mutableListOf<Value>()
    override fun onValue(value: Value) { values.add(value); if (values.size == 1) gate?.enterAndWait() }
}
suspend fun finish(engine: Engine) {
    engine.requestClose(); engine.awaitClosed()
    val stats = engine.statistics()
    must(stats.queuedItems == 0UL && stats.retainedBytes == 0UL && stats.callbacksInFlight == 0UL &&
         stats.activeOperations == 0UL && stats.activeSubscriptions == 0UL, "close did not drain owned work")
    must(stats.payloadsAdmitted == stats.payloadsReleased, "retained payloads did not return to baseline")
    must(stats.operationsCreated == stats.operationsReleased, "operation ownership leaked")
    must(stats.subscriptionsCreated == stats.subscriptionsReleased, "subscription ownership leaked")
    must(stats.workerExits == 1UL, "instance worker did not exit exactly once")
    observed("cleanup.owned-work", "0")
    engine.destroy()
}

suspend fun data(expected: String) {
    val engine = openEngine(expected)
    val original = payload()
    val value = engine.roundtrip(original)
    assertValue(value, original)
    observedText("data.id", value.id); observedText("data.text", value.text)
    observed("data.null", if (value.sequence == null) "null" else value.sequence.toString())
    observed("data.bytes", value.bytes.joinToString(prefix="[", postfix="]"))
    observedText("data.minimum", engine.roundtrip(payload(Long.MIN_VALUE)).sequence.toString())
    observedText("data.maximum", engine.roundtrip(payload(Long.MAX_VALUE)).sequence.toString())
    for (phase in listOf(Phase.READY, Phase.WORKING, Phase.DONE)) assertValue(engine.roundtrip(original.copy(phase=phase)), original.copy(phase=phase))
    observed("data.variants", "3")
    finish(engine)
}
suspend fun errors(expected: String) {
    val engine = openEngine(expected)
    expectError("ResourceExhausted") { engine.roundtrip(emptyPayload(1025)) }
    val operation = engine.startOperation(payload(), object : Host {
        override fun transform(value: Value): Value { throw IllegalStateException("independent host failure") }
    })
    expectAsyncError("CallbackFailure") { operation.result() }
    operation.destroy()
    engine.requestClose(); engine.awaitClosed()
    expectError("Closed") { engine.roundtrip(payload()) }
    observedText("errors.callback", "CallbackFailure"); observedText("errors.closed", "Closed")
    observedText("errors.payload", "ResourceExhausted")
    finish(engine)
}
suspend fun objects(expected: String) {
    val engine = openEngine(expected)
    val operation = engine.startOperation(payload(), IdentityHost())
    val alias = operation
    assertValue(alias.result(), payload())
    expectAsyncError("AlreadyConsumed") { operation.result() }
    alias.destroy(); operation.destroy()
    must(engine.statistics().operationsReleased == 1UL, "aliases released the native operation more than once")
    observed("objects.released", "1"); observedText("objects.second-result", "AlreadyConsumed")
    finish(engine)
}
suspend fun asyncCase(expected: String) {
    val engine = openEngine(expected)
    val caller = threadIdentity()
    var callback = ""
    val operation = engine.startOperation(payload(), object : Host {
        override fun transform(value: Value): Value {
            callback = threadIdentity()
            // A reentrant query is legal. This also detects a lock held across a foreign callback.
            assertValue(engine.roundtrip(value), value)
            return value.copy(text = value.text + ":host")
        }
    })
    val result = operation.result()
    observedText("async.text", result.text)
    must(callback.isNotEmpty() && callback != caller, "foreign callback did not run on the declared owner worker")
    observed("async.worker-distinct", "true")
    operation.destroy(); finish(engine)
}
suspend fun cancel(expected: String) = coroutineScope {
    val engine = openEngine(expected)
    val gate = newGate()
    val operation = engine.startOperation(payload(), BlockingHost(gate))
    gate.awaitEntered()
    // Deterministic cancellation before an IO-dispatched generated body starts.
    // The old Gobley helper allocated its Rust future before installing finally.
    val preCancelled = launch(start=CoroutineStart.UNDISPATCHED) {
        currentCoroutineContext().cancel()
        operation.result()
        error("pre-cancelled waiter resumed successfully")
    }
    preCancelled.join()
    val waiter = launch(start=CoroutineStart.UNDISPATCHED) { operation.result(); error("cancelled waiter resumed successfully") }
    waiter.cancelAndJoin()
    must(!operation.isCancelRequested(), "cancelling a waiter silently cancelled native work")
    observed("cancel.wait-is-not-work", "true")
    gate.release(); assertValue(operation.result(), payload()); operation.destroy()

    val gate2 = newGate(); val running = engine.startOperation(payload(), BlockingHost(gate2)); gate2.awaitEntered()
    var queuedInvoked = false
    val queued = engine.startOperation(payload(), object : Host { override fun transform(value: Value): Value { queuedInvoked=true; return value } })
    queued.requestCancel(); running.requestCancel()
    must(running.isCancelRequested() && queued.isCancelRequested(), "explicit cancellation was not recorded")
    gate2.release()
    expectAsyncError("Cancelled") { running.result() }; expectAsyncError("Cancelled") { queued.result() }
    must(!queuedInvoked, "queued cancelled work entered the foreign callback")
    running.destroy(); queued.destroy()
    observed("cancel.queued-callbacks", "0"); observedText("cancel.late-result", "Cancelled")
    finish(engine)
}
suspend fun lateCallback(expected: String) {
    val engine=openEngine(expected); val gate=newGate(); val sink=RecordingSink(gate)
    val subscription=engine.observeEvents(sink)
    engine.tryPublishEvent(payload(1)); gate.awaitEntered()
    must(engine.statistics().callbacksInFlight == 1UL, "source lease was not observable while callback was blocked")
    engine.tryPublishEvent(payload(2)); subscription.requestStop()
    engine.tryPublishEvent(payload(3))
    gate.release(); subscription.awaitStopped()
    must(sink.values.map { it.sequence } == listOf(1L), "stopped observer received a queued or late callback")
    observed("late-callback.sequences", "[1]")
    subscription.destroy(); finish(engine)

    val stateEngine=openEngine(expected); val workerGate=newGate()
    val held=stateEngine.startOperation(emptyPayload(),BlockingHost(workerGate)); workerGate.awaitEntered()
    val stateGate=newGate(); val stateSink=RecordingSink(stateGate); val state=stateEngine.observeState(stateSink)
    for(sequence in 1L..3L) stateEngine.publishState(Value("",sequence,"x",emptyList(),Phase.READY))
    must(stateEngine.statistics().queuedItems==1UL && stateEngine.statistics().retainedBytes==1UL,"state latest slot retained superseded payloads")
    workerGate.release(); held.result(); held.destroy(); stateGate.awaitEntered()
    state.requestStop(); stateGate.release(); state.awaitStopped()
    must(stateSink.values.map { it.sequence }==listOf(3L),"state did not coalesce to the latest queued value")
    observed("state.latest-sequence","3"); state.destroy(); finishSecond(stateEngine)
}
suspend fun capacity(expected: String) {
    // Item budget: keep the worker inside a real foreign callback, then fill eight event tickets.
    val engine=openEngine(expected); val gate=newGate(); val held=engine.startOperation(emptyPayload(),BlockingHost(gate)); gate.awaitEntered()
    val sink=RecordingSink(); val subscription=engine.observeEvents(sink)
    repeat(8) { engine.tryPublishEvent(emptyPayload(1)) }
    val admitted=engine.statistics().payloadsAdmitted
    expectError("ResourceExhausted") { engine.tryPublishEvent(emptyPayload(1)) }
    must(engine.statistics().queuedItems==8UL && engine.statistics().payloadsAdmitted==admitted, "item overflow transferred ownership")
    observed("capacity.items", "8")
    engine.requestClose(); gate.release(); engine.awaitClosed()
    expectAsyncError("Cancelled") { held.result() }
    held.destroy(); subscription.awaitStopped(); subscription.destroy()
    must(sink.values.isEmpty(), "shutdown admitted callbacks from a full queue")
    finish(engine)

    // Byte budget includes the in-flight host payload, not just pending queue items.
    val bytesEngine=openEngine(expected); val bytesGate=newGate(); val bytesHeld=bytesEngine.startOperation(emptyPayload(1024),BlockingHost(bytesGate)); bytesGate.awaitEntered()
    val bytesSub=bytesEngine.observeEvents(RecordingSink())
    repeat(3) { bytesEngine.tryPublishEvent(emptyPayload(1024)) }
    expectError("ResourceExhausted") { bytesEngine.tryPublishEvent(emptyPayload(1)) }
    expectError("ResourceExhausted") { bytesEngine.tryPublishEvent(emptyPayload(1025)) }
    must(bytesEngine.statistics().retainedBytes==4096UL, "retained byte budget omitted in-flight work")
    observed("capacity.bytes", "4096")
    bytesEngine.requestClose(); bytesGate.release(); bytesEngine.awaitClosed()
    expectAsyncError("Cancelled") { bytesHeld.result() }; bytesHeld.destroy(); bytesSub.awaitStopped(); bytesSub.destroy()
    // Avoid emitting the same observation name twice in a case with two owners.
    finishSecond(bytesEngine)
    handleBudgets(expected)
    waiterBudget(expected)
}
suspend fun handleBudgets(expected: String) {
    val engine=openEngine(expected); val gate=newGate()
    val operations=mutableListOf(engine.startOperation(emptyPayload(),BlockingHost(gate))); gate.awaitEntered()
    repeat(7) { operations.add(engine.startOperation(emptyPayload(),IdentityHost())) }
    expectError("ResourceExhausted") { engine.startOperation(emptyPayload(),IdentityHost()) }
    val subscriptions=List(8) { engine.observeEvents(RecordingSink()) }
    expectError("ResourceExhausted") { engine.observeEvents(RecordingSink()) }
    observed("capacity.operations","8"); observed("capacity.subscriptions","8")
    engine.requestClose(); gate.release(); engine.awaitClosed()
    for(operation in operations) { expectAsyncError("Cancelled") { operation.result() }; operation.destroy() }
    for(subscription in subscriptions) { subscription.awaitStopped(); subscription.destroy() }
    finishSecond(engine,"handles")
}
suspend fun waiterBudget(expected: String) = coroutineScope {
    val engine=openEngine(expected); val rejected=CompletableDeferred<Unit>()
    val failures=mutableListOf<String>()
    // Every waiter returns to this same consumer coroutine context before writing the list.
    val waiters=List(33) { launch {
        try { engine.awaitClosed(); error("open engine unexpectedly closed") }
        catch(error: CancellationException) { /* Consumer cancelled its own wait. */ }
        catch(error: Throwable) {
            check(errorName(error)=="ResourceExhausted")
            failures.add(errorName(error)); rejected.complete(Unit)
        }
    } }
    rejected.await()
    for(waiter in waiters) waiter.cancel()
    waiters.joinAll()
    check(failures==listOf("ResourceExhausted"))
    observed("capacity.waiters","32"); observed("capacity.waiter-overflow","1")
    finishSecond(engine,"waiter")
}
suspend fun finishSecond(engine: Engine, name: String = "second") {
    engine.requestClose(); engine.awaitClosed(); val stats=engine.statistics()
    must(stats.queuedItems==0UL && stats.retainedBytes==0UL && stats.activeOperations==0UL && stats.activeSubscriptions==0UL && stats.callbacksInFlight==0UL, "second owner did not drain")
    must(stats.payloadsAdmitted==stats.payloadsReleased && stats.operationsCreated==stats.operationsReleased && stats.subscriptionsCreated==stats.subscriptionsReleased && stats.workerExits==1UL,"second owner resources leaked")
    observed("cleanup.$name-owner", "0"); engine.destroy()
}
suspend fun shutdown(expected: String) = coroutineScope {
    val engine=openEngine(expected); val gate=newGate(); val op=engine.startOperation(payload(),BlockingHost(gate)); gate.awaitEntered()
    engine.requestClose(); engine.requestClose()
    expectError("Closing") { engine.startOperation(payload(),IdentityHost()) }
    val close=async(start=CoroutineStart.UNDISPATCHED) { engine.awaitClosed() }
    must(!close.isCompleted,"close completed while a foreign callback still owned a source lease")
    observed("shutdown.waited-for-callback","true")
    gate.release(); close.await(); expectAsyncError("Cancelled") { op.result() }; op.destroy()
    finish(engine)
    val callbackEngine=openEngine(expected)
    var calls=0
    val callbackOperation=callbackEngine.startOperation(payload(),object : Host {
        override fun transform(value: Value): Value { calls++; callbackEngine.requestClose(); return value }
    })
    expectAsyncError("Cancelled") { callbackOperation.result() }; callbackOperation.destroy()
    callbackEngine.awaitClosed(); check(calls==1)
    observed("shutdown.callback-request","true"); finishSecond(callbackEngine)
}
suspend fun identity(expected: String) {
    observedText("identity.profile", profileIdentity())
    must(profileIdentity()==expected,"loaded provider profile differs")
    val engine=openEngine(expected); finish(engine)
}
fun wrongProfile(expected: String) {
    expectError("ProfileMismatch") { openEngine(expected) }
    observedText("rejection.code","ProfileMismatch")
}
fun wrongAbi(expected: String) {
    var caught: Throwable? = null
    try { openEngine(expected) } catch (failure: Throwable) { caught = failure }
    var current = caught
    var checksum = false
    repeat(8) {
        if (current?.message?.contains("UniFFI API checksum mismatch") == true) checksum = true
        current = current?.cause
    }
    must(checksum, "wrong ABI did not produce the precise upstream checksum rejection: $caught")
    observedText("rejection.code", "AbiMismatch")
}
suspend fun execute(scenario: String, expected: String, installedLibrary: String?) {
    when(scenario) {
        "data" -> data(expected); "errors" -> errors(expected); "objects" -> objects(expected)
        "async" -> asyncCase(expected); "cancel" -> cancel(expected); "late-callback" -> lateCallback(expected)
        "capacity" -> capacity(expected); "shutdown" -> shutdown(expected); "identity" -> identity(expected)
        "wrong-profile" -> wrongProfile(expected); "wrong-abi" -> wrongAbi(expected)
        "distribution" -> { identity(expected); observed("distribution.loaded-copy", (loadedLibraryPath()==canonicalPath(checkNotNull(installedLibrary))).toString()) }
        else -> error("Unknown independent scenario: $scenario")
    }
    println("{\"result\":\"passed\"}")
}
fun main(args: Array<String>) = runBlocking { require(args.size in 2..3); withTimeout(15000) { execute(args[0],args[1],args.getOrNull(2)) } }
