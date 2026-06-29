package com.tagundo.elichika

import android.os.Handler
import android.os.Looper

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

    @Volatile var serverRunning = false
        private set

    var logListener: ((String) -> Unit)? = null
    var stateListener: ((Boolean) -> Unit)? = null

    fun snapshot(): String = synchronized(buffer) { buffer.toString() }

    fun log(line: String) {
        synchronized(buffer) {
            buffer.append(line)
            if (!line.endsWith("\n")) buffer.append('\n')
            if (buffer.length > MAX) buffer.delete(0, buffer.length - MAX)
        }
        main.post { logListener?.invoke(line) }
    }

    fun setRunning(running: Boolean) {
        serverRunning = running
        main.post { stateListener?.invoke(running) }
    }
}
