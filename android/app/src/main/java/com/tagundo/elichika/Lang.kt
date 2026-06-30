package com.tagundo.elichika

import android.content.Context
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import java.io.File
import java.util.Locale

/**
 * Single source of truth for the UI language across the whole app: the native UI,
 * the server WebUI (config.json webui_language) and the Python tools (SIFAS_LANG).
 *
 * Default is "auto" — follow the system locale, falling back to English for any
 * locale we don't ship (en/ko/ja). The user can override it in Settings.
 */
object Lang {
    private const val PREFS = "elichika"
    private const val KEY = "lang"
    val SUPPORTED = listOf("en", "ko", "ja")

    /** "auto" | "en" | "ko" | "ja" */
    fun pref(ctx: Context): String =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, "auto") ?: "auto"

    fun setPref(ctx: Context, value: String) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, value).apply()
    }

    /** Resolve the concrete language code, mapping "auto" to the system locale. */
    fun effective(ctx: Context): String {
        val p = pref(ctx)
        if (p in SUPPORTED) return p
        val sys = Locale.getDefault().language
        return if (sys in SUPPORTED) sys else "en"
    }

    /** Apply the preference to the native UI (auto = follow system). */
    fun applyToApp(ctx: Context) {
        val p = pref(ctx)
        val target =
            if (p in SUPPORTED) LocaleListCompat.forLanguageTags(p)
            else LocaleListCompat.getEmptyLocaleList()
        if (AppCompatDelegate.getApplicationLocales() != target) {
            AppCompatDelegate.setApplicationLocales(target)
        }
    }

    /** Point config.json's webui_language at the effective language. */
    fun writeWebuiLanguage(ctx: Context, configRoot: File) {
        val cfg = File(configRoot, "config.json")
        if (!cfg.exists()) return
        try {
            val txt = cfg.readText()
            val patched = Regex("\"webui_language\"\\s*:\\s*\"[a-z]{2}\"")
                .replace(txt, "\"webui_language\":\"${effective(ctx)}\"")
            if (patched != txt) cfg.writeText(patched)
        } catch (_: Exception) {
        }
    }
}
