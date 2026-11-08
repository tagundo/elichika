package com.tagundo.elichika

import android.content.Context
import org.json.JSONObject

/** Display-only progress: raw callbacks can never acknowledge a committed update. */
internal object PayloadProgress {
    val stages = listOf("recovering", "validating", "snapshot", "merging", "verifying", "publishing", "complete")
    private val basename = Regex("[A-Za-z0-9_.-]{1,96}")

    data class State(val stage: String, val completed: Long, val total: Long,
                     val current: String, val percent: Int)

    fun parse(json: String): State? = runCatching {
        if (json.length > 2048) return null
        val item = JSONObject(json)
        val stage = item.getString("stage")
        if (stage !in stages) return null
        fun integer(name: String): Long? {
            val raw = item.get(name)
            if (raw !is Int && raw !is Long) return null
            return (raw as Number).toLong().takeIf { it in 0..Long.MAX_VALUE }
        }
        val completed = integer("completed") ?: return null
        val total = integer("total") ?: return null
        val percent = integer("percent")?.takeIf { it <= 100 }?.toInt() ?: return null
        if (total < 1 || completed > total) return null
        val range = when (stage) {
            "recovering" -> 0..99
            "validating" -> 2..15
            "snapshot" -> 15..35
            "merging" -> 35..85
            "verifying" -> 85..95
            "publishing" -> 95..99
            else -> 100..100
        }
        if (percent !in range) return null
        val current = item.getString("current")
        if (current.isNotEmpty() && (!basename.matches(current) || current == "." || current == "..")) return null
        State(stage, completed, total, current, percent)
    }.getOrNull()

    /** One invocation owns one session; late or backwards observer calls are ignored. */
    class Session(private val observer: (State) -> Unit) {
        private var closed = false
        private var latest: State? = null

        @Synchronized fun accept(json: String) {
            if (closed) return
            val raw = parse(json) ?: return
            // The common reporter may emit completion before returning. Kotlin
            // independently verifies COMMITTED and installed_version first.
            val next = if (raw.stage == "complete") raw.copy(stage = "publishing", percent = 99)
                else raw.copy(percent = raw.percent.coerceAtMost(99))
            val before = latest
            if (before != null && (next.percent < before.percent ||
                (stages.indexOf(next.stage) < stages.indexOf(before.stage) && next.stage != "recovering"))) return
            if (next == before) return
            latest = next
            runCatching { observer(next) }
        }

        @Synchronized fun committed() {
            if (closed) return
            closed = true
            val complete = State("complete", 1, 1, "", 100)
            latest = complete
            runCatching { observer(complete) }
        }

        @Synchronized fun close() { closed = true }
    }

    fun stageLabel(context: Context, stage: String): String = context.getString(when (stage) {
        "recovering" -> R.string.progress_recovering
        "validating" -> R.string.progress_validating
        "snapshot" -> R.string.progress_snapshot
        "merging" -> R.string.progress_merging
        "verifying" -> R.string.progress_verifying
        "publishing" -> R.string.progress_publishing
        else -> R.string.progress_complete
    })
}

/** Public method is called reflectively by Chaquopy; release rules retain this class. */
class PayloadProgressObserver internal constructor(private val session: PayloadProgress.Session) {
    fun onProgress(json: String) { runCatching { session.accept(json) } }
}
