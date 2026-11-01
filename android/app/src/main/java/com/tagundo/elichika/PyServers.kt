package com.tagundo.elichika

import android.content.Context
import android.os.Environment
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

/**
 * Boots the embedded Python (Chaquopy) once and starts the two stdlib web UIs
 * (adminui dev tools on :8772, webtools modding tools on :8770) via
 * elichika_launch.py. They keep running in-process; the WebView tabs point at
 * them. All tool logic lives in Python so adding a tool needs no app change.
 */
object PyServers {

    @Volatile private var started = false
    @Volatile private var preparing = false
    @Volatile private var preparationError: Throwable? = null
    private val preparationLock = Any()

    /** Open the local editors without launching the game server or a foreground service. */
    fun prepareAsync(ctx: Context) {
        val appContext = ctx.applicationContext
        synchronized(preparationLock) {
            if (started || preparing) return
            preparing = true
            preparationError = null
        }
        Bus.toolsStateChanged()
        Thread({
            try {
                val directory = AssetInstaller.install(appContext) { Bus.log(it) }
                ensureStarted(appContext, directory)
            } catch (error: Throwable) {
                preparationError = error
                Bus.log(appContext.getString(R.string.log_pyservers_failed, error.message ?: ""))
            } finally {
                preparing = false
                Bus.toolsStateChanged()
            }
        }, "elichika-tools-prepare").apply { isDaemon = true }.start()
    }

    fun ensureStarted(ctx: Context, serverCwd: File): Boolean {
        if (started) return true
        synchronized(this) {
            if (started) return true
            try {
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(ctx.applicationContext))
                }
                // shared Download/sukusta (same as Termux), so the modding tools'
                // extracted/ + modded/ folders are user-visible. Needs storage access.
                val sukusta = File(
                    Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                    "sukusta"
                )
                // bundled ASTC encoder (shipped as a native lib so it's executable
                // from nativeLibraryDir) — lets the texture tool import compressed
                // ASTC textures on-device. Pass null if it isn't present.
                val astcenc = File(ctx.applicationInfo.nativeLibraryDir, "libastcenc.so")
                    .takeIf { it.exists() }?.absolutePath
                val py = Python.getInstance()
                py.getModule("elichika_launch")
                    .callAttr("start", serverCwd.absolutePath, sukusta.absolutePath,
                        Lang.effective(ctx), astcenc, AndroidServerController(ctx.applicationContext))
                started = true
                preparationError = null
                Bus.log(ctx.getString(R.string.log_pyservers_started))
                Bus.toolsStateChanged()
                return true
            } catch (e: Throwable) {
                preparationError = e
                Bus.log(ctx.getString(R.string.log_pyservers_failed, e.message ?: ""))
                Bus.toolsStateChanged()
                return false
            }
        }
    }

    fun isStarted(): Boolean = started
    fun isPreparing(): Boolean = preparing
    fun hasPreparationError(): Boolean = preparationError != null
}
