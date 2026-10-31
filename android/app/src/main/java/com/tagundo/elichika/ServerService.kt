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
import java.io.File
import java.util.ArrayDeque

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
    private val main = Handler(Looper.getMainLooper())
    private var operation = 0L
    private var installing = false
    private var maintenance = false
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
        server = ServerProcess(this)
        current = this
        getSharedPreferences(ServerSettings.PREFS, MODE_PRIVATE)
            .registerOnSharedPreferenceChangeListener(preferencesChanged)
        createChannel()
        // Claim the foreground immediately, then keep the main thread available
        // for console input and Stop while the large first-install copy runs.
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        val appContext = applicationContext
        Thread({
            try {
                val prepared = AssetInstaller.install(appContext) { Bus.log(it) }
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
            when (intent?.action) {
                ACTION_STOP, null -> {
                    cancellation++
                    pendingCommands.clear()
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
                // The installer still owns its DB writes. Cancel only the pending
                // restart, keeping its foreground protection until finish().
                when {
                    installing -> Bus.log(getString(R.string.log_install_restart_cancelled))
                    maintenance -> { stopAfterMaintenance = true; server.stop() }
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
            finishService()
        } }
        Bus.setRunning(ok)
        if (ok) {
            Bus.log(getString(R.string.log_server_starting))
            scheduleAutoStop()
        } else {
            finishService()
        }
        return ok
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

    private fun cancelAutoStop() {
        autoStop?.let { main.removeCallbacks(it) }
        autoStop = null
    }

    private fun scheduleAutoStop() {
        cancelAutoStop()
        val minutes = ServerSettings.autoStopMinutes(this)
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
    internal fun pauseForInstall(): Process? {
        check(current === this) { "The server service changed; retry installation" }
        check(isReady) { "Server files are still being prepared" }
        check(!installing && !maintenance) { getString(R.string.log_install_busy) }
        installing = true
        stopping = false
        operation++
        cancelAutoStop()
        val process = server.stop()
        Bus.setRunning(false)
        acquireWakeLock()
        startForeground(NOTIF_ID, buildNotification())
        return process
    }

    internal fun resumeAfterInstall(expectedCancellation: Long): Boolean {
        if (current !== this || cancellation != expectedCancellation || !installing) return false
        installing = false
        check(startServer()) { getString(R.string.log_error_exec_failed, "server restart failed") }
        return true
    }

    internal fun finishInstall() {
        if (current !== this) return
        installing = false
        if (!Bus.serverRunning) stopServer(stopSelfToo = true)
    }

    /** Run a one-shot CLI verb; optionally stop the server first to avoid DB locks. */
    private fun runAction(args: List<String>, stopFirst: Boolean) {
        if (args.isEmpty()) return
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
                AssetInstaller.resetServerData(this) { Bus.log(it) }
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
        val text = when {
            initializing -> getString(R.string.notif_preparing_text)
            installing -> getString(R.string.notif_installing_text)
            minutes > 0 -> getString(R.string.notif_auto_stop, minutes)
            else -> getString(R.string.notif_text)
        }
        val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            Notification.Builder(this, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(this)
        val title = when {
            initializing -> R.string.notif_preparing
            installing -> R.string.notif_installing
            else -> R.string.notif_running
        }
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
        isReady = false
        pendingCommands.clear()
        operation++
        cancelAutoStop()
        getSharedPreferences(ServerSettings.PREFS, MODE_PRIVATE)
            .unregisterOnSharedPreferenceChangeListener(preferencesChanged)
        server.stop()
        if (current === this) {
            current = null
            Bus.setRunning(false)
        }
        releaseWakeLock()
        super.onDestroy()
        afterDestroy?.let { next -> applicationContext.startForegroundService(next) }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        @Volatile internal var current: ServerService? = null
            private set
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
