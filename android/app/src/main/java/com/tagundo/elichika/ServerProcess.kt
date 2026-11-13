package com.tagundo.elichika

import android.content.Context
import java.io.BufferedReader
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Launches the bundled elichika Go binary. It ships as jniLibs/arm64-v8a/
 * libelichika.so, so the installer places it in nativeLibraryDir with the
 * execute bit — the standard way to run a packaged native executable on API 29+.
 *
 * All invocations run with cwd = the app files dir (the server is cwd-relative:
 * config.json, "server init jsons/", webui/, *.pem, *.db all resolve there).
 */
class ServerProcess(private val ctx: Context) {

    @Volatile private var proc: Process? = null
    internal class Launch(val process: Process, val token: String, localWebuiToken: String) {
        @Volatile private var localAccess: String? = localWebuiToken
        internal fun localWebuiToken(): String? = localAccess
        internal fun clearLocalWebuiToken() { localAccess = null }
    }
    @Volatile private var launch: Launch? = null
    @Volatile private var startFailure: String? = null
    internal fun startupError(): String? = startFailure
    internal fun currentLaunch(): Launch? = launch?.takeIf { proc === it.process && it.process.isAlive }
    internal fun owns(candidate: Launch): Boolean = proc === candidate.process && launch === candidate && candidate.process.isAlive
    internal fun localWebuiToken(): String? = currentLaunch()?.let { if (owns(it)) it.localWebuiToken() else null }

    private fun binary(): File = File(ctx.applicationInfo.nativeLibraryDir, "libelichika.so")

    fun isAlive(): Boolean = proc?.isAlive == true

    /**
     * Start the long-running server. [onExit] fires when the process ends.
     * Returns false if the binary is missing or already running.
     */
    fun startServer(workDir: File, onExit: (Int) -> Unit): Boolean {
        if (isAlive()) return false
        return start(emptyList(), workDir) { code -> onExit(code) }
    }

    /** Run a one-shot CLI verb (rebuild_assets, download_packs N, …) to completion. */
    fun runOnce(args: List<String>, workDir: File, onExit: (Int) -> Unit): Boolean =
        start(args, workDir, onExit)

    /** Private WebUI-only child; its readiness nonce never crosses the log bus. */
    internal fun startManagement(workDir: File, stillWanted: () -> Boolean,
                                 onLine: (String) -> Boolean, onExit: (Int) -> Unit): Boolean {
        // Chaquopy startup can be slow. Keep it outside the process lock so a
        // main-thread service reservation can cancel this pending launch fast.
        try {
            PayloadUpgrade.checkCostumeStartup(ctx, workDir)
        } catch (error: IllegalStateException) {
            startFailure = error.message
            Bus.log(error.message.orEmpty())
            return false
        }
        return startInternal(listOf("management"), workDir, onExit, onLine, stillWanted, checkStartup = false)
    }

    private fun start(args: List<String>, workDir: File, onExit: (Int) -> Unit): Boolean =
        startInternal(args, workDir, onExit)

