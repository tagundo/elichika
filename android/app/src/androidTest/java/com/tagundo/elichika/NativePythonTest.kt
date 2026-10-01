package com.tagundo.elichika

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
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
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        val python = Python.getInstance()
        val module = python.getModule("types").callAttr("ModuleType", "_native_qa")
        val script = instrumentation.context.assets.open("native_python_checks.py")
            .bufferedReader().use { it.readText() }
        python.getModule("builtins").callAttr("exec", script, module.get("__dict__"))
        val directory = File(context.cacheDir, "native-qa").apply { mkdirs() }
        try {
            val astc = File(context.applicationInfo.nativeLibraryDir, "libastcenc.so")
            val result = module.callAttr("python_checks", astc.absolutePath, directory.absolutePath)
            val encoded = python.getModule("json").callAttr("dumps", result).toString()
            val report = JSONObject(encoded)
            assertTrue(report.getString("python").startsWith("3.13."))
            assertEquals(6, report.getInt("compression_roundtrips"))
            for (key in listOf("ssl_and_certificates", "sqlite_unicode", "ctypes",
                "numpy_linear_algebra", "pillow_png_jpeg_freetype", "unitypy_binary_io",
                "fsspec_memory_io", "adminui_and_webtools_imports", "astc_encode_decode")) {
                assertTrue(key, report.getBoolean(key))
            }
            println("ANDROID_PYTHON_NATIVE_REPORT=$encoded")
        } finally {
            directory.deleteRecursively()
        }
    }
}
