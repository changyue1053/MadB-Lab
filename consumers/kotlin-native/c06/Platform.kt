@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class)
package lab.c06

import kotlinx.cinterop.*
import platform.posix.*
import platform.Foundation.NSCondition
import platform.Foundation.NSDate
import platform.Foundation.NSThread
import platform.Foundation.dateWithTimeIntervalSinceNow

fun threadIdentity(): String = checkNotNull(NSThread.currentThread.description)
fun newGate(): Gate = object : Gate {
    private val condition=NSCondition()
    private var entered=false
    private var released=false
    override fun enterAndWait() {
        condition.lock()
        try {
            entered=true; condition.broadcast()
            val deadline=NSDate.dateWithTimeIntervalSinceNow(10.0)
            while(!released) check(condition.waitUntilDate(deadline)) { "foreign callback release barrier timed out" }
        } finally { condition.unlock() }
    }
    override fun awaitEntered() {
        condition.lock()
        try {
            val deadline=NSDate.dateWithTimeIntervalSinceNow(10.0)
            while(!entered) check(condition.waitUntilDate(deadline)) { "foreign callback entry barrier timed out" }
        } finally { condition.unlock() }
    }
    override fun release() {
        condition.lock()
        try { released=true; condition.broadcast() } finally { condition.unlock() }
    }
}

fun canonicalPath(path: String): String {
    val resolved=checkNotNull(realpath(path,null))
    try { return resolved.toKString() } finally { free(resolved) }
}
fun loadedLibraryPath(): String = memScoped {
    val info=alloc<Dl_info>()
    val symbol=checkNotNull(dlsym(RTLD_DEFAULT,"ffi_madb_boundary_gobley_uniffi_contract_version"))
    check(dladdr(symbol,info.ptr)!=0)
    canonicalPath(checkNotNull(info.dli_fname).toKString())
}
