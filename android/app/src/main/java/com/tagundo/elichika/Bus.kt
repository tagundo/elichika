package com.tagundo.elichika

import android.os.Handler
import android.os.Looper
import java.io.BufferedWriter
import java.io.File
import java.io.FileWriter
import java.util.ArrayDeque
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

internal data class ConsoleLogRead(val start: Long, val end: Long, val reset: Boolean, val text: String)
internal data class LogFileStatus(val pendingBytes: Long, val unmirroredLines: Long, val unmirroredBytes: Long,
                                  val paused: Boolean)

/** Character offsets let each visible window append only its own unseen tail. */
internal class ConsoleLogBuffer(private val maximum: Int) {
    private val chunks = ArrayDeque<String>()
    private var start = 0L
    private var end = 0L

    @Synchronized fun append(text: String) {
        chunks.addLast(text)
        end += text.length
        var excess = (end - start - maximum).coerceAtLeast(0).toInt()
        while (excess > 0) {
            val first = chunks.removeFirst()
            val remove = minOf(excess, first.length)
            start += remove
            excess -= remove
            if (remove < first.length) chunks.addFirst(first.substring(remove))
        }
    }

    @Synchronized fun clear() {
        chunks.clear()
        // A clear is a distinct revision even when the old tail was empty.
        end++
        start = end
    }

    @Synchronized fun read(after: Long): ConsoleLogRead {
        val reset = after < start || after > end
        if (!reset && after == end) return ConsoleLogRead(start, end, false, "")
        var skip = if (reset) 0L else after - start
        val result = StringBuilder()
        for (chunk in chunks) {
            if (skip >= chunk.length) skip -= chunk.length
            else {
                result.append(chunk, skip.toInt(), chunk.length)
                skip = 0
            }
        }
        return ConsoleLogRead(start, end, reset, result.toString())
    }
}

/**
 * Tiny in-process event bus connecting the foreground service / process runners
 * to the Activity, without the ceremony of a bound service. The service appends
 * log lines and flips the running flag; the Activity registers a listener while
 * visible.
 */
object Bus {
    private val main = Handler(Looper.getMainLooper())
    private const val MAX = 200_000
    private const val LOG_INTERVAL_MS = 100L
    internal const val MAX_PENDING_FILE_BYTES = 4L * 1024 * 1024
    private val buffer = ConsoleLogBuffer(MAX)
    private var logDispatchPending = false
    private var pendingLogCount = 0
    private var pendingSingleLine = ""
    private var pendingCdnChange = false
    private var dispatchedOffset = 0L

    // Optional persistent sink: a user-visible log file under the shared sukusta
    // folder, so people can attach it when reporting an issue. Rotated when large.
    private val fileLock = Any()
    private val disk = Executors.newSingleThreadScheduledExecutor { task ->
        Thread(task, "elichika-log-file").apply { isDaemon = true }
    }
    private var logTarget: File? = null
    private var diskDrainPending = false
    private val diskLines = ArrayDeque<String>()
    // A conservative UTF-8/UTF-16 plus object estimate. Includes the worker's
    // active batch until its write completes, not only the waiting queue.
    private var pendingFileBytes = 0L
    private var unmirroredLines = 0L
    private var unmirroredBytes = 0L
    private var fileOverflowed = false
    @Volatile var logFilePaused = false
        private set
    private var logWriter: BufferedWriter? = null

    @Volatile var serverRunning = false
        private set
    @Volatile var serverReady = false
        private set
    @Volatile var serverStartupFailed = false
        private set
    @Volatile var serverStarting = false
        private set
    @Volatile var preparationPhase = AssetInstaller.PreparationPhase.IDLE
        private set

    @Volatile internal var payloadProgress: PayloadProgress.State? = null
        private set
    private var progressDispatch: Runnable? = null

    private data class Listener(
        val log: (String) -> Unit,
        val state: (Boolean) -> Unit,
        val toolsState: () -> Unit,
        val cdnChanged: () -> Unit,
    )
    private val listeners = LinkedHashMap<Any, Listener>()

    // Each visible Activity owns its subscription. Pausing or closing one window
    // must not remove another window's callbacks.
    fun addListener(owner: Any, log: (String) -> Unit, state: (Boolean) -> Unit,
                    toolsState: () -> Unit = {}, cdnChanged: () -> Unit = {}) {
        listeners[owner] = Listener(log, state, toolsState, cdnChanged)
    }

    fun removeListener(owner: Any) {
        listeners.remove(owner)
    }

