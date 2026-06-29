package com.tagundo.elichika

import android.content.Context
import java.io.BufferedReader
import java.io.File

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

    private fun start(args: List<String>, workDir: File, onExit: (Int) -> Unit): Boolean {
        val bin = binary()
        if (!bin.exists()) {
            Bus.log("[error] libelichika.so 가 없습니다: ${bin.absolutePath}")
            return false
        }
        val cmd = mutableListOf(bin.absolutePath).apply { addAll(args) }
        val pb = ProcessBuilder(cmd)
            .directory(workDir)
            .redirectErrorStream(true)
        pb.environment()["HOME"] = workDir.absolutePath
        // Pure-Go fallback resolver hint; harmless under the cgo/bionic build.
        pb.environment()["GODEBUG"] = "netdns=go+1"

        val p = try {
            pb.start()
        } catch (e: Exception) {
            Bus.log("[error] 실행 실패: ${e.message}")
            return false
        }
        proc = p
        Thread {
            try {
                p.inputStream.bufferedReader().forEachLineSafe { Bus.log(it) }
            } catch (_: Exception) {
            }
            val code = try { p.waitFor() } catch (_: InterruptedException) { -1 }
            if (proc === p) proc = null
            onExit(code)
        }.start()
        return true
    }

    fun stop() {
        proc?.let {
            it.destroy()
            proc = null
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
