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
            for (key in listOf("ssl_and_certificates", "sqlite_unicode", "ctypes",
                "numpy_linear_algebra", "pillow_png_jpeg_freetype", "unitypy_binary_io",
                "fsspec_memory_io", "adminui_and_webtools_imports", "astc_encode_decode", "bundled_suit_preview")) {
                assertTrue(key, report.getBoolean(key))
            }
            println("ANDROID_PYTHON_NATIVE_REPORT=$encoded")
        } finally {
            directory.deleteRecursively()
        }
    }
}
