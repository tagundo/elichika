package com.tagundo.elichika

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/** Small config transactions; never holds the large payload-install lock. */
object ServerConfig {
    private val lock = Any()
    private const val PREFS = "elichika"
    private const val GAME_DATA_LOCALES = "gamedata_locales"
    private const val ALL_LOCALES = "ja,en,zh,ko"
    private val localeChoices = setOf(ALL_LOCALES, "ja", "en", "ko", "zh")

    fun read(root: File): JSONObject = synchronized(lock) {
        val file = File(root, "config.json")
        if (file.exists()) JSONObject(file.readText()) else JSONObject()
    }

    /** Merge against the latest file and publish a complete JSON document. */
    fun update(root: File, create: Boolean = true, edit: (JSONObject) -> Unit): Boolean = synchronized(lock) {
        val file = File(root, "config.json")
        if (!create && !file.exists()) return@synchronized false
        val before = if (file.exists()) file.readText() else null
        val config = if (before == null) JSONObject() else JSONObject(before)
        edit(config)
        val after = config.toString()
        if (after == before) return@synchronized false
        root.mkdirs()
        val temporary = File.createTempFile("config-", ".tmp", root)
        try {
            FileOutputStream(temporary).use { output ->
                output.write(after.toByteArray(Charsets.UTF_8))
                output.fd.sync()
            }
            Files.move(temporary.toPath(), file.toPath(),
                StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        } finally {
            temporary.delete()
        }
        true
    }

    fun gameDataLocales(ctx: Context, root: File = ctx.filesDir): String = synchronized(lock) {
        val saved = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(GAME_DATA_LOCALES, null)
        saved ?: read(root).optString("locales", ALL_LOCALES)
    }

    fun setGameDataLocales(ctx: Context, value: String, root: File = ctx.filesDir) = synchronized(lock) {
        require(value in localeChoices)
        // Save even before first preparation creates config.json. Concurrent
        // settings windows and setup share the same short transaction lock.
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(GAME_DATA_LOCALES, value).apply()
        update(root, create = false) { it.put("locales", value) }
    }

    fun applyGameDataLocales(ctx: Context, root: File) = synchronized(lock) {
        val saved = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(GAME_DATA_LOCALES, null)
        if (saved != null) update(root) { it.put("locales", saved) }
    }
}