    @Synchronized
    private fun startInternal(args: List<String>, workDir: File, onExit: (Int) -> Unit,
                      onLine: (String) -> Boolean = { false }, stillWanted: () -> Boolean = { true },
                      checkStartup: Boolean = true): Boolean {
        if (isAlive()) return false
        startFailure = null
        try {
            if (checkStartup) PayloadUpgrade.checkCostumeStartup(ctx, workDir)
        } catch (error: IllegalStateException) {
            startFailure = error.message
            Bus.log(error.message.orEmpty())
            return false
        }
        val bin = binary()
        if (!bin.exists()) {
            startFailure = ctx.getString(R.string.log_error_missing_binary, bin.absolutePath)
            Bus.log(ctx.getString(R.string.log_error_missing_binary, bin.absolutePath))
            return false
        }
        val cmd = mutableListOf(bin.absolutePath).apply { addAll(args) }
        val pb = ProcessBuilder(cmd)
            .directory(workDir)
            .redirectErrorStream(true)
        pb.environment()["HOME"] = workDir.absolutePath
        // Never reuse a token across process launches. A listener left on the
        // configured port cannot make a new process look ready.
        val readyToken = if (args.isEmpty() || args == listOf("management")) java.util.UUID.randomUUID().toString().replace("-", "") else null
        // This independent 128-bit capability authorizes only the app-owned local
        // WebUI. The readiness nonce is public through its HTTP proof and must
        // never authorize management access.
        val localWebuiToken = if (readyToken != null) newLocalWebuiToken() else null
        if (localWebuiToken != null) pb.environment()["ELICHIKA_LOCAL_WEBUI_TOKEN"] = localWebuiToken
        else pb.environment().remove("ELICHIKA_LOCAL_WEBUI_TOKEN")
        if (readyToken != null) pb.environment()["ELICHIKA_READY_TOKEN"] = readyToken
        else pb.environment().remove("ELICHIKA_READY_TOKEN")
        if (args == listOf("management")) {
            pb.environment()["ELICHIKA_MANAGEMENT_PARENT_PID"] = android.os.Process.myPid().toString()
        } else pb.environment().remove("ELICHIKA_MANAGEMENT_PARENT_PID")
        // Do NOT force GODEBUG=netdns=go here: Android has no /etc/resolv.conf, so the
        // pure-Go resolver fails ("lookup ... on [::1]:53: connection refused") and every
        // download dies. The cgo/NDK build defaults to bionic's resolver, which works.

        if (!stillWanted()) return false
        val p = try {
            pb.start()
        } catch (e: Exception) {
            val message = e.message.orEmpty().let { if (localWebuiToken == null) it else it.replace(localWebuiToken, "[redacted]") }
            startFailure = message
            Bus.log(ctx.getString(R.string.log_error_exec_failed, message))
            return false
        }
        proc = p
        launch = readyToken?.let { Launch(p, it, checkNotNull(localWebuiToken)) }
        Thread {
            try {
                p.inputStream.bufferedReader().forEachLineSafe { line ->
                    if (!onLine(line)) {
                        val visible = if (args == listOf("management") && line.contains("AdminPassword :")) {
                            line.substringBefore("AdminPassword :") + "AdminPassword : [redacted]"
                        } else line
                        Bus.log(if (localWebuiToken == null) visible else visible.replace(localWebuiToken, "[redacted]"))
                    }
                }
            } catch (_: Exception) {
            }
            val code = try { p.waitFor() } catch (_: InterruptedException) { -1 }
            synchronized(this) { if (proc === p) { launch?.clearLocalWebuiToken(); proc = null; launch = null } }
            onExit(code)
        }.start()
        return true
    }

    @Synchronized
    fun stop(): Process? {
        val p = proc ?: return null
        launch?.clearLocalWebuiToken()
        p.destroy()
        return p
    }

    companion object {
        private val localWebuiRandom = java.security.SecureRandom()
        private fun newLocalWebuiToken(): String {
            val bytes = ByteArray(16).also(localWebuiRandom::nextBytes)
            val digits = "0123456789abcdef"
            return buildString(32) { for (byte in bytes) {
                val value = byte.toInt() and 255
                append(digits[value ushr 4]); append(digits[value and 15])
            } }
        }
        /** Call on a worker thread before writing DBs or starting a replacement. */
        fun awaitStopped(process: Process?): Boolean {
            if (process == null) return true
            if (process.waitFor(10, TimeUnit.SECONDS)) return true
            process.destroyForcibly()
            return process.waitFor(5, TimeUnit.SECONDS)
        }
    }

    private inline fun BufferedReader.forEachLineSafe(action: (String) -> Unit) {
        var line: String?
        while (true) {
            line = try { readLine() } catch (_: Exception) { null }
            if (line == null) break
            action(line)
        }
    }
}

/** Header policy shared by native document loads and host-only security checks. */
internal object LocalWebuiBootstrap {
    const val HEADER = "X-Elichika-Local-Access"
    private val tokenPattern = Regex("[0-9a-f]{32}")

    fun acceptedToken(url: String, token: String?): String? {
        if (token == null || !tokenPattern.matches(token)) return null
        val uri = runCatching { java.net.URI(url) }.getOrNull() ?: return null
        if (uri.scheme !in listOf("http", "https") || uri.rawUserInfo != null ||
            uri.port !in 1..65535 || !(uri.path == "/webui" || uri.path.orEmpty().startsWith("/webui/"))) return null
        val host = uri.host?.removePrefix("[")?.removeSuffix("]")?.lowercase() ?: return null
        val loopback = host == "localhost" || host == "::1" || host.split('.').let { pieces ->
            pieces.size == 4 && pieces[0] == "127" && pieces.all { part ->
                part.isNotEmpty() && part.all { it in '0'..'9' } && part.toIntOrNull() in 0..255
            }
        }
        return if (loopback) token else null
    }

    fun requiresReload(currentUrl: String?, destination: String, previousToken: String?, token: String?): Boolean {
        val current = currentUrl?.let { runCatching { java.net.URI(it) }.getOrNull() }
        val target = runCatching { java.net.URI(destination) }.getOrNull()
        return current == null || target == null || current.scheme != target.scheme ||
            current.rawAuthority != target.rawAuthority || previousToken != acceptedToken(destination, token)
    }

    fun headers(url: String, token: String?): Map<String, String> =
        acceptedToken(url, token)?.let { mapOf(HEADER to it) } ?: emptyMap()
}
