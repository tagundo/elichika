package com.tagundo.elichika

import android.net.Uri
import android.webkit.MimeTypeMap
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView

/** Native document grants for file inputs in the two trusted local tool UIs. */
internal class ToolFileChooser {
    private var callback: ValueCallback<Array<Uri>>? = null
    private var owner: WebView? = null
    private var inFlight = false
    private var multiple = false

    private fun trusted(url: String?): Boolean = runCatching {
        val value = Uri.parse(url ?: return@runCatching false)
        value.scheme == "http" && value.host in setOf("127.0.0.1", "localhost") &&
            value.port in setOf(8772, 8770) && value.userInfo == null
    }.getOrDefault(false)

    fun client(launch: (Array<String>, Boolean) -> Unit): WebChromeClient = object : WebChromeClient() {
        override fun onShowFileChooser(view: WebView, result: ValueCallback<Array<Uri>>,
                                       params: FileChooserParams): Boolean {
            if (!trusted(view.url) || params.mode !in setOf(FileChooserParams.MODE_OPEN, FileChooserParams.MODE_OPEN_MULTIPLE)) return false
            if (inFlight) {
                // Never bind a late result from an older OS picker to a newer
                // WebView callback. Finish that picker before another request.
                cancel()
                runCatching { result.onReceiveValue(null) }
                return true
            }
            callback = result; owner = view; inFlight = true
            multiple = params.mode == FileChooserParams.MODE_OPEN_MULTIPLE
            val types = params.acceptTypes.orEmpty().mapNotNull { raw ->
                val value = raw.trim().lowercase()
                when {
                    Regex("[a-z0-9.+_-]+/[a-z0-9.+_*-]+").matches(value) -> value
                    value.startsWith(".") -> MimeTypeMap.getSingleton().getMimeTypeFromExtension(value.drop(1))
                    else -> null
                }
            }.distinct().toTypedArray().takeIf { it.isNotEmpty() } ?: arrayOf("*/*")
            try { launch(types, multiple) } catch (_: RuntimeException) { inFlight = false; cancel() }
            return true
        }
    }

    fun deliver(chosen: List<Uri>) {
        val result = callback; val view = owner
        callback = null; owner = null; inFlight = false
        if (result == null) return
        val unique = chosen.distinct()
        // URI grants come only from the OS document picker. JavaScript receives
        // File objects, whose bytes are uploaded; fake/local path strings never
        // become installer arguments. The shared form enforces its 128-file cap.
        val accepted = trusted(view?.url) && unique.size <= 1024 &&
            (multiple || unique.size <= 1) && unique.all { it.scheme == "content" }
        runCatching { result.onReceiveValue(if (accepted && unique.isNotEmpty()) unique.toTypedArray() else null) }
    }

    fun cancel() {
        val result = callback
        callback = null; owner = null
        runCatching { result?.onReceiveValue(null) }
    }

    fun cancelFor(view: WebView) {
        if (owner === view) cancel()
    }

    fun awaitingResult(): Boolean = inFlight

    fun restoreAwaitingResult(pending: Boolean) {
        // ActivityResultRegistry retains an outstanding OS picker across
        // recreation. Drain that old result before binding a new WebView input.
        if (pending) { cancel(); inFlight = true }
    }
}
