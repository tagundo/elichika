package com.tagundo.elichika

import org.json.JSONObject

/** Public methods are called by the embedded Python bridge; release minification is disabled. */
class ArchiveDownloadCallbacks(private val update: (String) -> Unit, private val cancelled: () -> Boolean) {
    @Suppress("unused") fun onProgress(packet: String) = update(packet)
    @Suppress("unused") fun isCancelled(): Boolean = cancelled()
}

internal data class ArchiveDownloadProgress(val percent: Int, val completedFiles: Int, val totalFiles: Int,
                                            val completedBytes: Long, val totalBytes: Long, val current: String,
                                            val cancelling: Boolean = false) {
    companion object {
        fun preparing() = ArchiveDownloadProgress(0, 0, 0, 0, 0, "")
        fun parse(packet: String): ArchiveDownloadProgress {
            val value = JSONObject(packet)
            return ArchiveDownloadProgress(value.optInt("percent").coerceIn(0, 100),
                value.optInt("completed_files").coerceAtLeast(0), value.optInt("total_files").coerceAtLeast(0),
                value.optLong("completed_bytes").coerceAtLeast(0), value.optLong("total_bytes").coerceAtLeast(0),
                value.optString("current").take(128))
        }
    }
}