    fun snapshot(): String = buffer.read(-1).text

    internal fun readLog(after: Long): ConsoleLogRead = buffer.read(after)

    /** Clear the in-memory console buffer (the on-disk log file is left intact). */
    fun clear() {
        synchronized(buffer) {
            buffer.clear()
            queueLogDispatch("")
        }
    }

    /** Start mirroring log lines to [file] (e.g. Download/sukusta/logs/elichika.log). */
    fun attachLogFile(file: File) {
        synchronized(fileLock) {
            if (logTarget != null || fileOverflowed) return
            logTarget = file
            scheduleDiskDrain(0L)
        }
    }

    fun log(line: String) {
        val text = if (line.endsWith("\n")) line else line + "\n"
        var warning: String? = null
        synchronized(buffer) {
            buffer.append(text)
            queueLogDispatch(line)
            synchronized(fileLock) {
                if (logTarget != null || logFilePaused) {
                    val bytes = retainedFileBytes(text)
                    if (fileOverflowed || (logFilePaused && logTarget == null) ||
                        pendingFileBytes + bytes > MAX_PENDING_FILE_BYTES) {
                        addUnmirrored(1, bytes)
                        if (!fileOverflowed && logTarget != null) {
                            fileOverflowed = true
                            logFilePaused = true
                            warning = "[log file paused] Storage could not keep up; the 4 MiB pending limit was reached. " +
                                "Already queued lines will be written in order. Check storage and restart the app; " +
                                "later lines remain available only in the recent Console tail."
                        }
                    } else {
                        diskLines.addLast(text)
                        pendingFileBytes += bytes
                        scheduleDiskDrain(LOG_INTERVAL_MS)
                    }
                }
            }
        }
        warning?.let(::logFileNotice)
    }

    private fun retainedFileBytes(text: String): Long = 64L + text.length.toLong() * 3L

    /** fileLock held. Counters saturate rather than wrap after prolonged failure. */
    private fun addUnmirrored(lines: Long, bytes: Long) {
        unmirroredLines = if (Long.MAX_VALUE - unmirroredLines < lines) Long.MAX_VALUE else unmirroredLines + lines
        unmirroredBytes = if (Long.MAX_VALUE - unmirroredBytes < bytes) Long.MAX_VALUE else unmirroredBytes + bytes
    }

    /** Called outside producer/file locks; notices never re-enter the file sink. */
    private fun logFileNotice(value: String) = synchronized(buffer) {
        if (value.isNotEmpty()) buffer.append(value + "\n")
        queueLogDispatch(value)
    }

    internal fun logFileStatus(): LogFileStatus = synchronized(fileLock) {
        LogFileStatus(pendingFileBytes, unmirroredLines, unmirroredBytes, logFilePaused)
    }

    /** Called with the buffer lock; one notification per interval, not per line. */
    private fun queueLogDispatch(line: String) {
        pendingLogCount++
        pendingSingleLine = line
        pendingCdnChange = pendingCdnChange || line.contains("cdn_cache:")
        if (logDispatchPending) return
        logDispatchPending = true
        main.postDelayed({
            val update = synchronized(buffer) {
                val tail = buffer.read(dispatchedOffset)
                val text = if (pendingLogCount == 1) pendingSingleLine else tail.text
                val cdn = pendingCdnChange
                dispatchedOffset = tail.end
                pendingLogCount = 0
                pendingSingleLine = ""
                pendingCdnChange = false
                logDispatchPending = false
                text to cdn
            }
            listeners.values.toList().forEach {
                it.log(update.first)
                if (update.second) it.cdnChanged()
            }
        }, LOG_INTERVAL_MS)
    }

    /** Called with fileLock. Slow shared-storage writes only run on this worker. */
    private fun scheduleDiskDrain(delay: Long) {
        if (diskDrainPending) return
        diskDrainPending = true
        disk.schedule({ drainLogFile() }, delay, TimeUnit.MILLISECONDS)
    }

