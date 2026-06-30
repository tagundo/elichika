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
                val py = Python.getInstance()
                py.getModule("elichika_launch")
                    .callAttr("start", serverCwd.absolutePath, sukusta.absolutePath, Lang.effective(ctx))
                started = true
                Bus.log("[pyservers] 개발/모드 도구 웹 UI 시작 (:8772 / :8770)")
            } catch (e: Throwable) {
                Bus.log("[pyservers] 파이썬 도구 시작 실패: ${e.message}")
            }
        }
    }
}
