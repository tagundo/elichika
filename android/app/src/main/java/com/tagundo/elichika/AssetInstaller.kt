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
    private const val MARKER = "installed_version"

    /** Returns the server working dir (== app files dir). */
    @Synchronized
    fun install(ctx: Context, log: (String) -> Unit): File = prepare(ctx, log, reset = false)

    /** Vanilla file restoration; ServerService performs the separate account reset. */
    @Synchronized
    fun resetServerData(ctx: Context, log: (String) -> Unit): File = prepare(ctx, log, reset = true)

    private fun prepare(ctx: Context, log: (String) -> Unit, reset: Boolean): File =
        PayloadUpgrade.withMaintenance(ctx, ctx.filesDir) { prepareLocked(ctx, log, reset) }

    private fun prepareLocked(ctx: Context, log: (String) -> Unit, reset: Boolean): File {
        val root = ctx.filesDir
        val am = ctx.assets
        // The maintenance lease covers recovery, staging cleanup, settings and
        // publishing. A read-only CLEAN result alone would not grant ownership.
        // Recovery precedes the version check, stage cleanup and every live write.
        // Starting raw Python here does not start the editor HTTP servers.
        PayloadUpgrade.recover(ctx, root, log)
        PayloadFiles.clearStages(root)
        val payloadExists = runCatching { am.list(PAYLOAD)?.isNotEmpty() == true }.getOrDefault(false)
        if (!payloadExists) {
            log(ctx.getString(R.string.log_setup_no_payload))
            return root
        }

        val installedVersion = File(root, MARKER).takeIf { it.exists() }?.readText()?.trim()
        val currentVersion = appVersion(ctx)
        check(currentVersion != "unknown") { "Cannot determine the installed application version" }
        val source = object : PayloadFiles.Source {
            override fun list(path: String): Array<String> = am.list(path) ?: emptyArray()
            override fun open(path: String) = am.open(path)
        }
        val required = PayloadFiles.managedFiles(source)
        // Check names/existence without copying large DBs on every server start.
        // A missing core DB also goes through the journal, even at the same version.
        val update = reset || PayloadFiles.needsUpdate(root, installedVersion, currentVersion, required)
        log(ctx.getString(R.string.log_setup_preparing, currentVersion, update.toString()))
        val mode = when {
            reset -> "reset"
            PayloadFiles.hasInstalledData(root, installedVersion) -> "upgrade"
            else -> "fresh"
        }
        val staged = if (update) PayloadFiles.stage(root, source, required) else null
        var enteredUpdater = false
        var committed = false
        try {
            // Existing settings helpers merge only defaults or explicit app choices.
            // Complete them before the updater publishes its final version marker.
            ensureBundledConfig(ctx, root)
            ensureSharedLinks(ctx, root, log)
            ensureCacheDir(ctx, root, log)
            ensureCdnDefaultOn(ctx, root, log)
            ensureLanguage(ctx, root, log)
            if (staged != null) {
                if (mode == "upgrade") log(ctx.getString(R.string.log_setup_preserving_mods))
                enteredUpdater = true
                PayloadUpgrade.apply(ctx, root, staged, installedVersion, currentVersion, mode)
                committed = true
            }
            log(ctx.getString(R.string.log_setup_ready))
            return root
        } finally {
            // If publishing was interrupted, retain its inputs until recover()
            // finishes. Never delete a journal dependency merely because it threw.
            if (staged != null && (!enteredUpdater || committed)) PayloadFiles.removeStage(staged)
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
