package com.tagundo.elichika

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import java.io.File

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

    override fun onCreate() {
        super.onCreate()
        server = ServerProcess(this)
        workDir = AssetInstaller.install(this) { Bus.log(it) }
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startServer()
            ACTION_STOP -> stopServer(stopSelfToo = true)
            ACTION_RUN -> runAction(
                intent.getStringArrayExtra(EXTRA_ARGS)?.toList() ?: emptyList(),
                intent.getBooleanExtra(EXTRA_STOP_SERVER, true)
            )
            ACTION_RESET_SERVER -> resetServer()
        }
        return START_STICKY
    }

    private fun startServer() {
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        // Tool web UIs come up alongside the server.
        PyServers.ensureStarted(this, workDir)
        val ok = server.startServer(workDir) { code ->
            Bus.log(getString(R.string.log_server_exited, code))
            Bus.setRunning(false)
            stopForegroundCompat()
            releaseWakeLock()
            stopSelf()
        }
        if (ok) {
            Bus.log(getString(R.string.log_server_starting))
            Bus.setRunning(true)
        } else {
            Bus.setRunning(server.isAlive())
        }
    }

    private fun stopServer(stopSelfToo: Boolean) {
        server.stop()
        Bus.setRunning(false)
        releaseWakeLock()
        stopForegroundCompat()
        if (stopSelfToo) stopSelf()
    }

    /** Run a one-shot CLI verb; optionally stop the server first to avoid DB locks. */
    private fun runAction(args: List<String>, stopFirst: Boolean) {
        if (args.isEmpty()) return
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        if (stopFirst && server.isAlive()) {
            Bus.log(getString(R.string.log_action_stop_first))
            server.stop()
            Bus.setRunning(false)
        }
        Bus.log(getString(R.string.log_action_run, args.joinToString(" ")))
        val started = server.runOnce(args, workDir) { code ->
            Bus.log(getString(R.string.log_action_done, code))
            releaseWakeLock()
            stopForegroundCompat()
            stopSelf()
        }
        if (!started) {
            releaseWakeLock()
            stopForegroundCompat()
            stopSelf()
        }
    }

    /**
     * "Reset server": stop the server, restore the bundled vanilla game data
     * (removing every installed mod), then reset all accounts back to a
     * new-account state while keeping their logins (reset_accounts CLI verb).
     * The file restore copies hundreds of MB, so it runs off the main thread.
     */
    private fun resetServer() {
        startForeground(NOTIF_ID, buildNotification())
        acquireWakeLock()
        if (server.isAlive()) {
            Bus.log(getString(R.string.log_action_stop_first))
            server.stop()
            Bus.setRunning(false)
        }
        Thread {
            try {
                Bus.log(getString(R.string.log_reset_restore))
                AssetInstaller.resetServerData(this) { Bus.log(it) }
                Bus.log(getString(R.string.log_reset_accounts))
                val started = server.runOnce(listOf("reset_accounts"), workDir) { code ->
                    Bus.log(getString(R.string.log_reset_done, code))
                    releaseWakeLock()
                    stopForegroundCompat()
                    stopSelf()
                }
                if (!started) {
                    releaseWakeLock()
                    stopForegroundCompat()
                    stopSelf()
                }
            } catch (e: Exception) {
                Bus.log(getString(R.string.log_reset_failed, e.message ?: ""))
                releaseWakeLock()
                stopForegroundCompat()
                stopSelf()
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
        val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            Notification.Builder(this, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(this)
        return b.setContentTitle(getString(R.string.notif_running))
            .setContentText(getString(R.string.notif_text))
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(tap)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        releaseWakeLock()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_START = "com.tagundo.elichika.START"
        const val ACTION_STOP = "com.tagundo.elichika.STOP"
        const val ACTION_RUN = "com.tagundo.elichika.RUN"
        const val ACTION_RESET_SERVER = "com.tagundo.elichika.RESET_SERVER"
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
