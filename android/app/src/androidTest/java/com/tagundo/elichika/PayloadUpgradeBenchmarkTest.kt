package com.tagundo.elichika

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import java.util.Comparator
import java.util.UUID

/** Explicit, disposable-Redroid-only updater measurement; excluded from normal smoke tests. */
@RunWith(AndroidJUnit4::class)
class PayloadUpgradeBenchmarkTest {
    @Test
    fun benchmarkFixedPublicPayloadWithoutTouchingLiveData() {
        val arguments = InstrumentationRegistry.getArguments()
        assumeTrue("Requires explicit payloadUpgradeBenchmark=true",
            arguments.getString("payloadUpgradeBenchmark") == "true")
        assertEquals("redroid", Build.HARDWARE)
        assertEquals("arm64-v8a", Build.SUPPORTED_ABIS.firstOrNull())
        assertTrue(Build.VERSION.SDK_INT >= 29)
        val label = arguments.getString("payloadBenchmarkLabel") ?: "baseline"
        require(label in setOf("baseline", "candidate"))
        val staticMiB = (arguments.getString("payloadBenchmarkStaticMiB") ?: "256").toInt()
        require(staticMiB in setOf(0, 256))
        val profile = arguments.getString("payloadBenchmarkProfile") == "true"
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val cache = context.cacheDir.canonicalFile
        val fixture = File(cache, "payload-upgrade-benchmark-${UUID.randomUUID()}")
        check(fixture.mkdir())
        val report = File(cache, "payload-upgrade-benchmark-$label-${UUID.randomUUID()}.json")
        try {
            val python = EmbeddedPython.instance(context)
            val module = python.getModule("types").callAttr("ModuleType", "_payload_benchmark_qa")
            val script = instrumentation.context.assets.open("android_payload_upgrade_benchmark.py")
                .bufferedReader().use { it.readText() }
            python.getModule("builtins").callAttr("exec", script, module.get("__dict__"))
            val encoded = module.callAttr("run_benchmark", cache.absolutePath, fixture.absolutePath,
                report.absolutePath, true, Build.HARDWARE, Build.SUPPORTED_ABIS[0], staticMiB, profile).toString()
            val result = JSONObject(encoded)
            val info = context.packageManager.getPackageInfo(context.packageName, 0)
            result.put("target_version_name", info.versionName)
            result.put("target_version_code", info.longVersionCode)
            result.put("target_apk_sha256", sha256(File(context.applicationInfo.sourceDir)))
            result.put("target_native_sha256", sha256(File(context.applicationInfo.nativeLibraryDir, "libelichika.so")))
            report.writeText(result.toString())
            println("ANDROID_PAYLOAD_BENCHMARK_REPORT=$result")
            println("ANDROID_PAYLOAD_BENCHMARK_REPORT_FILE=${report.absolutePath}")
            assertEquals("PASS", result.getString("status"))
            assertTrue(result.getBoolean("fixture_cleanup_complete"))
            assertEquals(55, result.getInt("databases"))
            assertEquals(2, result.getJSONArray("cases").length())
        } finally {
            // Never follow a symlink into shared storage while removing a fixture.
            if (fixture.exists() || Files.isSymbolicLink(fixture.toPath())) {
                Files.walk(fixture.toPath()).use { paths ->
                    paths.sorted(Comparator.reverseOrder()).forEach { Files.deleteIfExists(it) }
                }
            }
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
