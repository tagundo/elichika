package com.tagundo.elichika

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Build
import android.os.IBinder
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.Environment
import org.json.JSONObject
import java.io.File
import java.util.ArrayDeque
import java.util.concurrent.CountDownLatch

/**
 * Foreground service that owns the elichika server subprocess so Android keeps
 * it alive with the screen off (the native replacement for termux-wake-lock).
 * Also drives one-shot CLI actions (download_packs, rebuild_assets, …) declared
 * in assets/actions.json.
 */
class ServerService : Service() {

    private lateinit var server: ServerProcess
    private var wakeLock: PowerManager.WakeLock? = null
    private lateinit var workDir: File
    private lateinit var managementLease: ManagementServer.Lease
    private val preparationFinished = CountDownLatch(1)
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var operation = 0L
    private var installing = false
    private var maintenance = false
    @Volatile private var archiveLease: ArchiveWorkerFence.Lease? = null
    private var stopAfterMaintenance = false
    private var stopping = false
    private var initializing = true
    private var closing = false
    private var stopWhenReady = false
    private var afterDestroy: Intent? = null
    @Volatile private var destroyed = false
    internal var isReady = false
        private set
    internal var initializationFailure: Throwable? = null
        private set
    private val pendingCommands = ArrayDeque<Intent>()
    internal var holdRequest: String? = null
        private set
    private var autoStop: Runnable? = null
    private val preferencesChanged = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == ServerSettings.AUTO_STOP_MINUTES) main.post {
            if (Bus.serverRunning && server.isAlive() && !installing && !maintenance) scheduleAutoStop()
        }
    }

    override fun onCreate() {
        super.onCreate()
        managementLease = ManagementServer.suspendForService()
        server = ServerProcess(this)
        current = this
        getSharedPreferences(ServerSettings.PREFS, MODE_PRIVATE)
            .registerOnSharedPreferenceChangeListener(preferencesChanged)
        createChannel()
        Bus.addListener(this, {}, {
            if (current === this && !destroyed && !closing) {
                getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildNotification())
            }
        })
        // Claim the foreground immediately, then keep the main thread available
        // for console input and Stop while the large first-install copy runs.
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        val appContext = applicationContext
        Thread({
            try {
                check(ManagementServer.awaitSuspended(managementLease)) { "Management WebUI did not stop. Server preparation was left unchanged." }
                // A destroyed service may still own cancelling Python transfers.
                // Keep both management leases suspended, but wait off main before
                // payload preparation or any queued game/tool command can proceed.
                if (archiveWorkers.isBusy()) Bus.log(getString(R.string.log_archive_draining))
                archiveWorkers.awaitIdle()
                if (destroyed || current !== this) return@Thread
                val prepared = AssetInstaller.install(appContext, ::preparationChanged) { Bus.log(it) }
                if (destroyed) return@Thread
                // Cold Chaquopy initialization also belongs off the UI thread.
                PyServers.ensureStarted(appContext, prepared)
                main.post {
                    if (current !== this || destroyed) return@post
                    workDir = prepared
                    initializing = false
                    isReady = true
                    getSystemService(NotificationManager::class.java)
                        .notify(NOTIF_ID, buildNotification())
                    if (stopWhenReady) {
                        Bus.setRunning(false)
                        finishService()
                    } else {
                        val commands = pendingCommands.toList()
                        pendingCommands.clear()
                        for (command in commands) {
                            if (closing) break
                            dispatchCommand(command)
                        }
                    }
                }
            } catch (error: PayloadUpgrade.CostumeRecoveryRequired) {
                main.post {
                    if (current !== this || destroyed) return@post
                    // Only the recovery tools may reserve this unprepared root.
                    // ServerProcess still requires a CLEAN check for every Go/CLI launch.
                    workDir = appContext.filesDir
                    initializing = false
                    isReady = true
                    Bus.log(error.message.orEmpty())
                    Bus.setRunning(false)
                    val holds = pendingCommands.filter { it.action == ACTION_PREPARE_INSTALL }
                    pendingCommands.clear()
                    if (stopWhenReady) finishService() else {
                        holds.forEach(::dispatchCommand)
                        main.postDelayed({
                            if (current === this && !installing && !maintenance && !Bus.serverRunning) finishService()
                        }, 30_000L)
                    }
                }
            } catch (error: Exception) {
                main.post {
                    if (current !== this || destroyed) return@post
                    initializing = false
                    initializationFailure = error
                    pendingCommands.clear()
                    Bus.log(getString(R.string.log_setup_failed, error.message ?: ""))
                    Bus.setRunning(false)
                    finishService()
                }
            } finally {
                preparationFinished.countDown()
            }
        }, "elichika-prepare").start()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (closing) {
            // An explicit new request can arrive after stopSelf() but before
            // onDestroy(). Run it in a fresh, fully initialized service instead.
            if (intent?.action == ACTION_STOP || intent == null) {
                cancellation++
                afterDestroy = null
                Bus.setRunning(false)
            } else {
                afterDestroy = Intent(intent)
                if (intent.action == ACTION_START) Bus.setStarting(true)
            }
            return START_NOT_STICKY
        }
        if (initializing) {
            if (archiveWorkers.isBusy() && intent?.action != ACTION_STOP) {
                Bus.log(getString(R.string.log_archive_draining))
            }
            when (intent?.action) {
                ACTION_STOP, null -> {
                    cancellation++
                    pendingCommands.clear()
                    cancelArchiveDownload()
                    stopWhenReady = true
                    Bus.setRunning(false)
                }
                else -> {
                    stopWhenReady = false
                    // Repeated Start taps/windows share one pending server start.
                    if (intent.action != ACTION_START || pendingCommands.none { it.action == ACTION_START }) {
                        pendingCommands.add(Intent(intent))
                    }
                    if (intent.action == ACTION_START) Bus.setStarting(true)
                }
            }
            return START_NOT_STICKY
        }
        if (intent == null) {
            stopSelf(startId)
            return START_NOT_STICKY
        }
        dispatchCommand(intent)
        return START_NOT_STICKY
    }

    private fun dispatchCommand(intent: Intent) {
        if (archiveWorkers.isBusy() && intent.action in listOf(ACTION_START, ACTION_RUN, ACTION_RESET_SERVER, ACTION_PREPARE_INSTALL)) {
            Bus.log(getString(if (archiveWorkers.isCancelling()) R.string.log_archive_draining else R.string.log_install_busy))
            return
        }
        if ((installing || maintenance) && intent.action in listOf(ACTION_START, ACTION_RUN, ACTION_RESET_SERVER)) {
            Bus.log(getString(R.string.log_install_busy))
            Bus.setRunning(Bus.serverRunning)
            return
        }
        when (intent.action) {
            ACTION_START -> {
                if (stopping) { Bus.setStarting(true); startAfterStop() } else startServer()
            }
            ACTION_STOP -> {
                cancellation++
                // The installer still owns its DB writes. Stop Go and cancel
                // restart, keeping foreground protection until the job finishes.
                when {
                    installing -> {
                        Bus.log(getString(R.string.log_install_restart_cancelled))
                        // A whole-job reservation may deliberately leave Go
                        // running until a nested stop is requested.
                        pauseReservedInstall()
                    }
                    maintenance -> { stopAfterMaintenance = true; cancelArchiveDownload(); server.stop() }
                    else -> stopServer(stopSelfToo = true)
                }
            }
            ACTION_RUN -> runAction(
                intent.getStringArrayExtra(EXTRA_ARGS)?.toList() ?: emptyList(),
                intent.getBooleanExtra(EXTRA_STOP_SERVER, true)
            )
            ACTION_RESET_SERVER -> resetServer()
            ACTION_PREPARE_INSTALL -> {
                holdRequest = intent.getStringExtra(EXTRA_HOLD_ID)
                // If the calling worker times out before acquiring the hold,
                // do not leave a foreground notification behind indefinitely.
                main.postDelayed({
                    if (current === this && !installing && !maintenance && !Bus.serverRunning) finishService()
                }, 30_000L)
            }
        }
    }

    private fun startServer(): Boolean {
        check(!archiveWorkers.isBusy()) { getString(if (archiveWorkers.isCancelling()) R.string.log_archive_draining else R.string.log_install_busy) }
        check(isReady) { "Server files are still being prepared" }
        if (server.isAlive()) return true
        val token = ++operation
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        val ok = server.startServer(workDir) { code -> main.post {
            if (token != operation) return@post
            Bus.log(getString(R.string.log_server_exited, code))
            Bus.setRunning(false)
            cancelAutoStop()
            if (!installing) finishService()
        } }
        Bus.setRunning(ok)
        if (ok) {
            Bus.log(getString(R.string.log_server_starting))
            awaitServerReadiness(token)
        } else {
            finishService()
        }
        return ok
    }

    private fun awaitServerReadiness(generation: Long) {
        val launch = server.currentLaunch() ?: return
        Thread({
            val endpoints = runCatching {
                ServerReadiness.endpoints(ServerConfig.read(workDir).optString("server_address", "0.0.0.0:8080"))
            }.getOrDefault(emptyList())
            val result = ServerReadiness.await(endpoints, launch.token, {
                operation == generation && !destroyed && server.owns(launch)
            })
            main.post {
                if (generation != operation || destroyed || closing || !server.owns(launch)) return@post
                when (result) {
                    ServerReadiness.Result.READY -> {
                        Bus.setServerReady()
                        Bus.log(getString(R.string.log_server_ready))
                        scheduleAutoStop()
                    }
                    ServerReadiness.Result.TIMED_OUT -> {
                        // Prevent the old exit callback or a delayed HTTP reply
                        // from changing a later start's state.
                        operation++
                        val process = server.stop()
                        Bus.setRunning(false)
                        Bus.setServerStartupFailed()
                        Bus.log(getString(R.string.log_server_ready_timeout))
                        Thread { ServerProcess.awaitStopped(process) }.start()
                        finishService()
                    }
                    ServerReadiness.Result.CANCELLED -> Unit
                }
            }
        }, "elichika-http-ready").start()
    }

    private fun stopServer(stopSelfToo: Boolean) {
        val token = ++operation // Ignore a stopped process's delayed exit callback.
        cancelAutoStop()
        val process = server.stop()
        Bus.setRunning(false)
        if (!stopSelfToo) return
        stopping = true
        Thread {
            ServerProcess.awaitStopped(process)
            main.post {
                if (token != operation) return@post
                stopping = false
                finishService()
            }
        }.start()
    }

    /** A second window can request Start before a previous Stop has fully exited. */
    private fun startAfterStop() {
        val token = ++operation
        val process = server.stop()
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        Thread {
            val stopped = ServerProcess.awaitStopped(process)
            main.post {
                if (token != operation) return@post
                stopping = false
                if (stopped) startServer() else {
                    Bus.setRunning(false)
                    finishService()
                }
            }
        }.start()
    }

    private fun finishService() {
        closing = true
        isReady = false
        maintenance = false
        stopAfterMaintenance = false
        stopping = false
        releaseWakeLock()
        stopForegroundCompat()
        stopSelf()
    }

    private fun preparationChanged(phase: AssetInstaller.PreparationPhase) {
        Bus.setPreparationPhase(phase)
    }

    private fun cancelAutoStop() {
        autoStop?.let { main.removeCallbacks(it) }
        autoStop = null
    }

    private fun scheduleAutoStop() {
        cancelAutoStop()
        val minutes = ServerSettings.autoStopMinutes(this)
        if (!Bus.serverReady) return
        if (minutes > 0) {
            val task = Runnable {
                cancellation++
                Bus.log(getString(R.string.log_auto_stop))
                stopServer(stopSelfToo = true)
            }
            autoStop = task
            main.postDelayed(task, minutes.toLong() * 60_000L)
        }
        getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildNotification())
    }

    // All controller calls below run on the main thread; process exit is awaited
    // on the Python job thread. The hold blocks other windows from opening DBs.
    internal fun reserveForInstall() {
        check(current === this) { "The server service changed; retry installation" }
        check(!archiveWorkers.isBusy()) { getString(if (archiveWorkers.isCancelling()) R.string.log_archive_draining else R.string.log_install_busy) }
        check(isReady) { "Server files are still being prepared" }
        check(!installing && !maintenance) { getString(R.string.log_install_busy) }
        installing = true
        if (stopping) operation++ // Cancel a previous hold's pending service shutdown.
        stopping = false
        cancelAutoStop()
        acquireWakeLock()
        startForeground(NOTIF_ID, buildNotification())
    }

    internal fun pauseReservedInstall(): Process? {
        check(current === this && installing) { "The installation hold changed" }
        operation++
        val process = server.stop()
        Bus.setRunning(false)
        return process
    }

    internal fun pauseForInstall(): Process? {
        reserveForInstall()
        return pauseReservedInstall()
    }

    internal fun canResumeAfterInstall(expectedCancellation: Long): Boolean =
        current === this && cancellation == expectedCancellation && installing

    internal fun resumeAfterInstall(expectedCancellation: Long): Boolean {
        if (!canResumeAfterInstall(expectedCancellation)) return false
        installing = false
        check(startServer()) { getString(R.string.log_error_exec_failed, "server restart failed") }
        return true
    }

    internal fun finishInstall() {
        if (current !== this) return
        installing = false
        if (!Bus.serverRunning) stopServer(stopSelfToo = true) else scheduleAutoStop()
    }

    /** Run a one-shot CLI verb; optionally stop the server first to avoid DB locks. */
    private fun runAction(args: List<String>, stopFirst: Boolean) {
        if (args.isEmpty()) return
        if (args.first() == "download_archive_profile") { runArchiveDownload(args); return }
        maintenance = true
        stopAfterMaintenance = false
        val token = ++operation
        cancelAutoStop()
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        var previous: Process? = null
        if (stopFirst && server.isAlive()) {
            Bus.log(getString(R.string.log_action_stop_first))
            previous = server.stop()
            Bus.setRunning(false)
        }
        Thread {
            val stopped = ServerProcess.awaitStopped(previous)
            main.post {
                if (token != operation) return@post
                if (!stopped || stopAfterMaintenance) { finishService(); return@post }
                Bus.log(getString(R.string.log_action_run, args.joinToString(" ")))
                val started = server.runOnce(args, workDir) { code -> main.post {
                    if (token != operation) return@post
                    Bus.log(getString(R.string.log_action_done, code))
                    finishService()
                } }
                if (!started) finishService()
            }
        }.start()
    }

    /** Cancellation keeps the shared ownership and its visible progress until reaped. */
    private fun cancelArchiveDownload() {
        if (archiveWorkers.cancelActive()) {
            val progress = Bus.archiveDownloadProgress ?: ArchiveDownloadProgress.preparing()
            Bus.setArchiveDownloadProgress(progress.copy(cancelling = true))
        }
    }

    /** Public archive downloads keep the same foreground maintenance ownership as CLI actions. */
    private fun runArchiveDownload(args: List<String>) {
        if (args.size != 4) {
            Bus.log(getString(R.string.archive_download_invalid_scope))
            if (!Bus.serverRunning) finishService()
            return
        }
        val lease = archiveWorkers.tryAcquire()
        if (lease == null) {
            Bus.log(getString(R.string.log_archive_draining))
            return
        }
        archiveLease = lease
        maintenance = true
        stopAfterMaintenance = false
        val token = ++operation
        val cancelled = lease.cancellation
        try {
            cancelAutoStop()
            acquireWakeLock()
            Bus.setArchiveDownloadProgress(ArchiveDownloadProgress.preparing())
            startForeground(NOTIF_ID, buildNotification())
            val previous = server.stop()
            Bus.setRunning(false)
            Thread({
                try {
                    check(ServerProcess.awaitStopped(previous)) { "The game server did not stop; no archive files were changed." }
                    if (cancelled.get() || destroyed) return@Thread
                    Bus.log(getString(R.string.archive_download_start, args[1], args[2], args[3]))
                    val config = assets.open("archive-hosted-catalog.json").bufferedReader().use { it.readText() }
                    @Suppress("DEPRECATION")
                    val library = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "sukusta")
                    val observer = ArchiveDownloadCallbacks(
                        { packet ->
                            val progress = ArchiveDownloadProgress.parse(packet)
                            main.post {
                                if (token == operation && !destroyed && !cancelled.get() && archiveWorkers.owns(lease)) {
                                    Bus.setArchiveDownloadProgress(progress)
                                }
                            }
                        },
                        { cancelled.get() || destroyed })
                    val raw = EmbeddedPython.instance(this).getModule("archive_profile_download_bridge")
                        .callAttr("run_android", workDir.absolutePath, library.absolutePath, config,
                            args[1], args[2], args[3], observer).toString()
                    val result = JSONObject(raw)
                    when (result.optString("status")) {
                        "done" -> Bus.log(getString(R.string.archive_download_done))
                        "cancelled" -> Bus.log(getString(R.string.archive_download_cancelled))
                        else -> Bus.log(getString(R.string.archive_download_failed, result.optString("error", "Unknown archive failure")))
                    }
                } catch (error: Throwable) {
                    Bus.log(getString(R.string.archive_download_failed, error.message ?: error.javaClass.simpleName))
                } finally {
                    // The Python call returns only after its pool has reaped all
                    // transfers. No cancellation/destroy path may release this.
                    archiveWorkers.complete(lease)
                    main.post {
                        // A delayed old callback cannot clear a newer lease's UI.
                        if (archiveWorkers.mayClearProgress(lease)) Bus.setArchiveDownloadProgress(null)
                        if (token == operation && !destroyed && archiveLease === lease) {
                            archiveLease = null
                            finishService()
                        }
                    }
                }
            }, "elichika-archive-download").start()
        } catch (error: Throwable) {
            // No worker was started: release the otherwise stranded reservation.
            archiveWorkers.complete(lease)
            if (archiveWorkers.mayClearProgress(lease)) Bus.setArchiveDownloadProgress(null)
            archiveLease = null
            Bus.log(getString(R.string.archive_download_failed, error.message ?: error.javaClass.simpleName))
            finishService()
        }
    }

    /**
     * "Reset server": stop the server, restore the bundled vanilla game data
     * (removing every installed mod), then reset all accounts back to a
     * new-account state while keeping their logins (reset_accounts CLI verb).
     * The file restore copies hundreds of MB, so it runs off the main thread.
     */
    private fun resetServer() {
        maintenance = true
        stopAfterMaintenance = false
        val token = ++operation
        cancelAutoStop()
        var previous: Process? = null
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        if (server.isAlive()) {
            Bus.log(getString(R.string.log_action_stop_first))
            previous = server.stop()
            Bus.setRunning(false)
        }
        Thread {
            try {
                check(ServerProcess.awaitStopped(previous)) { "Server did not stop" }
                Bus.log(getString(R.string.log_reset_restore))
                AssetInstaller.resetServerData(this, ::preparationChanged) { Bus.log(it) }
                Bus.log(getString(R.string.log_reset_accounts))
                main.post {
                    if (token != operation) return@post
                    if (stopAfterMaintenance) { finishService(); return@post }
                    val started = server.runOnce(listOf("reset_accounts"), workDir) { code -> main.post {
                        if (token != operation) return@post
                        Bus.log(getString(R.string.log_reset_done, code))
                        finishService()
                    } }
                    if (!started) finishService()
                }
            } catch (e: Exception) {
                main.post {
                    if (token != operation) return@post
                    Bus.log(getString(R.string.log_reset_failed, e.message ?: ""))
                    finishService()
                }
            }
        }.start()
    }

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "elichika:server").also {
            it.setReferenceCounted(false)
            it.acquire()
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION") stopForeground(true)
        }
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            val ch = NotificationChannel(
                CHANNEL, getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW
            )
            nm.createNotificationChannel(ch)
        }
    }

    private fun buildNotification(): Notification {
        val tap = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, ServerService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val minutes = ServerSettings.autoStopMinutes(this)
        val phase = Bus.preparationPhase
        val preparing = phase == AssetInstaller.PreparationPhase.PREPARING ||
            phase == AssetInstaller.PreparationPhase.UPDATING_GAME_DATA
        val dataProgress = Bus.payloadProgress.takeIf { phase == AssetInstaller.PreparationPhase.UPDATING_GAME_DATA }
        val archive = Bus.archiveDownloadProgress
        val text = when {
            archive?.cancelling == true -> getString(R.string.archive_download_cancelling)
            archive != null && archive.totalFiles == 0 -> getString(R.string.archive_download_preparing)
            archive != null -> getString(R.string.archive_download_progress, archive.percent, archive.completedFiles, archive.totalFiles)
            dataProgress != null -> getString(R.string.progress_work_detail, dataProgress.percent,
                PayloadProgress.stageLabel(this, dataProgress.stage), dataProgress.completed, dataProgress.total)
            phase == AssetInstaller.PreparationPhase.UPDATING_GAME_DATA -> getString(R.string.status_updating_game_data)
            initializing || preparing -> getString(R.string.notif_preparing_text)
            Bus.serverRunning && !Bus.serverReady -> getString(R.string.status_server_loading)
            installing -> getString(R.string.notif_installing_text)
            minutes > 0 -> getString(R.string.notif_auto_stop, minutes)
            else -> getString(R.string.notif_text)
        }
        val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            Notification.Builder(this, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(this)
        val title = when {
            initializing || preparing || (Bus.serverRunning && !Bus.serverReady) -> R.string.notif_preparing
            installing -> R.string.notif_installing
            else -> R.string.notif_running
        }
        if (archive != null) b.setProgress(100, archive.percent, archive.cancelling || archive.totalFiles == 0)
        else if (dataProgress != null) b.setProgress(100, dataProgress.percent, false)
        else if (initializing || preparing || (Bus.serverRunning && !Bus.serverReady)) b.setProgress(0, 0, true)
        return b.setContentTitle(getString(title))
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(tap)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(
                null, getString(R.string.stop_server), stop
            ).build())
            .build()
    }

    override fun onDestroy() {
        destroyed = true
        val archiveWorker = archiveLease
        // Mark only this service's lease. It may already have completed while
        // a newer service acquired a new lease; never cancel that newer owner.
        if (archiveWorker != null && archiveWorkers.cancel(archiveWorker)) {
            val progress = Bus.archiveDownloadProgress ?: ArchiveDownloadProgress.preparing()
            Bus.setArchiveDownloadProgress(progress.copy(cancelling = true))
        }
        Bus.removeListener(this)
        isReady = false
        pendingCommands.clear()
        operation++
        cancelAutoStop()
        getSharedPreferences(ServerSettings.PREFS, MODE_PRIVATE)
            .unregisterOnSharedPreferenceChangeListener(preferencesChanged)
        val previous = server.stop()
        if (current === this) {
            current = null
            Bus.setRunning(false)
        }
        releaseWakeLock()
        super.onDestroy()
        Thread({
            preparationFinished.await()
            if (archiveWorker != null) archiveWorkers.awaitFinished(archiveWorker)
            if (ServerProcess.awaitStopped(previous) && ManagementServer.awaitSuspended(managementLease)) {
                ManagementServer.releaseService(managementLease)
            } else {
                ManagementServer.reportStopFailure()
            }
        }, "elichika-management-resume").apply { isDaemon = true }.start()
        afterDestroy?.let { next -> applicationContext.startForegroundService(next) }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        // Process lifetime, including forced Service destruction/recreation.
        private val archiveWorkers = ArchiveWorkerFence()
        @Volatile internal var current: ServerService? = null
            private set
        /** No capability is published through Bus, logs, readiness, or an Intent. */
        internal fun localWebuiToken(): String? {
            val owner = current ?: return null
            if (!Bus.serverRunning || !Bus.serverReady || owner.destroyed || owner.closing || owner.stopping) return null
            return owner.server.localWebuiToken()
        }
        internal var cancellation = 0L
            private set
        const val ACTION_START = "com.tagundo.elichika.START"
        const val ACTION_STOP = "com.tagundo.elichika.STOP"
        const val ACTION_RUN = "com.tagundo.elichika.RUN"
        const val ACTION_RESET_SERVER = "com.tagundo.elichika.RESET_SERVER"
        internal const val ACTION_PREPARE_INSTALL = "com.tagundo.elichika.PREPARE_INSTALL"
        internal const val EXTRA_HOLD_ID = "hold_id"
        const val EXTRA_ARGS = "args"
        const val EXTRA_STOP_SERVER = "stop_server"
        private const val CHANNEL = "elichika_server"
        private const val NOTIF_ID = 1

        fun start(ctx: Context) = ctx.startForegroundService(
            Intent(ctx, ServerService::class.java).setAction(ACTION_START)
        )

        fun stop(ctx: Context) = ctx.startService(
            Intent(ctx, ServerService::class.java).setAction(ACTION_STOP)
        )

        fun resetServer(ctx: Context) = ctx.startForegroundService(
            Intent(ctx, ServerService::class.java).setAction(ACTION_RESET_SERVER)
        )

        fun runAction(ctx: Context, args: List<String>, stopServer: Boolean) =
            ctx.startForegroundService(
                Intent(ctx, ServerService::class.java)
                    .setAction(ACTION_RUN)
                    .putExtra(EXTRA_ARGS, args.toTypedArray())
                    .putExtra(EXTRA_STOP_SERVER, stopServer)
            )
    }
}
