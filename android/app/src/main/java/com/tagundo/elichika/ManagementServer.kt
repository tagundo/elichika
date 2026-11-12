package com.tagundo.elichika

import android.app.Activity
import android.content.Context
import org.json.JSONObject
import java.io.File
import java.net.URI
import java.util.WeakHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Owned loopback WebUI while no game/maintenance service owns the databases. */
object ManagementServer {
    private const val READY_PREFIX = "ELICHIKA_MANAGEMENT_READY "
    private val lock = Any()
    private var context: Context? = null
    private var directory: File? = null
    private var process: ServerProcess? = null
    private var ownedPid: Int? = null
    private var requested = false
    private var uiDemand = false
    private var drainingOwner: ServerProcess? = null
    private val uiOwners = WeakHashMap<Any, Boolean>()
    private var generation = 0L
    private var nextLease = 0L
    private val suspended = mutableSetOf<Long>()
    @Volatile private var baseUrl: String? = null
    @Volatile private var preparing = false
    @Volatile private var failure: String? = null

    internal class Lease internal constructor(internal val id: Long, internal val child: Process?,
                                             internal val owner: ServerProcess?)

    fun url(): String? = baseUrl
    fun isPreparing(): Boolean = preparing
    fun hasError(): Boolean = failure != null
    fun errorMessage(): String? = failure
    fun isDraining(): Boolean = synchronized(lock) { drainingOwner != null }
    internal fun currentPid(): Int? = synchronized(lock) {
        val owner = process ?: return@synchronized null
        val launch = owner.currentLaunch() ?: return@synchronized null
        if (owner.owns(launch)) ownedPid else null
    }

    /** A retry from an offline tab also prepares the existing standalone tools. */
    fun prepareAsync(ctx: Context) {
        synchronized(lock) { requested = true; failure = null }
        prepareTools(ctx)
    }

    /** Each visible management window owns demand independently of data-job leases. */
    fun requestUi(ctx: Context, owner: Any, retry: Boolean = false) {
        synchronized(lock) {
            pruneUiOwnersLocked()
            uiOwners[owner] = true
            uiDemand = true
            requested = true
            if (retry) failure = null
            if (failure != null) return
        }
        prepareTools(ctx)
    }

    /** Returning to 3D/tools drops the last window's Go memory cost. */
    fun releaseUi(owner: Any) {
        var previous: ServerProcess? = null
        var stop = false
        synchronized(lock) {
            val removed = uiOwners.remove(owner) != null
            pruneUiOwnersLocked()
            if ((!removed && !uiDemand) || uiOwners.isNotEmpty()) return
            uiDemand = false
            requested = false
            generation++
            baseUrl = null
            preparing = false
            if (drainingOwner == null) {
                drainingOwner = process
                previous = process
                stop = true
            }
        }
        Bus.toolsStateChanged()
        if (stop) stopUnused(previous)
    }

    private fun prepareTools(ctx: Context) {
        if (!PyServers.isStarted()) PyServers.prepareAsync(ctx.applicationContext)
        else prepare(ctx.applicationContext, ctx.filesDir)
    }

    private fun pruneUiOwnersLocked() {
        val entries = uiOwners.keys.iterator()
        while (entries.hasNext()) {
            val owner = entries.next()
            if (owner is Activity && owner.isDestroyed) entries.remove()
        }
    }

    private fun stopUnused(owner: ServerProcess?) {
        val child = owner?.stop()
        Thread({
            val stopped = awaitManagementExit(child)
            synchronized(lock) {
                finishDrainLocked(owner, stopped)
            }
            Bus.toolsStateChanged()
        }, "elichika-management-release").apply { isDaemon = true }.start()
    }

    /** Tools-ready notification; standalone 3D/tool use never requests Go. */
    internal fun prepare(ctx: Context, root: File) {
        synchronized(lock) {
            context = ctx.applicationContext
            directory = root
            if (!requested || drainingOwner != null || failure != null || process?.isAlive() == true || preparing || suspended.isNotEmpty()) return
            launchLocked()
        }
        Bus.toolsStateChanged()
    }

    /** Fast main-thread reservation; the preparation worker awaits child exit. */
    internal fun suspendForService(): Lease {
        val owner: ServerProcess?
        val id: Long
        synchronized(lock) {
            id = ++nextLease
            suspended.add(id)
            generation++
            owner = process
            if (owner != null) drainingOwner = owner
            baseUrl = null
            preparing = false
        }
        // Do not hold our lock while acquiring ServerProcess's launch lock.
        // A launch in flight checks generation before spawning, or is stopped here.
        val child = owner?.stop()
        Bus.toolsStateChanged()
        return Lease(id, child, owner)
    }

    internal fun awaitSuspended(lease: Lease): Boolean {
        val stopped = awaitManagementExit(lease.child)
        synchronized(lock) { finishDrainLocked(lease.owner, stopped) }
        return stopped
    }

    /** Authenticated WebUI writes may span multiple commits. Never force-kill them. */
    private fun awaitManagementExit(child: Process?): Boolean = try {
        child?.waitFor()
        true
    } catch (_: InterruptedException) {
        Thread.currentThread().interrupt()
        false
    }

