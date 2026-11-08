package com.tagundo.elichika

import android.content.Context
import android.os.Environment
import java.io.File

/**
 * Stages the APK payload and delegates publishing to the recoverable updater.
 * Normal updates merge game definitions while preserving mods. First install
 * and explicit Reset Server restore vanilla definitions. User state is never
 * replaced by the bundled payload; the explicit account reset remains separate.
 */
object AssetInstaller {

    private const val PAYLOAD = "payload"

    enum class PreparationPhase { IDLE, PREPARING, UPDATING_GAME_DATA, FAILED }

    /** Returns the server working dir (== app files dir). */
    @Synchronized
    fun install(ctx: Context, log: (String) -> Unit): File =
        prepare(ctx, log, {}, reset = false)

    /** Phase reporting is separate from console text and never marks Go as running. */
    @Synchronized
    fun install(ctx: Context, onPhase: (PreparationPhase) -> Unit, log: (String) -> Unit): File =
        prepare(ctx, log, onPhase, reset = false)

    /** Vanilla file restoration; ServerService performs the separate account reset. */
    @Synchronized
    fun resetServerData(ctx: Context, log: (String) -> Unit): File =
        prepare(ctx, log, {}, reset = true)

    @Synchronized
    fun resetServerData(ctx: Context, onPhase: (PreparationPhase) -> Unit, log: (String) -> Unit): File =
        prepare(ctx, log, onPhase, reset = true)

    private fun prepare(ctx: Context, log: (String) -> Unit,
                        onPhase: (PreparationPhase) -> Unit, reset: Boolean): File {
        val source = object : PayloadFiles.Source {
            override fun list(path: String): Array<String> = ctx.assets.list(path) ?: emptyArray()
            override fun open(path: String) = ctx.assets.open(path)
        }
        return PayloadPreparation.prepare(ctx, ctx.filesDir, source, appVersion(ctx), reset, onPhase, log, Bus::setPayloadProgress) {
            // Settings still run on data-revision no-ops and preserve explicit choices.
            ensureBundledConfig(ctx, ctx.filesDir)
            ensureSharedLinks(ctx, ctx.filesDir, log)
            ensureCacheDir(ctx, ctx.filesDir, log)
            ensureCdnDefaultOn(ctx, ctx.filesDir, log)
            ensureLanguage(ctx, ctx.filesDir, log)
        }
    }

    // Termux default that the server injects into config.json on Android.
    private const val SUKUSTA_DEFAULT = "~/storage/downloads/sukusta/packs"

    /**
     * Keep the server WebUI language in sync with the app's language preference
     * (Settings → Language; default = follow system). The app pref is the single
     * source of truth, so this runs every server start.
     */
    private fun ensureLanguage(ctx: Context, root: File, log: (String) -> Unit) {
        ServerConfig.applyGameDataLocales(ctx, root)
        Lang.writeWebuiLanguage(ctx, root)
    }

    /**
     * Make the Termux-style "~/storage/downloads" path resolve to the real shared
     * Download/ folder, so the addon installers (and any tool using that path) read
     * and write where the user can see them. The server/Python run with HOME = the
     * files dir, so a symlink files/storage/downloads -> /sdcard/Download does it.
     * Also pre-creates the unified addon drop folder.
     */
    private fun ensureSharedLinks(ctx: Context, root: File, log: (String) -> Unit) {
        try {
            val download = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            runCatching { File(download, "sukusta/addons").mkdirs() }
            val storageDir = File(root, "storage").apply { mkdirs() }
            val link = File(storageDir, "downloads")
            if (!link.exists()) {
                android.system.Os.symlink(download.absolutePath, link.absolutePath)
                log(ctx.getString(R.string.log_setup_downloads_link, download.absolutePath))
            }
        } catch (e: Exception) {
            log(ctx.getString(R.string.log_setup_link_failed, e.message ?: ""))
        }
    }

    /**
     * Point cdn_cache_dir at the shared Download/sukusta/packs folder — the same
     * place the Termux install uses, so packs land where the user (and the modding
     * tools) expect them. Writing there needs All-files access on Android 11+
     * (requested in MainActivity). Only an empty value, the Termux default, or the
     * earlier app-private path is replaced — a dir the user chose in the WebUI is
     * left alone. A non-empty absolute path also stops the server re-injecting the
     * sukusta default on Load().
     */
    private fun ensureCacheDir(ctx: Context, root: File, log: (String) -> Unit) {
        val shared = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            "sukusta/packs"
        )
        runCatching { shared.mkdirs() } // succeeds once storage access is granted
        val path = shared.absolutePath
        // the path the previous build wrote, so we can migrate it forward
        val oldAppPath = File(ctx.getExternalFilesDir(null), "packs").absolutePath
        var created = false
        var changed = false
        ServerConfig.update(root) { config ->
            created = !File(root, "config.json").exists()
            if (created) config.put("cdn_cache", true)
            val current = config.optString("cdn_cache_dir", "")
            if (current.isEmpty() || current == SUKUSTA_DEFAULT || current == oldAppPath) {
                config.put("cdn_cache_dir", path)
                changed = current != path
            }
        }
        if (created) {
            log(ctx.getString(R.string.log_setup_config_created, path))
        } else if (changed) {
            log(ctx.getString(R.string.log_setup_cdn_dir, path))
        }
    }

    /**
     * One-time default fix: earlier builds bundled a config.json generated with the
     * server-wide defaults, which carried cdn_cache=false and silently overrode the
     * app's intended ON default. Flip it to true once per install; the marker makes
     * sure a user who later turns it OFF with the console toggle stays OFF.
     */
    private fun ensureCdnDefaultOn(ctx: Context, root: File, log: (String) -> Unit) {
        val marker = File(root, "cdn_default_on_applied")
        if (marker.exists()) return
        try {
            var enabled = false
            ServerConfig.update(root, create = false) { config ->
                if (config.opt("cdn_cache") == false) {
                    config.put("cdn_cache", true)
                    enabled = true
                }
            }
            if (enabled) log(ctx.getString(R.string.log_setup_cdn_on))
            marker.writeText("1")
        } catch (_: Exception) {
        }
    }

    private fun appVersion(ctx: Context): String =
        runCatching {
            val pi = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
            @Suppress("DEPRECATION")
            "${pi.versionName}-${pi.versionCode}"
        }.getOrDefault("unknown")

    private fun ensureBundledConfig(ctx: Context, root: File) {
        val destination = File(root, "config.json")
        if (destination.exists()) return
        val defaults = runCatching {
            ctx.assets.open("$PAYLOAD/config.json").bufferedReader().use { it.readText() }
        }.getOrNull() ?: return
        ServerConfig.update(root) { config ->
            if (!destination.exists()) {
                val bundled = org.json.JSONObject(defaults)
                bundled.keys().forEach { key -> config.put(key, bundled.get(key)) }
            }
        }
    }
}
