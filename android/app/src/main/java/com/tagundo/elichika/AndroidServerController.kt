package com.tagundo.elichika

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.FutureTask
import java.util.concurrent.TimeUnit

/** Synchronous Chaquopy bridge, called only by Python's background job workers. */
class AndroidServerController(private val context: Context) {
    private val main = Handler(Looper.getMainLooper())
    private class Hold(val service: ServerService, val cancellation: Long, val outerJob: Boolean) {
        var childDepth = 0
        var paused = false
        var wasRunning = false
        var restartRequested = false
    }
    // Native thread ownership survives separate Python -> Java bridge entries.
    private val held = ConcurrentHashMap<Int, Hold>()
    private fun owner(): Int = android.os.Process.myTid()
    private fun hold(): Hold? = held[owner()]

    fun is_running(): Boolean = onMain { Bus.serverRunning }

    /** Reserve the service before the Python worker takes the database guard. */
    fun begin_job(): Boolean {
        check(Looper.myLooper() != Looper.getMainLooper()) { "Install must run on a worker thread" }
        check(hold() == null) { "This worker already holds the server" }
        held[owner()] = reserve(outerJob = true)
        return true
    }

    fun stop(): Boolean {
        check(Looper.myLooper() != Looper.getMainLooper()) { "Install must run on a worker thread" }
        val existing = hold()
        check(existing == null || existing.outerJob) { "This worker already holds the server" }
        val hold = existing ?: reserve(outerJob = false).also { held[owner()] = it }
        val previous = onMain {
            if (hold.paused) null else {
                hold.wasRunning = Bus.serverRunning
                hold.paused = true
                hold.service.pauseReservedInstall()
            }
        }
        hold.childDepth++
        return ServerProcess.awaitStopped(previous)
    }

    private fun reserve(outerJob: Boolean): Hold {
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
                    check(!candidate.isReady || request == null || candidate.holdRequest == request) {
                        "Another tool job prepared the server; retry installation"
                    }
                    candidate.takeIf { it.isReady && (request == null || it.holdRequest == request) }
                }
            }
            if (ready == null) Thread.sleep(50)
        }
        val active = checkNotNull(ready) { "Server preparation timed out; retry when setup completes" }
        return onMain {
            active.reserveForInstall()
            Hold(active, ServerService.cancellation, outerJob)
        }
    }

    fun was_running_before_stop(): Boolean = hold()?.wasRunning == true

    fun start(): Boolean {
        val hold = hold() ?: return false
        if (hold.outerJob) {
            val allowed = onMain { hold.service.canResumeAfterInstall(hold.cancellation) }
            if (allowed) hold.restartRequested = true
            return allowed
        }
        return onMain { hold.service.resumeAfterInstall(hold.cancellation) }
    }

    fun restart_is_pending(): Boolean = hold()?.let { it.outerJob && it.restartRequested } == true

    fun finish() {
        val owner = owner()
        val hold = held[owner] ?: return
        if (hold.childDepth > 0) hold.childDepth--
        if (hold.outerJob || hold.childDepth > 0) return
        try { onMain { hold.service.finishInstall() } }
        finally { held.remove(owner, hold) }
    }

    /** Called only after the job's database guard has been released. */
    fun finish_job(successful: Boolean): Boolean {
        val owner = owner()
        val hold = held[owner] ?: return false
        check(hold.outerJob) { "This worker does not hold a tool job" }
        try {
            return onMain {
                try {
                    if (successful && hold.restartRequested) {
                        hold.service.resumeAfterInstall(hold.cancellation)
                    } else true
                } finally {
                    hold.service.finishInstall()
                }
            }
        } finally {
            held.remove(owner, hold)
        }
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
