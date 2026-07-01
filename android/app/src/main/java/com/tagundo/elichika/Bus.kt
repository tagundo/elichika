package com.tagundo.elichika

import android.os.Handler
import android.os.Looper
import java.io.BufferedWriter
import java.io.File
import java.io.FileWriter

/**
 * Tiny in-process event bus connecting the foreground service / process runners
 * to the Activity, without the ceremony of a bound service. The service appends
 * log lines and flips the running flag; the Activity registers a listener while
 * visible.
 */
object Bus {
    private val main = Handler(Looper.getMainLooper())
    private val buffer = StringBuilder()
    private const val MAX = 200_000

    // Optional persistent sink: a user-visible log file under the shared sukusta
    // folder, so people can attach it when reporting an issue. Rotated when large.
    private val fileLock = Any()
    private var logWriter: BufferedWriter? = null

    @Volatile var serverRunning = false
        private set

    var logListener: ((String) -> Unit)? = null
    var stateListener: ((Boolean) -> Unit)? = null

    fun snapshot(): String = synchronized(buffer) { buffer.toString() }

    /** Start mirroring log lines to [file] (e.g. Download/sukusta/logs/elichika.log). */
    fun attachLogFile(file: File) {
        synchronized(fileLock) {
            if (logWriter != null) return
            runCatching {
                file.parentFile?.mkdirs()
                if (file.exists() && file.length() > 2_000_000L) file.writeText("") // rotate
                logWriter = BufferedWriter(FileWriter(file, true))
                logWriter?.write("\n==== session " + System.currentTimeMillis() + " ====\n")
                logWriter?.flush()
            }
        }
    }

    fun log(line: String) {
        synchronized(buffer) {
            buffer.append(line)
            if (!line.endsWith("\n")) buffer.append('\n')
            if (buffer.length > MAX) buffer.delete(0, buffer.length - MAX)
        }
        synchronized(fileLock) {
            logWriter?.let { w ->
                runCatching {
                    w.write(if (line.endsWith("\n")) line else line + "\n")
                    w.flush()
                }
            }
        }
        main.post { logListener?.invoke(line) }
    }

    fun setRunning(running: Boolean) {
        serverRunning = running
        main.post { stateListener?.invoke(running) }
    }
}