    private fun finishDrainLocked(owner: ServerProcess?, stopped: Boolean) {
        if (drainingOwner !== owner) return
        if (!stopped) {
            failure = "Management WebUI is still draining. Its owned process is retained; retry after it exits."
            return
        }
        if (process === owner) {
            process = null
            ownedPid = null
        }
        drainingOwner = null
        if (requested && suspended.isEmpty() && failure == null) launchLocked()
    }

    internal fun reportStopFailure() {
        synchronized(lock) {
            baseUrl = null
            preparing = false
            failure = "Management WebUI remains stopped because the previous server did not exit safely. Restart the app before retrying."
        }
        Bus.log(failure.orEmpty())
        Bus.toolsStateChanged()
    }

    /** Called only after this service's preparation and game/CLI child have exited. */
    internal fun releaseService(lease: Lease) {
        synchronized(lock) {
            if (!suspended.remove(lease.id) || suspended.isNotEmpty()) return
            if (drainingOwner == null) process = null
            preparing = false
            if (requested && drainingOwner == null && failure == null && context != null && directory != null) launchLocked()
        }
        Bus.toolsStateChanged()
    }

    private fun wanted(owner: ServerProcess, expected: Long): Boolean = synchronized(lock) {
        requested && drainingOwner == null && generation == expected && process === owner && suspended.isEmpty()
    }

    private fun launchLocked() {
        if (!requested || drainingOwner != null || suspended.isNotEmpty() || failure != null ||
            process?.isAlive() == true || preparing) return
        val appContext = context ?: return
        val root = directory ?: return
        val expected = ++generation
        val owner = ServerProcess(appContext)
        process = owner
        preparing = true
        failure = null
        baseUrl = null
        ownedPid = null
        Thread({
            val marker = CountDownLatch(1)
            var announcedUrl: String? = null
            try {
                val started = owner.startManagement(root, { wanted(owner, expected) }, { line ->
                    if (!line.startsWith(READY_PREFIX)) false else {
                        // Suppress the complete protocol line from the public log.
                        val announcement = runCatching { JSONObject(line.removePrefix(READY_PREFIX)) }.getOrNull()
                        val parsed = announcement?.optString("url")?.let(::loopbackUrl)
                        val pidValue = announcement?.opt("pid")
                        val pid = if (pidValue is Int && pidValue > 0) pidValue else if (
                            pidValue is Long && pidValue in 1..Int.MAX_VALUE
                        ) pidValue.toInt() else null
                        if (parsed != null && pid != null && wanted(owner, expected)) {
                            synchronized(lock) { if (wanted(owner, expected)) ownedPid = pid }
                            announcedUrl = parsed
                            marker.countDown()
                        }
                        true
                    }
                }, { code ->
                    synchronized(lock) {
                        if (drainingOwner === owner) {
                            // This callback runs after ServerProcess reaps the
                            // child, including when an earlier waiter was interrupted.
                            finishDrainLocked(owner, true)
                        } else if (generation == expected && process === owner) {
                            baseUrl = null
                            preparing = false
                            failure = "Management WebUI exited with code $code. Retry opening the panel."
                            process = null
                            ownedPid = null
                        }
                    }
                    marker.countDown()
                    Bus.toolsStateChanged()
                })
                if (!started) {
                    if (wanted(owner, expected)) fail(owner, expected,
                        owner.startupError() ?: "Management WebUI could not start. Check the console and retry.")
                    return@Thread
                }
                val launch = owner.currentLaunch() ?: error("Management WebUI exited before readiness.")
                val deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(5)
                while (wanted(owner, expected) && owner.owns(launch) && marker.count > 0 && System.nanoTime() < deadline) {
                    marker.await(100, TimeUnit.MILLISECONDS)
                }
                if (!wanted(owner, expected)) return@Thread
                val url = announcedUrl ?: error("Management WebUI did not report its private address.")
                val endpoint = ServerReadiness.endpoint(URI(url).rawAuthority)
                val result = ServerReadiness.await(endpoint, launch.token, { wanted(owner, expected) && owner.owns(launch) })
                synchronized(lock) {
                    if (wanted(owner, expected) && owner.owns(launch)) {
                        if (result == ServerReadiness.Result.READY) {
                            baseUrl = url
                            preparing = false
                            failure = null
                        } else error("Management WebUI readiness timed out. Retry opening the panel.")
                    }
                }
                Bus.toolsStateChanged()
            } catch (error: Exception) {
                fail(owner, expected, error.message ?: "Management WebUI preparation failed.")
            }
        }, "elichika-management-ready").apply { isDaemon = true }.start()
    }

    private fun fail(owner: ServerProcess, expected: Long, message: String) {
        synchronized(lock) {
            if (process === owner) {
                drainingOwner = owner
                baseUrl = null
                preparing = false
                if (generation == expected) failure = message.filter { it >= ' ' }.take(500)
            }
        }
        Bus.toolsStateChanged()
        val child = owner.stop()
        val stopped = awaitManagementExit(child)
        synchronized(lock) {
            finishDrainLocked(owner, stopped)
        }
        Bus.log(message)
        Bus.toolsStateChanged()
    }

    private fun loopbackUrl(value: String): String? = runCatching {
        val uri = URI(value)
        if (uri.scheme != "http" || uri.host != "127.0.0.1" || uri.port !in 1..65535 ||
            uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null ||
            !uri.rawPath.isNullOrEmpty()) return null
        "http://127.0.0.1:${uri.port}"
    }.getOrNull()
}
