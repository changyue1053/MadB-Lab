package lab.c06

import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

fun threadIdentity(): String = Thread.currentThread().threadId().toString()
fun newGate(): Gate = object : Gate {
    private val entered=CountDownLatch(1)
    private val released=CountDownLatch(1)
    override fun enterAndWait() {
        entered.countDown()
        check(released.await(10,TimeUnit.SECONDS)) { "foreign callback release barrier timed out" }
    }
    override fun awaitEntered() { check(entered.await(10,TimeUnit.SECONDS)) { "foreign callback entry barrier timed out" } }
    override fun release() { released.countDown() }
}

fun loadedLibraryPath(): String = com.sun.jna.NativeLibrary.getInstance("madb_boundary_uniffi").file.canonicalPath
fun canonicalPath(path: String): String = java.io.File(path).canonicalPath
