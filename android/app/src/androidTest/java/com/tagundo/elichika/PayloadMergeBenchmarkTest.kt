package com.tagundo.elichika

import android.app.Activity
import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.Comparator
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.TimeUnit

/** Explicit public-data measurements on disposable native Redroid, outside core smoke tests. */
@RunWith(AndroidJUnit4::class)
class PayloadMergeBenchmarkTest {
    @Test
    fun comparePrivatePublicDatabaseMergesWithoutBlockingTheMainLooper() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        assumeTrue("Requires payloadMergeBenchmark=true",
            InstrumentationRegistry.getArguments().getString("payloadMergeBenchmark") == "true")
        assertEquals("redroid", Build.HARDWARE)
        assertEquals("arm64-v8a", Build.SUPPORTED_ABIS.firstOrNull())
        assertTrue(Build.VERSION.SDK_INT >= 29)
        assertFalse("Benchmark must not run on the UI thread", Looper.myLooper() == Looper.getMainLooper())
        assertFalse("Benchmark requires a stopped server", Bus.serverRunning)
        assertFalse("Benchmark requires no pending server launch", Bus.serverStarting)
        val context = instrumentation.targetContext.applicationContext
        val cache = context.cacheDir.canonicalFile
        val fixture = File(cache, "payload-merge-benchmark-${UUID.randomUUID()}")
        check(fixture.mkdir())
        val report = File(cache, "payload-merge-benchmark-${UUID.randomUUID()}.json")
        val apk = File(context.applicationInfo.sourceDir).canonicalFile
        val apkSha = sha256(apk)
        val apkBytes = apk.length()
        val nativeSha = sha256(File(context.applicationInfo.nativeLibraryDir, "libelichika.so"))
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        val script = instrumentation.context.assets.open("android_payload_merge_benchmark.py")
            .bufferedReader().use { it.readText() }
        val memory = ActivityManager.MemoryInfo()
        (context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager).getMemoryInfo(memory)
        val availableMemory = memory.availMem
        val executor = Executors.newSingleThreadExecutor()
        var future: Future<String>? = null
        var activity: Activity? = null
        var heartbeats = 0
        try {
            activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            instrumentation.waitForIdleSync()
            val operation = executor.submit<String> {
                val python = EmbeddedPython.instance(context)
                val module = python.getModule("types").callAttr("ModuleType", "_payload_merge_benchmark_qa")
                python.getModule("builtins").callAttr("exec", script, module.get("__dict__"))
                module.callAttr("run_benchmark", cache.absolutePath, fixture.absolutePath,
                    report.absolutePath, true, Build.HARDWARE, Build.SUPPORTED_ABIS[0],
                    apk.absolutePath, apkSha, apkBytes, availableMemory).toString()
            }
            future = operation
            val deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(9)
            while (!operation.isDone) {
                assertTrue("Private benchmark exceeded its bounded test budget", System.nanoTime() < deadline)
                val heartbeat = CountDownLatch(1)
                Handler(Looper.getMainLooper()).post { heartbeat.countDown() }
                assertTrue("Database workers blocked the native main looper", heartbeat.await(1, TimeUnit.SECONDS))
                heartbeats++
                Thread.sleep(50)
            }
            val result = JSONObject(operation.get())
            result.put("target_version_name", info.versionName)
            result.put("target_version_code", info.longVersionCode)
            result.put("target_apk_sha256", apkSha)
            result.put("target_native_sha256", nativeSha)
            result.put("main_looper_heartbeats", heartbeats)
            result.put("main_looper_responsive", heartbeats > 0)
            report.writeText(result.toString())
            println("ANDROID_PAYLOAD_MERGE_BENCHMARK_REPORT_FILE=${report.absolutePath}")
            println("ANDROID_PAYLOAD_MERGE_BENCHMARK_SUMMARY=" + JSONObject()
                .put("status", result.getString("status"))
                .put("cases", result.optJSONArray("cases")?.length() ?: 0)
                .put("main_looper_heartbeats", heartbeats)
                .put("workers_4", result.optString("workers_4")))
            assertEquals("PASS", result.getString("status"))
            assertTrue(result.getBoolean("fixture_cleanup_complete"))
            assertTrue(result.getBoolean("android_backend_available"))
            assertTrue(result.getBoolean("all_output_schemas_baselines_counts_exact"))
            assertTrue(result.getBoolean("source_apk_unchanged"))
            assertTrue(result.getBoolean("main_looper_responsive"))
            val cases = result.getJSONArray("cases")
            assertTrue(cases.length() == 4 || cases.length() == 6)
            val counts = mutableMapOf<Int, Int>()
            for (index in 0 until cases.length()) {
                val worker = cases.getJSONObject(index).getInt("workers")
                counts[worker] = (counts[worker] ?: 0) + 1
            }
            assertEquals(2, counts[1])
            assertEquals(2, counts[2])
            if (result.getString("workers_4") == "MEASURED") assertEquals(2, counts[4])
            else assertEquals("RESOURCE_LIMIT_REFUSED", result.getString("workers_4"))
            assertFalse("Private benchmark must not start the game server", Bus.serverRunning)
        } finally {
            // Never remove a workspace while a timed-out CPython worker can
            // still be writing. The disposable Android container owns its
            // eventual teardown; normal results already clean up in Python.
            if (future == null || future.isDone) {
                if (fixture.exists() || Files.isSymbolicLink(fixture.toPath())) {
                    Files.walk(fixture.toPath()).use { paths ->
                        paths.sorted(Comparator.reverseOrder()).forEach { Files.deleteIfExists(it) }
                    }
                }
            }
            executor.shutdown()
            activity?.let { window -> instrumentation.runOnMainSync { window.finish() } }
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { stream ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
