package com.tagundo.elichika

import android.content.Context

/** Persist the timer separately from the Activity so resizing never resets it. */
object ServerSettings {
    const val PREFS = "elichika"
    const val AUTO_STOP_MINUTES = "auto_stop_minutes"
    const val MAX_AUTO_STOP_MINUTES = 10080

    fun autoStopMinutes(ctx: Context): Int =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getInt(AUTO_STOP_MINUTES, 0).coerceIn(0, MAX_AUTO_STOP_MINUTES)

    fun setAutoStopMinutes(ctx: Context, minutes: Int) {
        require(minutes in 0..MAX_AUTO_STOP_MINUTES)
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putInt(AUTO_STOP_MINUTES, minutes).apply()
    }
}
