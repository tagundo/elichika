package com.tagundo.elichika

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** Exercises Python packages through the real Chaquopy Java bridge in the signed APK. */
@RunWith(AndroidJUnit4::class)
class NativePythonTest {
    @Test
    fun nativePackagesAndAstcWork() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val python = EmbeddedPython.instance(context)
        val hca = File(context.applicationInfo.nativeLibraryDir, "libelichika_hca.so")
        assertTrue("The signed APK must include its local HCA decoder", hca.isFile)
        val hcaDecoder = python.getModule("webtools.core.cri_audio_decode").callAttr("_native_library")
        assertEquals("True", python.getModule("builtins").callAttr("bool", hcaDecoder).toString())
        assertEquals(hca.absolutePath,
            python.getModule("os").get("environ")!!.callAttr("get", "ELICHIKA_HCA_LIBRARY").toString())
        val texture65 = File(context.applicationInfo.nativeLibraryDir, "libelichika_texture65.so")
        assertTrue("The signed APK must include its bounded format65 executable", texture65.isFile)
        assertEquals(texture65.absolutePath,
            python.getModule("os").get("environ")!!.callAttr("get", "ELICHIKA_TEXTURE65_BIN").toString())
        val mergeModule = python.getModule("types").callAttr("ModuleType", "android_payload_merge_benchmark")
        val mergeScript = instrumentation.context.assets.open("android_payload_merge_benchmark.py")
            .bufferedReader().use { it.readText() }
        python.getModule("builtins").callAttr("exec", mergeScript, mergeModule.get("__dict__"))
        python.getModule("sys").get("modules")!!.callAttr("__setitem__", "android_payload_merge_benchmark", mergeModule)
        val module = python.getModule("types").callAttr("ModuleType", "_native_qa")
        val script = instrumentation.context.assets.open("native_python_checks.py")
            .bufferedReader().use { it.readText() }
        python.getModule("builtins").callAttr("exec", script, module.get("__dict__"))
        val directory = File(context.cacheDir, "native-qa").apply { mkdirs() }
        try {
            // The mandatory updater is importable before any editor server and
            // can inspect a fresh private fixture without requiring live DBs.
            val maintenance = python.getModule("database_maintenance")
            val lease = JSONObject(maintenance.callAttr("begin_maintenance_json", directory.absolutePath).toString())
            assertEquals("ACQUIRED", lease.getString("status"))
            try {
                // Java -> Python calls may recreate CPython thread state. The
                // nested guard must still recognize this native-thread owner.
                val nested = maintenance.callAttr("guard", directory.absolutePath)
                nested.callAttr("__enter__")
                nested.callAttr("__exit__", null, null, null)
                val recovered = JSONObject(python.getModule("payload_db_upgrade")
                    .callAttr("recover_upgrade_json", directory.absolutePath).toString())
                assertEquals("CLEAN", recovered.getString("status"))
            } finally {
                val released = JSONObject(maintenance.callAttr("end_maintenance_json",
                    directory.absolutePath, lease.getString("token")).toString())
                assertEquals("RELEASED", released.getString("status"))
            }
            val astc = File(context.applicationInfo.nativeLibraryDir, "libastcenc.so")
            val result = module.callAttr("python_checks", astc.absolutePath, directory.absolutePath)
            val encoded = python.getModule("json").callAttr("dumps", result).toString()
            val report = JSONObject(encoded)
            assertTrue(report.getString("python").startsWith("3.13."))
            assertEquals(6, report.getInt("compression_roundtrips"))
            val decoded65 = report.getJSONObject("texture65_decode")
            assertEquals("PASS", decoded65.getString("status"))
            assertEquals(65, decoded65.getInt("unity_format"))
            assertEquals(texture65.canonicalPath, File(decoded65.getString("executable")).canonicalPath)
            assertEquals("d22610a543c19f361d896ce8225e800a0507154867760615673265b2cfb1b577",
                decoded65.getString("fixture_sha256"))
            assertEquals("76a9cba0c36c189f976ac41793d14055407929beb4f142d17a2f8867dd6e479e",
                decoded65.getString("rgba_sha256"))
            assertEquals("57b0febf48dfd82df66c88426f7677107ad0d48cf588233f044b59d6d817ebf9",
                decoded65.getString("display_rgba_sha256"))
            assertTrue(decoded65.getBoolean("production_single_flip"))
            assertTrue(decoded65.getBoolean("transparent_rgb_retained"))
            assertTrue(decoded65.getBoolean("invalid_dimensions_refused"))
            val authoredMips = decoded65.getJSONObject("authored_mips")
            assertEquals("0ef12426c6703f658a12c7fc04f1fdbae73ca5d44164d965080be42a34db2552",
                authoredMips.getString("fixture_sha256"))
            val expectedMips = arrayOf(
                "67d75a329b0a72e9544ddc71e0e83f6a4cc74582a694209b1a9981d8d7bf70cf" to "86057308524be9a5e43a22adcb7ac4380572c5cb95a6ab22e00b6ecaa78af44c",
                "4408294f1905631d095f012c88d90abb0504046e7e3274026d6e324e5ffd9496" to "8405f5e5f26e562990376fb5fe60e46aadd9878294633309813d27d73ebeaebf",
                "7c176380ab026186839a000dc6a9ff5975a67378bdcd5deb613619ef0b1e80c4" to "524eba9b0228fd65ce9143e7e237ac28b29417fa9a6c74cd32b2a4da636baea6",
                "7108bd2cae8b5c04b49f297e74ad12bbd298512018ba945cdd1bab9ecf220d7a" to "45dd93b604b1017fe8849a75df63a5354c734c3a2f10947226f9ded5ae5188f9",
                "2c1d418829ea5941ce3ceca05e9adeba65e1ad1ad52e67972955f726d550fc31" to "2c1d418829ea5941ce3ceca05e9adeba65e1ad1ad52e67972955f726d550fc31")
            val levels = authoredMips.getJSONArray("levels")
            assertEquals(5, levels.length())
            expectedMips.forEachIndexed { level, golden ->
                val actual = levels.getJSONObject(level)
                val dimension = 16 shr level
                assertEquals(level, actual.getInt("level"))
                assertEquals(dimension, actual.getInt("width"))
                assertEquals(dimension, actual.getInt("height"))
                assertEquals(dimension * dimension * 4, actual.getInt("rgba_bytes"))
                assertEquals(golden.first, actual.getString("rgba_sha256"))
                assertEquals(golden.second, actual.getString("display_rgba_sha256"))
                assertTrue(actual.getBoolean("production_single_flip"))
            }
            assertTrue(authoredMips.getBoolean("invalid_level_refused"))
            assertTrue(authoredMips.getBoolean("invalid_python_level_refused"))
            assertEquals(PayloadFileHasher.sha256File(texture65.absolutePath),
                decoded65.getString("executable_sha256"))
            decoded65.put("apk_sha256", PayloadFileHasher.sha256File(context.applicationInfo.sourceDir))
            decoded65.put("application_id", context.packageName)
            decoded65.put("native_java_bridge", true)
            File(context.filesDir, "native-texture65-report.json").writeText(decoded65.toString(2))
            println("ANDROID_TEXTURE65_NATIVE_REPORT=$decoded65")
            val cdnModule = python.getModule("types").callAttr("ModuleType", "_native_cdn_qa")
            val cdnScript = instrumentation.context.assets.open("native_cdn_checks.py")
                .bufferedReader().use { it.readText() }
            python.getModule("builtins").callAttr("exec", cdnScript, cdnModule.get("__dict__"))
            val cdnPayload = context.assets.open("payload/assets/costume-cdn-index.json.gz").use { it.readBytes() }
            val cdnSha = java.security.MessageDigest.getInstance("SHA-256").digest(cdnPayload)
                .joinToString("") { "%02x".format(it.toInt() and 0xff) }
            val cdnResult = cdnModule.callAttr("check", context.filesDir.canonicalPath, cdnSha)
            val cdnReport = JSONObject(python.getModule("json").callAttr("dumps", cdnResult).toString())
            assertEquals("PASS_BUNDLED_CATALOG_READ_ONLY_PLAN", cdnReport.getString("status"))
            assertTrue(cdnReport.getBoolean("source_preserved"))
            assertEquals(0, cdnReport.getInt("network_requests"))
            cdnReport.put("apk_sha256", PayloadFileHasher.sha256File(context.applicationInfo.sourceDir))
            cdnReport.put("native_java_bridge", true)
            File(context.filesDir, "native-cdn-catalog-report.json").writeText(cdnReport.toString(2))
            println("ANDROID_CDN_CATALOG_NATIVE_REPORT=$cdnReport")
            for (key in listOf("ssl_and_certificates", "sqlite_unicode", "ctypes",
                "numpy_linear_algebra", "pillow_png_jpeg_freetype", "unitypy_binary_io",
                "fsspec_memory_io", "adminui_and_webtools_imports", "astc_encode_decode", "bundled_suit_preview",
                "clone_bundle_isolation")) {
                assertTrue(key, report.getBoolean(key))
            }
            println("ANDROID_PYTHON_NATIVE_REPORT=$encoded")
        } finally {
            directory.deleteRecursively()
        }
    }
}
