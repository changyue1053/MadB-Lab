@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class)
package madb.boundary

import kotlinx.cinterop.invoke
import kotlinx.atomicfu.atomic
import kotlinx.coroutines.*

private fun observation(name: String, value: Long) = println("{\"check\":\"$name\",\"actual\":$value}")
private fun scalarValues(name: String, values: List<ULong>) {
    // Decimal strings preserve uint64 MAX without a JSON/JS floating conversion.
    val encoded = values.joinToString(prefix="[", postfix="]") { "\"$it\"" }
    println("{\"check\":\"$name\",\"actual\":$encoded}")
}
private fun unsignedScalars() {
    val u8 = listOf<UByte>(0u, 128u, 255u)
    val u16 = listOf<UShort>(0u, 32768u, 65535u)
    val u32 = listOf<UInt>(0u, 2147483648u, 4294967295u)
    val u64 = listOf<ULong>(0uL, 9223372036854775808uL, 18446744073709551615uL)
    val received8 = mutableListOf<UByte>(); val received16 = mutableListOf<UShort>()
    val received32 = mutableListOf<UInt>(); val received64 = mutableListOf<ULong>()
    val host = object : UnsignedHost {
        override fun echoU8(value: UByte): UByte { received8.add(value); return (value.toUInt() xor 255u).toUByte() }
        override fun echoU16(value: UShort): UShort { received16.add(value); return (value.toUInt() xor 65535u).toUShort() }
        override fun echoU32(value: UInt): UInt { received32.add(value); return value.inv() }
        override fun echoU64(value: ULong): ULong { received64.add(value); return value.inv() }
    }
    scalarValues("unsigned.u8.forward", u8.map { unsignedU8(it).toULong() })
    scalarValues("unsigned.u16.forward", u16.map { unsignedU16(it).toULong() })
    scalarValues("unsigned.u32.forward", u32.map { unsignedU32(it).toULong() })
    scalarValues("unsigned.u64.forward", u64.map { unsignedU64(it) })
    scalarValues("unsigned.u8.reverse", u8.map { unsignedViaHostU8(it, host).toULong() })
    scalarValues("unsigned.u16.reverse", u16.map { unsignedViaHostU16(it, host).toULong() })
    scalarValues("unsigned.u32.reverse", u32.map { unsignedViaHostU32(it, host).toULong() })
    scalarValues("unsigned.u64.reverse", u64.map { unsignedViaHostU64(it, host) })
    // Check both legs: valid return values cannot conceal corrupted callback arguments.
    check(received8 == u8 && received16 == u16 && received32 == u32 && received64 == u64)
    observation("unsigned.callback-values", 12)
}
private suspend fun normalForeignCall() {
    val calls=atomic(0)
    val input=Value("independent",Long.MIN_VALUE,"async",listOf(0u,255u),Phase.READY)
    val output=asyncHostTransform(input,object : AsyncHost {
        override suspend fun transform(value: Value): Value {
            yield(); calls.incrementAndGet()
            check(value==input)
            return value.copy(text=value.text+":host",sequence=Long.MAX_VALUE)
        }
    })
    check(output==input.copy(text="async:host",sequence=Long.MAX_VALUE))
    observation("foreign.calls",calls.value.toLong())
    observation("foreign.results",1)
    unsignedScalars()
}
private suspend fun throwingCompletion() {
    val ledger=TestLedger()
    val transfer=atomic(0); val failure=atomic(0)
    val before=uniffiForeignFutureNotificationFailures.value
    val future=uniffiTraitInterfaceCallAsync(
        makeCall={ ledger.createResource() },
        handleSuccess={ result ->
            transfer.incrementAndGet()
            result.destroy()
            throw IllegalStateException("independent fault after result handoff")
        },
        handleError={ status -> failure.incrementAndGet(); RustBufferHelper.free(status.errorBuf) },
    )
    uniffiForeignFutureHandleMap.get(future.handle).join()
    future.free!!.invoke(future.handle.toULong())
    observation("completion.transfers",transfer.value.toLong())
    observation("completion.error-terminals",failure.value.toLong())
    observation("completion.created",ledger.created().toLong())
    observation("completion.released",ledger.released().toLong())
    observation("completion.diagnostics",(uniffiForeignFutureNotificationFailures.value-before).toLong())
    ledger.destroy()
}
private suspend fun cancelThenLateResult() {
    val ledger=TestLedger()
    val entered=CompletableDeferred<Unit>(); val cancellationObserved=CompletableDeferred<Unit>(); val release=CompletableDeferred<Unit>()
    val transfer=atomic(0); val failure=atomic(0)
    val future=uniffiTraitInterfaceCallAsync(
        makeCall={
            entered.complete(Unit)
            try { release.await() } catch (cancelled: CancellationException) {
                cancellationObserved.complete(Unit)
                withContext(NonCancellable) { release.await() }
            }
            ledger.createResource()
        },
        handleSuccess={ result -> transfer.incrementAndGet(); result.destroy() },
        handleError={ status -> failure.incrementAndGet(); RustBufferHelper.free(status.errorBuf) },
    )
    val task=uniffiForeignFutureHandleMap.get(future.handle)
    entered.await(); future.free!!.invoke(future.handle.toULong()); cancellationObserved.await()
    check(!task.isCompleted) // Cancellation cannot pretend that uncooperative work has drained.
    release.complete(Unit); task.join()
    observation("late.transfers",transfer.value.toLong())
    observation("late.error-terminals",failure.value.toLong())
    observation("late.created",ledger.created().toLong())
    observation("late.released",ledger.released().toLong())
    ledger.destroy()
}
fun main(args: Array<String>) = runBlocking {
    require(args.size==1)
    withTimeout(15000) {
        when(args[0]) {
            "foreign-future-once" -> normalForeignCall()
            "callback-throw" -> throwingCompletion()
            "cancel-late-result" -> cancelThenLateResult()
            else -> error("unknown independent P03 scenario")
        }
        observation("foreign.pending",uniffiForeignFutureHandleMap.size.toLong())
        println("{\"result\":\"passed\"}")
    }
}
