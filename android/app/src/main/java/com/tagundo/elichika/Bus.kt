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
    @Volatile var serverStarting = false
        private set

    private data class Listener(
        val log: (String) -> Unit,
        val state: (Boolean) -> Unit,
        val toolsState: () -> Unit,
    )
    private val listeners = LinkedHashMap<Any, Listener>()

    // Each visible Activity owns its subscription. Pausing or closing one window
    // must not remove another window's callbacks.
    fun addListener(owner: Any, log: (String) -> Unit, state: (Boolean) -> Unit,
                    toolsState: () -> Unit = {}) {
        listeners[owner] = Listener(log, state, toolsState)
    }

    fun removeListener(owner: Any) {
        listeners.remove(owner)
    }

    fun snapshot(): String = synchronized(buffer) { buffer.toString() }

    /** Clear the in-memory console buffer (the on-disk log file is left intact). */
    fun clear() = synchronized(buffer) { buffer.setLength(0) }

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
        main.post { listeners.values.toList().forEach { it.log(line) } }
    }

    fun setRunning(running: Boolean) {
        serverRunning = running
        serverStarting = false
        main.post { listeners.values.toList().forEach { it.state(running) } }
    }

    /** Includes queued starts while payload/Python preparation runs off-main. */
    fun setStarting(starting: Boolean) {
        serverStarting = starting
        main.post { listeners.values.toList().forEach { it.state(serverRunning) } }
    }

    /** Local editing tools may become ready while the game server stays stopped. */
    fun toolsStateChanged() {
        main.post { listeners.values.toList().forEach { it.toolsState() } }
    }
}
