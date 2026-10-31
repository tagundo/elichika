package com.tagundo.elichika

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import java.util.UUID
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit

/** Synchronous Chaquopy bridge, called only by Python's background job workers. */
class AndroidServerController(private val context: Context) {
    private val main = Handler(Looper.getMainLooper())
    private data class Hold(val service: ServerService, val cancellation: Long, val wasRunning: Boolean)
    // A failed concurrent job must never finish another worker's installation.
    private val held = ThreadLocal<Hold?>()

    fun is_running(): Boolean = onMain { Bus.serverRunning }

    fun stop(): Boolean {
        check(Looper.myLooper() != Looper.getMainLooper()) { "Install must run on a worker thread" }
        check(held.get() == null) { "This worker already holds the server" }
        // Tool servers outlive the Go server. An initially stopped install still
        // needs a foreground hold and must prevent a second window from starting Go.
        var service = onMain { ServerService.current }
        var request: String? = null
        if (service == null) {
            request = UUID.randomUUID().toString()
            onMain {
                context.startForegroundService(Intent(context, ServerService::class.java)
                    .setAction(ServerService.ACTION_PREPARE_INSTALL)
                    .putExtra(ServerService.EXTRA_HOLD_ID, request))
            }
        }
        // First-install extraction can take minutes on slower devices. Wait on
        // this worker, never inside an onMain call or a Service lifecycle callback.
        val until = System.nanoTime() + TimeUnit.MINUTES.toNanos(5)
        var ready: ServerService? = null
        while (ready == null && System.nanoTime() < until) {
            ready = onMain {
                if (service == null) service = ServerService.current
                service?.let { candidate ->
                    candidate.initializationFailure?.let { throw IllegalStateException("Server preparation failed", it) }
                    check(ServerService.current === candidate) { "Server preparation was stopped" }
                    candidate.takeIf { it.isReady && (request == null || it.holdRequest == request) }
                }
            }
            if (ready == null) Thread.sleep(50)
        }
        val active = checkNotNull(ready) { "Server preparation timed out; retry when setup completes" }
        val paused = onMain {
            val wasRunning = Bus.serverRunning
            val process = active.pauseForInstall()
            Pair(process, Hold(active, ServerService.cancellation, wasRunning))
        }
        held.set(paused.second)
        return ServerProcess.awaitStopped(paused.first)
    }

    fun was_running_before_stop(): Boolean = held.get()?.wasRunning == true

    fun start(): Boolean {
        val hold = held.get() ?: return false
        return onMain { hold.service.resumeAfterInstall(hold.cancellation) }
    }

    fun finish() {
        val hold = held.get() ?: return
        try { onMain { hold.service.finishInstall() } }
        finally { held.remove() }
    }

    private fun <T> onMain(action: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) return action()
        val task = FutureTask<T> { action() }
        main.post(task)
        try { return task.get(30, TimeUnit.SECONDS) }
        catch (error: Exception) {
            task.cancel(false)
            throw error
        }
    }
}