    private fun drainLogFile() {
        data class Batch(val target: File, val lines: ArrayList<String>, val bytes: Long)
        val batch = synchronized(fileLock) {
            diskDrainPending = false
            val target = logTarget ?: return
            val lines = ArrayList<String>(diskLines.size)
            while (diskLines.isNotEmpty()) lines.add(diskLines.removeFirst())
            Batch(target, lines, lines.sumOf(::retainedFileBytes))
        }
        var warning: String? = null
        var stateChanged = false
        try {
            if (logWriter == null) {
                val file = batch.target
                file.parentFile?.mkdirs()
                if (file.exists() && file.length() > 2_000_000L) file.writeText("") // existing session rotation
                logWriter = BufferedWriter(FileWriter(file, true))
                logWriter!!.write("\n==== session " + System.currentTimeMillis() + " ====\n")
            }
            for (line in batch.lines) logWriter!!.write(line)
            logWriter!!.flush()
            synchronized(fileLock) {
                if (!fileOverflowed && logFilePaused) { logFilePaused = false; stateChanged = true }
            }
        } catch (_: Exception) {
            runCatching { logWriter?.close() }
            logWriter = null
            synchronized(fileLock) {
                // Match the existing best-effort sink when storage permission
                // is unavailable; a later Activity may retry attaching it.
                logTarget = null
                if (!logFilePaused) warning = "[log file paused] Storage writing failed. Check storage and reopen the app. " +
                    "Recent Console logs remain available; queued file lines could not be confirmed."
                logFilePaused = true
                val queuedBytes = diskLines.sumOf(::retainedFileBytes)
                addUnmirrored((batch.lines.size + diskLines.size).toLong(), batch.bytes + queuedBytes)
                pendingFileBytes -= queuedBytes
                diskLines.clear()
            }
        } finally {
            // Release active string references before making the capacity reusable.
            batch.lines.clear()
            synchronized(fileLock) { pendingFileBytes -= batch.bytes }
        }
        if (warning != null) logFileNotice(warning!!)
        else if (stateChanged) logFileNotice("")
    }

    /** Queue a final flush without doing disk I/O on an Activity/service thread. */
    fun flushLogFile() { synchronized(fileLock) { scheduleDiskDrain(0L) } }

    /** Test/export barrier; callers must not block Android's main looper. */
    internal fun awaitLogFile(timeoutMillis: Long): Boolean {
        check(Looper.myLooper() != Looper.getMainLooper())
        val done = CountDownLatch(1)
        disk.execute { drainLogFile(); done.countDown() }
        return done.await(timeoutMillis, TimeUnit.MILLISECONDS)
    }

    fun setRunning(running: Boolean) {
        val wasRunning = serverRunning
        serverRunning = running
        if (!running || !wasRunning) serverReady = false
        if (running) serverStartupFailed = false
        serverStarting = false
        if (!running) flushLogFile()
        main.post { listeners.values.toList().forEach { it.state(serverRunning) } }
    }

    fun setServerReady() {
        if (!serverRunning) return
        serverReady = true
        serverStartupFailed = false
        main.post { listeners.values.toList().forEach { it.state(serverRunning) } }
    }

    fun setServerStartupFailed() {
        serverReady = false
        serverStartupFailed = true
        main.post { listeners.values.toList().forEach { it.state(serverRunning) } }
    }

    /** Includes queued starts while payload/Python preparation runs off-main. */
    fun setStarting(starting: Boolean) {
        serverStarting = starting
        if (starting) serverStartupFailed = false
        if (starting && preparationPhase == AssetInstaller.PreparationPhase.FAILED) {
            preparationPhase = AssetInstaller.PreparationPhase.IDLE
            setPayloadProgress(null)
        }
        main.post { listeners.values.toList().forEach { it.state(serverRunning) } }
    }

    /** The installer owns this phase until its atomic work finishes, even after Stop. */
    fun setPreparationPhase(phase: AssetInstaller.PreparationPhase) {
        preparationPhase = phase
        if (phase == AssetInstaller.PreparationPhase.IDLE || phase == AssetInstaller.PreparationPhase.FAILED) {
            setPayloadProgress(null)
        }
        main.post { listeners.values.toList().forEach { it.state(serverRunning) } }
    }

    /** Replay the newest value after rotation; coalesce display work, never DB callbacks. */
    @Synchronized internal fun setPayloadProgress(progress: PayloadProgress.State?) {
        payloadProgress = progress
        if (progress == null || progress.percent == 100) {
            progressDispatch?.let { main.removeCallbacks(it) }
            progressDispatch = null
            main.post { listeners.values.toList().forEach { it.state(serverRunning) } }
        } else if (progressDispatch == null) {
            val task = Runnable {
                synchronized(this) { progressDispatch = null }
                listeners.values.toList().forEach { it.state(serverRunning) }
            }
            progressDispatch = task
            main.postDelayed(task, 150L)
        }
    }

    /** Local editing tools may become ready while the game server stays stopped. */
    fun toolsStateChanged() {
        main.post { listeners.values.toList().forEach { it.toolsState() } }
    }
}
