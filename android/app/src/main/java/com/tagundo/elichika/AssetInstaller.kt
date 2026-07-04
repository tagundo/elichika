package com.tagundo.elichika

import android.content.Context
import android.os.Environment
import java.io.File

/**
 * Unpacks the bundled server payload (the assets/payload tree, assembled by CI) into
 * the app's files dir, which is also the elichika server's working directory.
 *
 * Overwrite policy:
 *  - static server files (webui/, "server init jsons/", *.pem) are refreshed on
 *    every app upgrade so server changes ride along with a new APK;
 *  - user/state files (config.json, serverdata.db, userdata.db) are only created
 *    when missing, so progress and settings survive an upgrade.
 *
 * A version marker keyed to the APK's versionCode decides when to refresh the
 * static set.
 */
object AssetInstaller {

    private const val PAYLOAD = "payload"
    private const val MARKER = "installed_version"

    // Refresh-on-upgrade (server-owned master data / static assets, safe to overwrite
    // so a new APK ships updated game data). serverdata.db + the harasho assets/ tree +
    // the rekeyed static/ output are all regenerated from the build, not user state.
    private val ALWAYS = listOf(
        "webui", "server init jsons", "privatekey.pem", "publickey.pem",
        "assets", "static", "serverdata.db"
    )
    // Create-if-missing (user-owned, preserve across upgrades).
    private val PRESERVE = listOf("config.json", "userdata.db")

    /** Returns the server working dir (== app files dir). */
    fun install(ctx: Context, log: (String) -> Unit): File {
        val root = ctx.filesDir
        val am = ctx.assets
        val payloadExists = runCatching { am.list(PAYLOAD)?.isNotEmpty() == true }.getOrDefault(false)
        if (!payloadExists) {
            log(ctx.getString(R.string.log_setup_no_payload))
            return root
        }

        val installedVersion = File(root, MARKER).takeIf { it.exists() }?.readText()?.trim()
        val currentVersion = appVersion(ctx)
        val refreshStatic = installedVersion != currentVersion

        log(ctx.getString(R.string.log_setup_preparing, currentVersion, refreshStatic.toString()))
        copyDir(ctx, PAYLOAD, root, refreshStatic, log)

        ensureSharedLinks(ctx, root, log)
        ensureCacheDir(ctx, root, log)
        ensureLanguage(ctx, root, log)
        File(root, MARKER).writeText(currentVersion)
        log(ctx.getString(R.string.log_setup_ready))
        return root
    }

    /**
     * "Reset server": delete every server-owned tree (the ALWAYS set: webui,
     * "server init jsons", *.pem, assets, static, serverdata.db) and re-extract the
     * bundled vanilla payload. Installed/cloned mod costumes live in exactly those
     * files, so this removes them all and puts the game data back to the state the
     * APK shipped with. User-owned files (config.json, userdata.db) are kept — the
     * account wipe runs separately (reset_accounts CLI verb) so logins survive.
     * Must be called with the server stopped.
     */
    fun resetServerData(ctx: Context, log: (String) -> Unit): File {
        val root = ctx.filesDir
        // Never delete anything unless the bundled payload is actually there to
        // restore from (it is absent in non-CI local builds).
        val payloadExists = runCatching { ctx.assets.list(PAYLOAD)?.isNotEmpty() == true }.getOrDefault(false)
        if (!payloadExists) {
            log(ctx.getString(R.string.log_setup_no_payload))
            return root
        }
        for (name in ALWAYS) {
            val f = File(root, name)
            if (f.exists()) {
                log(ctx.getString(R.string.log_reset_removing, name))
                f.deleteRecursively()
            }
        }
        // Dropping the marker forces install() to treat this as a fresh version and
        // re-copy the whole ALWAYS set from the bundled payload.
        File(root, MARKER).delete()
        return install(ctx, log)
    }

    // Termux default that the server injects into config.json on Android.
    private const val SUKUSTA_DEFAULT = "~/storage/downloads/sukusta/packs"

    /**
     * Keep the server WebUI language in sync with the app's language preference
     * (Settings → Language; default = follow system). The app pref is the single
     * source of truth, so this runs every server start.
     */
    private fun ensureLanguage(ctx: Context, root: File, log: (String) -> Unit) {
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
        val cfg = File(root, "config.json")
        if (cfg.exists()) {
            val before = cfg.readText()
            val after = before
                .replace("\"cdn_cache_dir\":\"\"", "\"cdn_cache_dir\":\"$path\"")
                .replace("\"cdn_cache_dir\":\"$SUKUSTA_DEFAULT\"", "\"cdn_cache_dir\":\"$path\"")
                .replace("\"cdn_cache_dir\":\"$oldAppPath\"", "\"cdn_cache_dir\":\"$path\"")
            if (after != before) {
                cfg.writeText(after)
                log(ctx.getString(R.string.log_setup_cdn_dir, path))
            }
        } else {
            // server fills the remaining fields with defaults on first Load().
            // cdn_cache defaults to true so a fresh install serves & caches packs
            // out of the box; the console toggle can still turn it off afterwards
            // (this branch only runs when there is no config.json yet, so it never
            // overrides a choice the user made later).
            cfg.writeText("{\"cdn_cache\":true,\"cdn_cache_dir\":\"$path\"}")
            log(ctx.getString(R.string.log_setup_config_created, path))
        }
    }

    private fun appVersion(ctx: Context): String =
        runCatching {
            val pi = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
            @Suppress("DEPRECATION")
            "${pi.versionName}-${pi.versionCode}"
        }.getOrDefault("unknown")

    private fun copyDir(ctx: Context, assetPath: String, destRoot: File, refreshStatic: Boolean, log: (String) -> Unit) {
        val am = ctx.assets
        val entries = am.list(assetPath) ?: return
        for (name in entries) {
            val childAsset = "$assetPath/$name"
            val children = am.list(childAsset)
            // Path relative to the payload root, used for the overwrite-policy check.
            val rel = childAsset.removePrefix("$PAYLOAD/")
            if (children != null && children.isNotEmpty()) {
                copyDir(ctx, childAsset, destRoot, refreshStatic, log)
            } else {
                val dest = File(destRoot, rel)
                if (shouldWrite(rel, dest, refreshStatic)) {
                    dest.parentFile?.mkdirs()
                    am.open(childAsset).use { input ->
                        dest.outputStream().use { input.copyTo(it) }
                    }
                }
            }
        }
    }

    private fun shouldWrite(rel: String, dest: File, refreshStatic: Boolean): Boolean {
        val top = rel.substringBefore('/')
        return when {
            PRESERVE.contains(top) || PRESERVE.contains(rel) -> !dest.exists()
            ALWAYS.contains(top) || ALWAYS.contains(rel) -> refreshStatic || !dest.exists()
            else -> !dest.exists()
        }
    }
}
