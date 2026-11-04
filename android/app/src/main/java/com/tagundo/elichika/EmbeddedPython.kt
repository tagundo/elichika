package com.tagundo.elichika

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/** Starts the interpreter without importing editors or opening tool servers. */
internal object EmbeddedPython {
    @Synchronized
    fun instance(context: Context): Python {
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context.applicationContext))
        }
        return Python.getInstance()
    }
}
