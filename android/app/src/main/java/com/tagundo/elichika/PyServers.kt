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

    fun ensureStarted(ctx: Context, serverCwd: File) {
        if (started) return
        synchronized(this) {
            if (started) return
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
                        Lang.effective(ctx), astcenc)
                started = true
                Bus.log(ctx.getString(R.string.log_pyservers_started))
            } catch (e: Throwable) {
                Bus.log(ctx.getString(R.string.log_pyservers_failed, e.message ?: ""))
            }
        }
    }
}
