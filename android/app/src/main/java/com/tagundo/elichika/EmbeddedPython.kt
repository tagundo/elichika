package com.tagundo.elichika

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

/** Starts the interpreter without importing editors or opening tool servers. */
internal object EmbeddedPython {
    @Synchronized
    fun instance(context: Context): Python {
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context.applicationContext))
        }
        val python = Python.getInstance()
        // Android extracts ABI-filtered native libraries to this trusted app
        // directory. Supply the HCA decoder before any editor or native check
        // imports it, including callers which do not start PyServers.
        val nativeDir = context.applicationInfo.nativeLibraryDir
        val environment = python.getModule("os").get("environ")!!
        environment.callAttr("__setitem__", "ELICHIKA_NATIVE_DIR", nativeDir)
        environment.callAttr("__setitem__", "ELICHIKA_HCA_LIBRARY", File(nativeDir, "libelichika_hca.so").absolutePath)
        environment.callAttr("__setitem__", "ELICHIKA_TEXTURE65_BIN", File(nativeDir, "libelichika_texture65.so").absolutePath)
        return python
    }
}
